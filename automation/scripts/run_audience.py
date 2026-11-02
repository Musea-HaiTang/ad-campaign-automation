# -*- coding: utf-8 -*-
"""CSDN 客群 · 圈选用户 数据驱动自动化（创建关键词博客ID圈选任务）

读一份整活动 YAML，逐桶（audiences[]）创建「圈选任务」。

拆开 + 断点续跑（排队/断点/止损在 `bucket_runner.py` 里）：
  - 每桶独立 try/except，单桶失败打印 ✗ 后继续下一桶；首桶/连续 3 桶失败即中止
  - 读/写 activities/{活动名}/日志/audience_progress.json，已完成的桶自动跳过
    （已创建的永远跳过；只是彩排校验过的，正式跑会重跑并真正创建）
  - 彩排默认不点「确定」；--submit 才真正创建
  - 「预估圈选总数」只记录日志，不作为创建门槛，也不据此调整阈值
  - 创建后按后台「日均曝光(预估) ≥ 10000」验收；博文 ID 数不参与达标判断

页面交互（会话/下拉/弹窗/截图）都在 `csdn_ui.py` 里；本脚本只管「这次要办什么」。

用法：
    .venv\\Scripts\\python.exe -u automation/scripts/run_audience.py --config activities/sensenova/SenseNova征文hang.yaml
  加 --submit 真正创建；加 --headed 显示窗口。
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bucket_runner  # noqa: E402
import audience_metrics as am  # noqa: E402
import cli  # noqa: E402
import csdn_ui as ui  # noqa: E402
import execution_state as es  # noqa: E402
import list_page  # noqa: E402
import naming  # noqa: E402
import remote_lookup  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

START_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/resource/list?channelType=page"
CONFIRM_DLG = "圈选任务创建"
PH_AUD_FILTER = "请输入圈选任务名称"


# ---------- 进圈选用户的入口 ----------
def open_entry(page):
    """进「圈选用户 → 博文圈选任务」列表（页面动作在共用层 `list_page`）。返回页面把手。"""
    return list_page.open_list(
        page, menu="圈选用户", tab="博文圈选任务", wait_input=PH_AUD_FILTER)


def open_form(page):
    # 先清掉上个实例可能残留的弹窗，避免遮罩挡住「创建圈选任务」
    ui.dismiss_dialogs(page)
    btn = page.locator("button.el-button--primary:visible").filter(has_text="创建圈选任务").first
    expect(btn).to_be_visible(timeout=10000)
    btn.click()
    expect(page.locator("textarea[placeholder='%s']" % ui.PH_KEYWORDS).first).to_be_visible(
        timeout=12000
    )
    dlg = ui.dialog(page, "圈选任务")
    expect(dlg).to_be_visible(timeout=8000)
    return dlg


# ---------- 表单流程 ----------
def fill_keywords(page, keywords):
    ta = page.locator("textarea[placeholder='%s']" % ui.PH_KEYWORDS).first
    expect(ta).to_be_visible(timeout=8000)
    ta.fill(keywords)
    actual = ta.input_value()
    ok = actual == keywords
    ui.log("  关键词列表 %s | %d 字符" % ("✓" if ok else "✗", len(actual)))
    return ok


def fill_thresholds(page, click_th, exp_th):
    item = page.locator(".el-form-item").filter(has_text="数据阈值控制").first
    expect(item).to_be_visible(timeout=8000)
    inputs = item.locator("input.el-input__inner")
    expect(inputs.nth(0)).to_be_visible(timeout=6000)
    inputs.nth(0).fill(str(click_th))
    inputs.nth(1).fill(str(exp_th))
    ok = inputs.nth(0).input_value() == str(click_th) and inputs.nth(1).input_value() == str(exp_th)
    ui.log("  数据阈值 %s | 点击≥%s 曝光≥%s" % ("✓" if ok else "✗", click_th, exp_th))
    return ok


def _count_raw(dlg):
    try:
        return dlg.get_by_text("预估圈选总数", exact=False).first.inner_text()
    except Exception:
        return None


def parse_count(txt):
    if not txt:
        return None
    m = re.search(r"预估圈选总数[：:]\s*([\d,]+)\s*个", txt)
    return int(m.group(1).replace(",", "")) if m else None


def analyze(page, dlg, prev_raw=None):
    """点『idf分析与总数预估』，等计数文本变化（或首次出现）后返回 (count, raw)。"""
    btn = dlg.locator("button.el-button--primary:visible").filter(has_text="idf分析与总数预估").first
    expect(btn).to_be_visible(timeout=8000)
    btn.click()
    deadline = time.time() + 25
    while time.time() < deadline:
        raw = _count_raw(dlg)
        if raw and raw != prev_raw:
            return parse_count(raw), raw
        time.sleep(0.3)
    raw = _count_raw(dlg)
    return parse_count(raw), raw


def threshold_analyze(page, dlg, click, exp, prev_raw=None):
    """设阈值 → 点分析 → 读新总数，返回 (count, raw)。"""
    fill_thresholds(page, click, exp)
    return analyze(page, dlg, prev_raw)


def open_confirm(page, dlg):
    btn = dlg.locator("button.el-button--primary:visible").filter(has_text="创建圈选任务").first
    expect(btn).to_be_visible(timeout=8000)
    btn.click()
    cd = ui.dialog(page, CONFIRM_DLG)
    expect(cd).to_be_visible(timeout=12000)
    expect(cd.locator("input[placeholder='%s']" % ui.PH_USER_NAME).first).to_be_visible(timeout=8000)
    return cd


def select_subline(s, cd, value):
    ui.select(s, cd.locator("input[placeholder='%s']" % ui.PH_SUBLINE).first, value)
    ui.log("  子业务线/用户组:", value)


def fill_name(cd, name):
    box = cd.locator("input[placeholder='%s']" % ui.PH_USER_NAME).first
    expect(box).to_be_visible(timeout=8000)
    box.fill(name)
    actual = box.input_value()
    ok = actual == name
    ui.log("  圈选任务名称 %s | %r" % ("✓" if ok else "✗", name))
    return ok


def submit_or_cancel(s, cd, ok=True):
    """彩排：关掉弹窗；正式：**先过闸**再点「确定」，返回"是否真的提交了"。

    ⛔ 提交前闸门（2026-09-22 加，跟 `run_taskorder` 同一规矩）：字段校验（圈选任务名 / 子业务线）没过**就不提交**。
    原来正式路径不看 `ok`，校验失败也照样点「确定」——而事后的 `verify_created()` 只查"任务名在不在列表里"，
    查不出字段缺失（名字对、子业务线没绑上这种事它发现不了）。
    """
    page = s.page
    if not s.dry_run:
        if not ok:
            ui.log("  !! 字段校验没通过 → **不提交**，记 warn（下次重跑这一桶）")
            cancel = cd.locator("button").filter(has_text="取消").last
            if cancel.count():
                cancel.click()
            ui.dismiss_dialogs(page)
            return False
        btn = cd.locator("button.el-button--primary").filter(has_text="确定").last
        expect(btn).to_be_visible(timeout=8000)
        btn.click()
        try:
            expect(cd).to_be_hidden(timeout=15000)
        except Exception:
            pass
        msgs = page.locator(".el-message").all_inner_texts()
        ui.log("  提交 | 提示:%s" % msgs)
        return True
    cancel = cd.locator("button").filter(has_text="取消").last
    if cancel.count():
        cancel.click()
    ui.dismiss_dialogs(page)
    ui.log("  彩排：未提交，已关闭")
    return True


def verify_created(page, task_name):
    """提交后**回后台列表核对**任务名是否真的存在（防"假通过"）。

    背景（2026-09-14 踩坑）：老实现点完「确定」只等弹窗关闭 + 读 `.el-message` 提示，
    后台其实没落库时也会记 `submitted`——A、E 各踩过一次，特征是提示只有 1 个「操作成功！」
    （真正建成时是 2 个）。这里只认完整任务名的精确行。
    """
    try:
        lp = remote_lookup.open(
            page, START_URL, menu="圈选用户", tab="博文圈选任务",
            filter_placeholder=PH_AUD_FILTER)
        state = remote_lookup.exact(lp, task_name, PH_AUD_FILTER)
        ui.log("  回读核对: %s" % (
            "✓ 精确命中完整任务名" if state.is_found else
            "✗ 已确认不存在完整任务名" if state.is_absent else
            "? 未确认（%s）" % state.reason))
        return state
    except Exception as e:
        reason = str(e).splitlines()[0][:120]
        ui.log("  回读核对异常（记未确认）: %s" % reason)
        return es.unknown(reason)


# ---------- 断点续跑进度 ----------
def derive_task_name(camp, aud):
    """圈选任务名 = 命名规则算出来的客群名（唯一实现见 `naming.py`）。

    前缀用 `campaign.namePrefix`（不是 taskGroupName——那是「选/建任务组」用的，
    沿用已有组时两者不同）；例：SenseNova征文hang-A类 · 模型部署 / GPU 基础设施。
    """
    return naming.audience_task_name(camp, aud)


def create_one(s, cfg, aud, args):
    page = s.page
    camp = cfg["campaign"]
    task_name = derive_task_name(camp, aud) + args.name_suffix
    keywords = aud["keywordGroup"]["keywords"]
    sub_line = aud["subBusinessLine"]
    aid = aud["id"]
    ui.log("[%s] %s" % (aid, task_name))
    name_warning = naming.name_warning(camp, aud)
    if name_warning:
        ui.log("  %s" % name_warning)

    click_th = aud.get("clickThreshold", args.click_threshold)
    exp_th = aud.get("exposureThreshold", args.exposure_threshold)

    dlg = open_form(page)
    ok = fill_keywords(page, keywords)
    count, _ = threshold_analyze(page, dlg, click_th, exp_th, _count_raw(dlg))
    ui.log("  预估圈选总数:%s（仅记录，不作为标准）" % count)

    cd = open_confirm(page, dlg)
    select_subline(s, cd, sub_line)
    ok = fill_name(cd, task_name) and ok
    ui.shot(s, "aud_%s_filled.png" % aid)
    ui.log("  字段校验:%s" % ok)
    submitted = submit_or_cancel(s, cd, ok)
    if s.dry_run:
        if not ok:
            ui.log("  ⚠ 字段校验没全过 → 记 warn（下次会重跑，结尾 RESULT: HAS_WARN）")
            return "warn"
        return "done"
    if not submitted:
        # 闸门拦下：根本没提交，不能记 submitted（账本里 submitted 是"永远跳过"）
        return "warn"
    # 正式创建：必须回读后台确认，别把"点了确定"当"建成了"（2026-09-14 踩坑）
    state = verify_created(page, task_name)
    if not state.is_found:
        ui.log("  ⚠ 提交后回读未确认该任务 → 下次先远端对账，不盲重建")
        return bucket_runner.NEEDS_RECONCILE
    return "submitted"


def main():
    ap = cli.parser("真正点『确定』创建圈选任务（默认彩排）")
    ap.add_argument("--click-threshold", type=int, default=0, help="点击需≥（默认 0）")
    ap.add_argument("--exposure-threshold", type=int, default=1, help="曝光需≥（默认 1）")
    ap.add_argument("--verify", action="store_true",
                    help="建完不关浏览器：每 N 秒点一次「查询」，读到「日均曝光(预估)」再判达标")
    ap.add_argument("--verify-interval", type=int, default=10, help="体检轮询间隔秒（默认 10）")
    ap.add_argument("--verify-timeout", type=int, default=900, help="体检最多等多少秒（默认 900）")
    ap.add_argument("--delete", action="append", default=[], metavar="圈选任务名",
                    help="删圈选任务（可重复传）：先「停止」→ 勾选 → 「批量删除」→ 确认；只动圈选任务")
    ap.add_argument("--name-suffix", default="",
                    help="给这趟建的圈选任务名加后缀（**试圈用**：先建一版看数据、不动正式客群名；看完用 --delete 删）")
    args = ap.parse_args()

    ctx = cli.context(args, shots="audience_shots")   # 账本名随 --name-suffix 变，自己开
    task_group = ctx.cfg["campaign"]["taskGroupName"]
    prefix = naming.require_prefix(ctx.cfg["campaign"])

    # 删圈选任务：只删客人给的这些名字，不建任何东西
    if args.delete:
        with ctx.session(args, dry_run=False) as s:
            lp = am.open_tab(s.page, url=am.DISTUSER_URL)
            am.apply_filters(lp, prefix=prefix, log=ui.log)
            gone = am.delete_tasks(lp, args.delete, log=ui.log)
        sys.exit(0 if len(gone) == len(args.delete) else 1)

    # 试圈（--name-suffix）走**单独的账本文件**：它建的不是正式客群，别污染正式那本
    # （踩坑 2026-09-21：不带后缀时正式账本记着 submitted → 试圈直接被跳过，一个都没建，还空等了 10 分钟）
    prog_file = "audience_progress.json"
    if args.name_suffix:
        safe = re.sub(r"[^\w\-]+", "", args.name_suffix) or "suffix"
        prog_file = "audience_progress.%s.json" % safe
    ctx.progress = cli.open_progress(
        ctx.act_dir, prog_file, reset=args.reset_progress, strict=args.submit)

    try:
        with ctx.session(args) as s:
            page = s.page
            ui.log("类型:%s | 桶数:%d | submit:%s"
                   % (ctx.cfg["label"], len(ctx.auds), args.submit))
            ui.goto(page, START_URL)
            open_entry(page)

            ctx.report = bucket_runner.run_buckets(
                ctx.auds,
                lambda aud: create_one(s, ctx.cfg, aud, args),
                key_of=lambda aud: "%s|%s" % (task_group, aud["id"]),
                describe=lambda aud: "[%s] %s" % (aud["id"], task_group),
                progress=ctx.progress,
                reconcile=lambda aud: verify_created(
                    page, derive_task_name(ctx.cfg["campaign"], aud) + args.name_suffix),
                payload_of=lambda aud: {
                    "taskName": derive_task_name(ctx.cfg["campaign"], aud) + args.name_suffix,
                    "bucket": aud["id"],
                    "subBusinessLine": aud["subBusinessLine"],
                    "keywords": (aud.get("keywordGroup") or {}).get("keywords", ""),
                    "clickThreshold": aud.get("clickThreshold", args.click_threshold),
                    "exposureThreshold": aud.get("exposureThreshold", args.exposure_threshold),
                },
                on_item_fail=lambda aud: ui.dismiss_dialogs(page),
                log=ui.log,
                dry_run=not args.submit,
                unit="桶", rest="桶")

            # 建完体检：浏览器不关，就在这一页反复点「查询」，等后台把预估算出来
            if args.verify and args.submit:
                # 只体检**后台确实有**的桶（跳过/未建成的没得看）
                live = [a for a in ctx.auds
                        if ctx.progress.get("%s|%s" % (task_group, a["id"])) == "submitted"]
                if not live:
                    ui.log("---- 建完体检：这一趟没有真建成的桶，跳过 ----")
                else:
                    names = [derive_task_name(ctx.cfg["campaign"], a) + args.name_suffix
                             for a in live]
                    ui.log("---- 建完体检：%d 个桶，每 %ds 点一次「查询」，最多等 %ds ----"
                           % (len(names), args.verify_interval, args.verify_timeout))
                    lp = am.open_tab(page)
                    am.apply_filters(lp, prefix=prefix, log=ui.log)
                    metrics = am.wait_ready(lp, names, timeout_s=args.verify_timeout,
                                            interval_s=args.verify_interval, prefix=prefix,
                                            log=ui.log)
                    am.report(names, metrics, log=ui.log)
            elif args.verify:
                ui.log("（--verify 只在 --submit 真建了任务之后才有意义，彩排跳过）")
    except Exception as e:
        cli.fatal(ctx, e)
    cli.finish(ctx.report)


if __name__ == "__main__":
    main()
