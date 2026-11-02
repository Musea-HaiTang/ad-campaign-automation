# -*- coding: utf-8 -*-
"""桶运行策略（工头）：四个 run_*.py 共用的循环 / 断点 / 止损 / 结果口径。

工头只管「排队」——逐项调 run_one、记账本、失败清场、到点止损、汇总结果。
它不认页面、不读 YAML、也不 import playwright，所以能脱浏览器单测
（见 `automation/tests/test_bucket_runner.py`）。

契约（`automation/README.md`「设计原则」）：
  - 每项独立 try/except，单项失败不影响下一项；
  - 跑前读「已完成清单」支持断点续跑；
  - 首项失败 / 连续 3 项失败即中止；
  - RESULT 三态 OK / HAS_WARN / HAS_FAILURES，只有 OK 返回 0。
"""
import json
import os
import tempfile
import time

import execution_state as es

OK = "OK"
HAS_WARN = "HAS_WARN"
HAS_FAILURES = "HAS_FAILURES"

# 账本里的状态值
SUBMITTED = "submitted"   # 已在后台真正创建 → 永远跳过
DONE = "done"             # 彩排已校验 → 只有彩排才跳过；正式跑要重跑并真正创建
WARN = "warn"
FAIL = "fail"
SUBMITTING = "submitting"            # 已开始本次写入，结果尚未安全落账
NEEDS_RECONCILE = "needs_reconcile"  # 结果无法确认，必须先查远端再决定

ABORT_AFTER = 3   # 连续失败多少项即中止


class PreSubmitValidationError(RuntimeError):
    """表单填写完成后仍有字段失败；此时尚未提交，可安全地整项重试。"""


def pre_submit_error(steps):
    """提交前字段步骤有失败时返回可重试异常，全通过返回 None。"""
    if steps_status(steps) != WARN:
        return None
    bad = "、".join(name for name, result in steps if result != "ok")
    return PreSubmitValidationError("提交前校验未通过（%s）" % bad)


def _norm(result):
    """run_one 的返回值 → 账本状态：True/None=完成，False=失败，字符串原样收下。"""
    if result is True or result is None:
        return DONE
    if result is False:
        return FAIL
    return str(result).strip() or DONE


def _first_line(exc):
    txt = str(exc).splitlines()
    line = txt[0] if txt else str(exc)
    return line[:140]


def steps_status(steps):
    """一个桶的「步骤体检」结果 → 账本状态（彩排口径，2026-09-11 修假通过）。

    steps 是 [(步骤名, 结果)]，结果只有 "ok" / "fail"。
      - 全部 ok   → True  → 账本记 done，下次彩排跳过；
      - 有一步 fail → "warn" → 账本记 warn：**下次还会重跑**，并计入 RESULT: HAS_WARN（退出码 1）。
    以前彩排一律 return True，步骤 fail 也记 done：界面上一堆 ✗，结尾却 RESULT: OK、下次还跳过。
    """
    return True if all(r == "ok" for _, r in steps) else WARN


class Progress:
    """断点账本：一个 JSON 文件存 {键: 状态}。

    彩排读不出来就降级为空账本；正式提交使用 strict=True，文件存在但损坏时
    必须停止。文件不存在仍视为首次运行。写入先落同目录临时文件并刷盘，
    再原子替换正式文件；中途失败不会留下半截账本。
    """

    def __init__(self, path, reset=False, strict=False):
        self.path = path
        self.data = {} if reset else self._load(strict=strict)

    def _load(self, *, strict=False):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            if strict:
                raise ValueError("进度账本无法读取：%s（%s）" % (self.path, e))
            return {}
        if not isinstance(data, dict):
            if strict:
                raise ValueError("进度账本顶层必须是对象：%s" % self.path)
            return {}
        return data

    def get(self, key):
        return self.record(key).get("status")

    def record(self, key):
        value = self.data.get(key)
        if isinstance(value, dict):
            return dict(value)
        return {"status": value} if value is not None else {}

    def _set_record(self, key, value):
        data = dict(self.data)
        data[key] = value
        _write_json_atomic(self.path, data)
        self.data = data

    def set(self, key, value):
        old = self.record(key)
        if old.get("payload_hash") or old.get("remote_id"):
            old["status"] = value
            self._set_record(key, old)
        else:
            self._set_record(key, value)

    def start(self, key, payload_hash=None):
        self._set_record(key, {
            "status": SUBMITTING,
            "payload_hash": payload_hash,
        })

    def finish(self, key, status, *, remote_id="", reason=""):
        record = self.record(key)
        record.update({
            "status": status,
            "remote_id": str(remote_id or record.get("remote_id") or ""),
        })
        if reason:
            record["reason"] = reason
        detail_keys = ("payload_hash", "remote_id", "reason")
        if not any(record.get(name) for name in detail_keys):
            self._set_record(key, status)
        else:
            self._set_record(key, record)


def _write_json_atomic(path, data):
    """账本整体写完、刷盘后，再用同目录临时文件原子替换旧文件。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


class RunReport:
    """这一趟的结果：计数 + 三态。

    脚本自己 catch 到的致命错误（起浏览器就挂等）用 `report.fatal = True` 记上。
    """

    def __init__(self):
        self.total = 0        # 清单总项数
        self.attempted = 0    # 真正尝试过几项
        self.done = 0         # 完成（含已提交）
        self.warned = 0       # 有警告
        self.failed = 0       # 失败
        self.skipped = 0      # 断点跳过
        self.aborted = False  # 触发了止损
        self.fatal = False    # 循环外就挂了
        self.seconds = 0.0    # 这一趟实际耗时（秒）

    @property
    def status(self):
        if self.fatal or self.failed:
            return HAS_FAILURES
        return HAS_WARN if self.warned else OK

    def exit_code(self):
        return 0 if self.status == OK else 1


def run_buckets(items, run_one, *, key_of=None, describe=None, progress=None,
                on_item_fail=None, on_item_retry=None, on_retry=None,
                retry=0, should_retry=None,
                reconcile=None, payload_of=None,
                log=print, dry_run=True,
                abort_after=ABORT_AFTER, unit="项", rest="项"):
    """逐项跑：跳过已完成 → run_one → 记账 → 失败清场 → 首项/连续 N 项止损。

    items        待跑的项
    run_one(item) 干这一项；True/None=完成，False=失败，也可直接返回状态字符串
    key_of(item)  这一项的账本键（默认用序号）
    describe(item) 日志里怎么称呼这一项（默认用账本键）
    progress      Progress 账本；不给就不记断点
    on_item_fail(item) 某项失败后清场（关残留弹窗）；它自己抛错不影响主流程
    on_item_retry(item) 重试前把页面恢复（重开列表页）；它自己抛错不影响主流程
    on_retry(item, exc) 优先于 on_item_retry；可先判断异常类型并恢复浏览器，再重开页面
    retry         每项失败后**自动重试几次**（默认 0）——治后台页面渲染抖动（下拉 0 选项 /
                  浮现层没散），2026-10-15 加：先清场、再 on_item_retry 重开页面、再跑一遍
    should_retry(item, exc) 这一项该不该重试（默认都重试）。⛔ 已经点过「提交/确定」的失败
                  **必须返回 False**，否则重试 = 重复创建（调用方自己盯一个 submitted 标志）
    dry_run       彩排只看「彩排已校验」就跳过；正式跑不跳（要真正创建）
    reconcile     仅对上次中断/未确认的项做定点远端对账：item → RemoteState
                 新建项不会触发远端预读
    payload_of    同一业务键本次要写入的业务载荷；用于发现同键不同内容
    abort_after   连续失败多少项即中止（首项失败一律中止）
    unit / rest   日志用词：如 unit="条"、rest="条目"
    """
    report = RunReport()
    items = list(items)
    report.total = len(items)
    fail_streak = 0
    t_start = time.perf_counter()

    for i, item in enumerate(items, 1):
        key = key_of(item) if key_of else str(i)
        say = describe(item) if describe else str(key)
        record = progress.record(key) if progress else {}
        state = record.get("status")
        payload = payload_of(item) if payload_of else None
        current_hash = es.payload_hash(payload) if payload is not None else None
        remote_state = None
        uncertain = state in (SUBMITTING, NEEDS_RECONCILE, WARN, FAIL)

        if reconcile and not dry_run and uncertain:
            try:
                remote_state = es.normalize(reconcile(item))
            except Exception as e:
                remote_state = es.unknown(_first_line(e))

        if remote_state and remote_state.is_unknown:
            report.warned += 1
            if progress:
                progress.set(key, NEEDS_RECONCILE)
            log("RECONCILE %s（远端未确认：%s）"
                % (say, remote_state.reason or "查询失败"))
            continue

        if remote_state and remote_state.is_found:
            old_hash = record.get("payload_hash")
            if old_hash and current_hash and old_hash != current_hash:
                report.warned += 1
                if progress:
                    progress.set(key, NEEDS_RECONCILE)
                log("CONFLICT %s（同一业务键的 payload 已变化，远端对象 %s）"
                    % (say, remote_state.object_id or "?"))
                continue
            report.skipped += 1
            if progress:
                progress.finish(key, SUBMITTED, remote_id=remote_state.object_id,
                                reason=remote_state.reason or "中断后对账命中")
            log("REUSE %s（远端已存在：%s）"
                % (say, remote_state.object_id or state or "?"))
            continue

        if state == SUBMITTED:
            report.skipped += 1
            log("SKIP %s（已创建:%s）" % (say, state))
            continue

        if state == DONE and dry_run:
            report.skipped += 1
            log("SKIP %s（彩排已校验:%s）" % (say, state))
            continue

        report.attempted += 1
        error = None
        t0 = time.perf_counter()
        attempt = 0
        if not dry_run and progress:
            try:
                progress.start(key, current_hash)
            except Exception as e:
                report.failed += 1
                report.fatal = True
                report.seconds = time.perf_counter() - t_start
                log("!! 无法写提交中状态，已停止：%s" % _first_line(e))
                return report
        while True:
            attempt += 1
            error = None
            try:
                result = _norm(run_one(item))
            except Exception as e:
                error, result = e, FAIL
            if result != FAIL or attempt > retry:
                break
            if should_retry and not should_retry(item, error):
                break
            log("  ↻ %s 失败:%s → 清场 + 重开页面后重试（第 %d 次）"
                % (say, _first_line(error) if error else "返回失败", attempt))
            if on_item_fail:
                try:
                    on_item_fail(item)
                except Exception:
                    pass
            if on_retry:
                try:
                    on_retry(item, error)
                except Exception:
                    pass
            elif on_item_retry:
                try:
                    on_item_retry(item)
                except Exception:
                    pass
        elapsed = time.perf_counter() - t0

        if result == FAIL:
            report.failed += 1
            fail_streak += 1
            log("  ✗ %s 失败:%s" % (say, _first_line(error) if error else "返回失败"))
            log("  ⏱ 用时 %.1f 秒" % elapsed)
            if progress:
                progress.finish(
                    key, FAIL if dry_run else NEEDS_RECONCILE)
            if on_item_fail:
                try:
                    on_item_fail(item)
                except Exception:
                    pass
            if report.attempted == 1:
                log("!! 首%s即失败，疑似系统性配置问题（任务组名/子业务线/页面结构），已中止后续%s。"
                    % (unit, rest))
                report.aborted = True
                break
            if abort_after and fail_streak >= abort_after:
                log("!! 连续 %d %s失败，已中止后续%s。" % (fail_streak, unit, rest))
                report.aborted = True
                break
            continue

        fail_streak = 0
        if result == WARN:
            report.warned += 1
        else:
            report.done += 1
        if progress:
            final_result = (
                NEEDS_RECONCILE
                if not dry_run and result not in (SUBMITTED, NEEDS_RECONCILE)
                else result
            )
            progress.finish(key, final_result,
                            remote_id=(remote_state.object_id if remote_state else ""))
        log("  ⏱ 用时 %.1f 秒" % elapsed)

    report.seconds = time.perf_counter() - t_start
    log("⏱ 总用时 %.1f 秒（跑了 %d %s，跳过 %d %s）"
        % (report.seconds, report.attempted, unit, report.skipped, rest))
    return report
