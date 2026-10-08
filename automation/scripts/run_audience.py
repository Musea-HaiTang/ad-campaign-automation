# -*- coding: utf-8 -*-
"""CSDN 客群 · 圈选用户 数据驱动自动化（创建关键词博客ID圈选任务）

读一份整活动 YAML，逐桶（audiences[]）创建「圈选任务」。

拆开 + 断点续跑（排队/断点/止损在 `bucket_runner.py` 里）：
  - 每桶独立 try/except，单桶失败打印 ✗ 后继续下一桶；首桶/连续 3 桶失败即中止
  - 读/写 activities/{活动名}/日志/audience_progress.json，已完成的桶自动跳过
    （已创建的永远跳过；只是彩排校验过的，正式跑会重跑并真正创建）
  - 彩排默认不点「确定」；--submit 才真正创建
  - 预估总数越界**不跳过**：当场自动调点击阈值（规则在 `audience_policy.py`，最多试 5 次），
    搜到落点就继续创建并写回 thresholds.yaml；搜不到才标 needs_keywords 跳过该桶
    （**曝光阈值锁死 1**：低于下限是词不够，去改词，不降曝光——曝光=0 是虚池，见该模块注释）

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
import campaign  # noqa: E402
import cli  # noqa: E402
import csdn_ui as ui  # noqa: E402
import list_page  # noqa: E402
import naming  # noqa: E402
import audience_policy  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

START_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/resource/list?channelType=page"
CONFIRM_DLG = "圈选任务创建"


# ---------- 进圈选用户的入口 ----------
def open_entry(page):
    """进「圈选用户 → 博文圈选任务」列表（页面动作在共用层 `list_page`）。返回页面把手。"""
    return list_page.open_list(page, menu="圈选用户", tab="博文圈选任务")


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
    （真正建成时是 2 个）。这里改为：重新打开列表，按任务名精确包含查找，找不到就算没过。
    """
    try:
        ui.goto(page, START_URL)
        open_entry(page)
        # 2026-09-22：原来固定死等 1200ms。改成等任务名真的出现在列表里（最多 8 秒，慢也不再误判）
        ui.wait_for(page, lambda: page.get_by_text(task_name, exact=False).count() > 0,
                    timeout=8, what="列表里出现任务名")
        hit = page.get_by_text(task_name, exact=False).count() > 0
        ui.log("  回读核对: %s" % ("✓ 列表里已出现该任务" if hit else "✗ 列表里查不到该任务"))
        return hit
    except Exception as e:
        ui.log("  回读核对异常（按未通过处理）: %s" % e)
        return False


def close_form_dialog(page, dlg):
    x = dlg.locator(".el-dialog__headerbtn").first
    if x.count():
        x.click()
    else:
        c = page.locator("button").filter(has_text="取消").last
        if c.count():
            c.click()
    try:
        expect(page.locator("textarea[placeholder='%s']" % ui.PH_KEYWORDS).first).to_be_hidden(
            timeout=6000
        )
    except Exception:
        pass


# ---------- 断点续跑进度 ----------
def derive_task_name(camp, aud):
    """圈选任务名 = 命名规则算出来的客群名（唯一实现见 `naming.py`）。

    前缀用 `campaign.namePrefix`（不是 taskGroupName——那是「选/建任务组」用的，
    沿用已有组时两者不同）；例：SenseNova征文hang-A类 · 模型部署 / GPU 基础设施。
    """
    return naming.audience_task_name(camp, aud)


def save_thresholds(config, records):
    """把落点写回 thresholds.yaml：**盖格子**——只改这次跑到的桶，其余桶的记录保留。

    `records` 是 `{桶id: 策略结果对象或记录字典}`，两种形状都收；栏位定义在
    `campaign.threshold_record()`（唯一一处）。原先两条写回路径各自拼一遍栏位、
    取值方式还不同（一个 `r["click"]`、一个 `r.click`），加一栏要改三处。
    """
    m = campaign.load_thresholds(config)
    for aid, r in records.items():
        m[aid] = campaign.threshold_record(r)
    campaign.save_thresholds(config, m)


def resolve_thresholds(aud, thr_map, args):
    aid = aud["id"]
    t = thr_map.get(aid, {})
    click = t.get("click", args.click_threshold)
    exp = t.get("exposure", args.exposure_threshold)
    return click, exp


def search_thresholds(page, dlg, args, prev_raw=None, base=audience_policy.NOT_GIVEN):
    """把浏览器侧的动作包成 estimate 端口，喂给纯策略 `audience_policy.search`。

    策略（超上限→升点击；低于下限→needs_keywords 改词、最多试 5 次；**曝光恒为 1**）
    都在那个模块里，这里只负责「设阈值 → 点分析 → 读数字」。
    """
    state = {"raw": prev_raw}

    def estimate(click, exposure):
        cnt, state["raw"] = threshold_analyze(page, dlg, click, exposure, state["raw"])
        return cnt

    return audience_policy.search(estimate, min_count=args.min_count, max_count=args.max_count,
                                  base=base)


def tune_bucket(page, cfg, aud, args):
    camp = cfg["campaign"]
    task_name = derive_task_name(camp, aud) + args.name_suffix
    keywords = aud["keywordGroup"]["keywords"]
    aid = aud["id"]
    ui.log("[%s] %s" % (aid, task_name))
    dlg = open_form(page)
    fill_keywords(page, keywords)
    r = search_thresholds(page, dlg, args)
    close_form_dialog(page, dlg)
    if r.status == audience_policy.OK:
        ui.log("  基线:%s | 调优: 点击≥%s 曝光≥%s | 总数:%s | 落点OK（试了 %d 次）"
               % (r.base, r.click, r.exposure, r.count, r.calls))
    else:
        ui.log("  基线:%s | 调优: %s（建议调整关键词，试了 %d 次）" % (r.base, r.status, r.calls))
    return {"id": aid, "click": r.click, "exposure": r.exposure, "count": r.count,
            "status": r.status, "base": r.base}


def create_one(s, cfg, aud, args, thr_map):
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

    # 调优文件里该桶被标记为 needs_keywords 时，不盲目创建
    tstat = thr_map.get(aid, {}).get("status")
    if tstat and tstat != "ok":
        ui.log("  !! [%s] 调优建议改词(%s)，跳过创建" % (aid, tstat))
        return "warn"
    click_th, exp_th = resolve_thresholds(aud, thr_map, args)

    dlg = open_form(page)
    ok = fill_keywords(page, keywords)
    count, raw = threshold_analyze(page, dlg, click_th, exp_th, _count_raw(dlg))
    ui.log("  预估圈选总数:%s" % count)
    in_range = count is not None and args.min_count <= count <= args.max_count
    if not in_range:
        # 越界不跳过：当场自动调阈值（AGENTS.md 承诺「默认自动 tune、不逐次询问」）
        ui.log("  !! 圈选总数 %s 超出正常范围[%s-%s]，当场自动调点击阈值（曝光锁死 %s）…"
               % (count, args.min_count, args.max_count, audience_policy.BASE_EXPOSURE))
        # 上面刚读过基线，直接传给策略当起点，别再把同一组阈值读一遍
        r = search_thresholds(page, dlg, args, prev_raw=raw, base=count)
        if r.status != audience_policy.OK:
            ui.log("  !! ⚠ 需要你改词：桶 %s 圈中 %s 篇（曝光≥1，不再降曝光），"
                   "调完点击阈值仍不落区间 [%s, %s]（试了 %d 次）"
                   "→ 本桶跳过创建；偏少就加词、偏多就换更精准的词，改完重跑这一桶。"
                   % (aid, r.base, args.min_count, args.max_count, r.calls))
            close_form_dialog(page, dlg)
            return "warn"
        ui.log("  自动调阈值落点：点击≥%s 曝光≥%s | 总数:%s（基线 %s，试了 %d 次）"
               % (r.click, r.exposure, r.count, r.base, r.calls))
        save_thresholds(args.config, {aid: r})   # 落点写回 thresholds.yaml，下次不用再搜

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
    if not verify_created(page, task_name):
        ui.log("  ⚠ 提交后回读查不到该任务 → 记 warn（下次重跑这一桶；结尾 RESULT: HAS_WARN）")
        return "warn"
    return "submitted"


def main():
    ap = cli.parser("真正点『确定』创建圈选任务（默认彩排）")
    ap.add_argument("--click-threshold", type=int, default=0, help="点击需≥（默认 0）")
    ap.add_argument("--exposure-threshold", type=int, default=1, help="曝光需≥（默认 1）")
    ap.add_argument("--min-count", type=int, default=25000,
                    help="圈选总数下限（默认 25000 ≈ 保底 1 万日均曝光；2026-09-21 由 10000 抬高）")
    ap.add_argument("--max-count", type=int, default=200000, help="圈选总数上限（默认 200000）")
    ap.add_argument("--tune", action="store_true", help="调优模式：搜索每桶最佳阈值写报告，不创建")
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
    thr_map = campaign.load_thresholds(args.config)
    prefix = naming.require_prefix(ctx.cfg["campaign"])

    # 删圈选任务：只删客人给的这些名字，不建任何东西
    if args.delete:
        with ctx.session(args, dry_run=False) as s:
            lp = am.open_tab(s.page, url=am.DISTUSER_URL)
            am.apply_filters(lp, prefix=prefix, log=ui.log)
            gone = am.delete_tasks(lp, args.delete, log=ui.log)
        sys.exit(0 if len(gone) == len(args.delete) else 1)

    # 调优模式不记账本（它不创建任何东西，跑几趟都一样）
    # 试圈（--name-suffix）走**单独的账本文件**：它建的不是正式客群，别污染正式那本
    # （踩坑 2026-09-21：不带后缀时正式账本记着 submitted → 试圈直接被跳过，一个都没建，还空等了 10 分钟）
    if not args.tune:
        prog_file = "audience_progress.json"
        if args.name_suffix:
            safe = re.sub(r"[^\w\-]+", "", args.name_suffix) or "suffix"
            prog_file = "audience_progress.%s.json" % safe
        ctx.progress = cli.open_progress(ctx.act_dir, prog_file, reset=args.reset_progress)

    try:
        with ctx.session(args) as s:
            page = s.page
            ui.log("类型:%s | 桶数:%d | submit:%s"
                   % (ctx.cfg["label"], len(ctx.auds), args.submit))
            ui.goto(page, START_URL)
            open_entry(page)

            if args.tune:
                ui.log("TUNE 模式：搜索每桶最佳点击阈值（曝光锁死 1），写报告，不创建。")
                results = []

                def tune_one(aud):
                    try:
                        r = tune_bucket(page, ctx.cfg, aud, args)
                    except Exception:
                        results.append({"id": aud["id"], "click": None, "exposure": None, "count": None,
                                        "status": "fail", "base": None})
                        raise
                    results.append(r)
                    return True if r.get("status") == "ok" else "warn"

                ctx.report = bucket_runner.run_buckets(
                    ctx.auds, tune_one,
                    describe=lambda aud: "[%s] %s" % (aud["id"], task_group),
                    on_item_fail=lambda aud: ui.dismiss_dialogs(page),
                    log=ui.log, unit="桶", rest="桶")
                save_thresholds(args.config, {r["id"]: r for r in results})
                okc = 0
                ui.log("---- 调优报告 ----")
                for r in results:
                    if r.get("status") == "ok":
                        okc += 1
                        ui.log("  [%s] 点击≥%s 曝光≥%s | 总数:%s | 基线:%s"
                               % (r["id"], r["click"], r["exposure"], r["count"], r.get("base")))
                    else:
                        ui.log("  [%s] %s | 基线:%s" % (r["id"], r.get("status"), r.get("base")))
                ui.log("调优结果: %d 落点OK / %d 需处理 | 阈值文件:%s"
                       % (okc, len(results) - okc, campaign.thresholds_path(args.config)))
            else:
                ctx.report = bucket_runner.run_buckets(
                    ctx.auds,
                    lambda aud: create_one(s, ctx.cfg, aud, args, thr_map),
                    key_of=lambda aud: "%s|%s" % (task_group, aud["id"]),
                    describe=lambda aud: "[%s] %s" % (aud["id"], task_group),
                    progress=ctx.progress,
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
