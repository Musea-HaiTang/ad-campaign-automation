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
import time

OK = "OK"
HAS_WARN = "HAS_WARN"
HAS_FAILURES = "HAS_FAILURES"

# 账本里的状态值
SUBMITTED = "submitted"   # 已在后台真正创建 → 永远跳过
DONE = "done"             # 彩排已校验 → 只有彩排才跳过；正式跑要重跑并真正创建
WARN = "warn"
FAIL = "fail"

ABORT_AFTER = 3   # 连续失败多少项即中止


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

    读不出来（文件不存在/写坏了）就当空账本，不让脚本躺下。
    """

    def __init__(self, path, reset=False):
        self.path = path
        self.data = {} if reset else self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


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
                on_item_fail=None, log=print, dry_run=True,
                abort_after=ABORT_AFTER, unit="项", rest="项"):
    """逐项跑：跳过已完成 → run_one → 记账 → 失败清场 → 首项/连续 N 项止损。

    items        待跑的项
    run_one(item) 干这一项；True/None=完成，False=失败，也可直接返回状态字符串
    key_of(item)  这一项的账本键（默认用序号）
    describe(item) 日志里怎么称呼这一项（默认用账本键）
    progress      Progress 账本；不给就不记断点
    on_item_fail(item) 某项失败后清场（关残留弹窗）；它自己抛错不影响主流程
    dry_run       彩排只看「彩排已校验」就跳过；正式跑不跳（要真正创建）
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
        state = progress.get(key) if progress else None

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
        try:
            result = _norm(run_one(item))
        except Exception as e:
            error, result = e, FAIL
        elapsed = time.perf_counter() - t0

        if result == FAIL:
            report.failed += 1
            fail_streak += 1
            log("  ✗ %s 失败:%s" % (say, _first_line(error) if error else "返回失败"))
            log("  ⏱ 用时 %.1f 秒" % elapsed)
            if progress:
                progress.set(key, FAIL)
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
            progress.set(key, result)
        log("  ⏱ 用时 %.1f 秒" % elapsed)

    report.seconds = time.perf_counter() - t_start
    log("⏱ 总用时 %.1f 秒（跑了 %d %s，跳过 %d %s）"
        % (report.seconds, report.attempted, unit, report.skipped, rest))
    return report
