# -*- coding: utf-8 -*-
"""用圈选出来的博文 id 建**分发名单**（普通名单那条路 · 执行层第 3.5 步的另一条走法）。

页面路径：广告后台 → 分发管理 → 3.圈选用户 → 页签「分发名单」→ `新增` →
填名字 → 名单列表类型 = 博客ID → 粘贴博文 id（逗号或换行）→ 分组个数 1 → `提交`。

**跟圈选分开跑**：先用 `run_selection.py` 导出 CSV，看着数量满意了，再用本脚本建名单。

用法：
    # 名单名按命名规则推（--suffix 覆盖 YAML 里的 nameSuffix，如重投第 3 次写 -3）
    .venv\\Scripts\\python.exe -u automation/scripts/run_distribution_ids.py ^
        --csv activities/火山引擎MediaKit/数据/圈选/2026-09-21_D桶96词_圈选博文_20260921.csv ^
        --config activities/火山引擎MediaKit/调整/2026-09-17-D桶换词重投.yaml ^
        --only D --suffix -3 --headed          # 彩排（默认）：填完读回计数后取消

    # 名字直接写死也行
    ... --name "测试名单-火山引擎MediaKit-hang-D类"

    # 真建
    ... 同上 + --submit

彩排/正式：默认彩排（不创建）；`--submit` 才真点提交，提交后**回读核对**并打印名单ID。
安全阀：后台「已输入 N 个有效数据」跟 CSV 行数对不上 → 取消，不提交。
"""
import csv
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign  # noqa: E402
import cli  # noqa: E402
import csdn_ui as ui  # noqa: E402
import list_page  # noqa: E402
import naming  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

DIST_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/resource/list?channelType=page"
PH_LIST_NAME = "填写分发名单"
PH_LIST_FILTER = "分发名单模糊查询"   # 列表页的筛选框（回读核对用）
COUNT_TIMEOUT_S = 180        # 等后台「已输入 N 个有效数据」就绪
ACK_TIMEOUT_S = 300          # 等提交回执「保存成功」：**大样本（10~46 万条 id）服务端要几十秒~几分钟**
                             # （2026-09-28 实测：小样本 0.3 秒回、大样本 2 秒内不回来 → 原实现直接跳页丢回执）
READBACK_MAX_IDS = 20000     # 会话内回读的上限：**超过就不在会话里回读**，改由事后体检核
                             # （2026-09-28 实测：提交 11.3 万条之后，本会话里的任何页面操作都要等 ~190 秒，
                             #  换新标签页也一样——同站标签共用渲染进程；而隔几分钟用只读探针访问只要 6 秒）
ID_COLS = ("article_id", "博文id", "博客ID", "博文ID")   # 新平台导出用英文列名，早期那版是中文别名


def read_ids(path):
    """从圈选 CSV 里取博文 id（保持文件顺序）。两种表头都认：article_id / 博文id。"""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        head = reader.fieldnames or []
        col = next((c for c in ID_COLS if c in head), None)
        if col is None:
            raise SystemExit("CSV 里找不到博文 id 列（试过 %s）｜实际表头：%s"
                             % ("/".join(ID_COLS), head))
        return [r[col].strip() for r in reader if r.get(col)]


def parse_count_hint(text):
    """「提示: 已输入 N 个有效数据」→ N，读不到返回 -1。"""
    m = re.search(r"已输入\s*([\d,]+)\s*个有效数据", text)
    return int(m.group(1).replace(",", "")) if m else -1


def list_name(camp, aud, name_override, suffix):
    """名单名：`--name` 优先，否则按命名规则（`--suffix` 覆盖 YAML 里的 nameSuffix）。"""
    if name_override:
        return name_override
    if suffix:
        aud = dict(aud, nameSuffix=suffix)
    return naming.audience_task_name(camp, aud)


def open_list_page(page):
    """进「圈选用户 → 分发名单」页签，返回页面把手（页面动作在共用层 `list_page`）。"""
    return list_page.open_list(page, menu="圈选用户", tab="分发名单",
                               wait_input=PH_LIST_FILTER)


def _wait_submit_ack(page, timeout):
    """等提交回执（`.el-message` 出现）：返回等了多久（秒），超时返回 -1。

    为什么要等：后台接到 10~46 万条 id 的文本域后要先校验/入库才回「保存成功」，
    大样本要几十秒到几分钟（2026-09-28 实测）。每 15 秒打一行进度，让人看得出在等什么。
    """
    t0 = time.time()
    ticks = 0
    while True:
        if page.locator(".el-message").count() > 0:
            return time.time() - t0
        waited = time.time() - t0
        if waited >= timeout:
            return -1
        if waited > (ticks + 1) * 15:
            ticks += 1
            ui.log("    …仍在等服务端落库回执，已 %.0f 秒（上限 %d 秒）" % (waited, timeout))
        page.wait_for_timeout(150)


def verify_created(page, name, msgs=None):
    """回读核对：翻到「分发名单」页 → 按名字筛 → 取行 → 打印名单ID。命中返回 True。

    ⚠ 大 payload 提交之后**必须在一个新会话里**调它：做提交的那个会话，页面在 ~3 分钟里不可用
    （2026-09-28 实测：同会话回读 192.8 秒、同浏览器换标签页 186.6 秒，而新会话 **5.9 秒**）。
    """
    ui.goto(page, DIST_URL)
    lp = open_list_page(page)
    lp.filter({PH_LIST_FILTER: name})
    lp.query(wait_ms=0, wait_rows=False)      # 下一句已经在等这一行
    row = lp.row_by_name(name, timeout=8)
    if row is None:
        ui.log("  ✗ 回读核对：列表里没找到 %s" % name)
        return False
    ui.log("  ✓ 回读核对：名单ID=%s 名称=%s（提交提示:%s）" % (row.id or "?", name, msgs or []))
    return True


def create_list(s, ids, name):
    """新增分发名单（类型=博客ID）→ 计数校验 → 彩排取消 / 正式提交 → 回读核对。

    2026-09-28 加**分段计时**（`mark()`）：这条路径此前没有任何埋点，「建一份名单要几分钟」
    只能靠感觉、定位不到慢在哪一段（见 `../docs/执行层实测耗时.md` 的「还没量到的」）。
    每段结束打一行 `⏱ <阶段>: 本段 X 秒 · 累计 Y 秒`，纯日志、不改业务行为。
    """
    page = s.page
    t0 = time.time()
    state = {"prev": t0}

    def mark(label):
        now = time.time()
        ui.log("    ⏱ %s: 本段 %.1f 秒 · 累计 %.1f 秒"
               % (label, now - state["prev"], now - t0))
        state["prev"] = now

    ui.goto(page, DIST_URL)
    mark("打开页面")
    lp = open_list_page(page)
    mark("翻开分发名单页")
    # 2026-09-22：读正文前先等**当前页签**的表格出数据（这张表异步加载；
    # 全页数行会被隐藏页签的表误满足）
    ui.log("  分发名单表格就绪:%s" % lp.wait_rows(timeout=12))
    mark("等表格出数据")

    # 重名预检：后台已有同名名单就别再建（回读核对也才能当真）
    lines = [x.strip() for x in page.locator("body").inner_text().splitlines() if x.strip()]
    if name in lines:
        raise RuntimeError("后台已经有同名的分发名单：%s（换 --suffix 或 --name 再来）" % name)
    mark("重名预检（读整页正文）")

    add = page.locator("button:visible").filter(has_text="新增").first
    expect(add).to_be_visible(timeout=10000)
    add.click()

    dlg = ui.dialog(page, "新增分发名单")
    expect(dlg).to_be_visible(timeout=10000)
    mark("打开新增弹窗")
    dlg.locator("input[placeholder='%s']" % PH_LIST_NAME).first.fill(name)
    sel = dlg.locator(".el-select").first
    if "博客ID" not in sel.inner_text():
        ui.select(s, dlg.locator("input").nth(1), "博客ID")
    ui.log("  名单名=%s ｜ 列表类型=%s" % (name, sel.inner_text().strip() or "博客ID"))
    mark("填名单名与类型")

    box = dlg.locator("textarea").first
    expect(box).to_be_visible(timeout=8000)
    t_fill = time.time()
    box.fill(",".join(ids))
    ui.log("  已灌入 %d 个博文 id（%.1f 秒），等后台计数…" % (len(ids), time.time() - t_fill))
    seen = -1
    deadline = time.time() + COUNT_TIMEOUT_S
    while time.time() < deadline:
        seen = parse_count_hint(page.locator("body").inner_text())
        if seen == len(ids):
            break
        # 2026-09-22：轮询步长 2000 → 500ms（后台算完就立刻往下走，不用多等那 1.5 秒）
        page.wait_for_timeout(500)
    ui.log("  后台计数 %d ／ 期望 %d" % (seen, len(ids)))
    mark("灌 id + 等后台计数（上面那条已单独计时）")
    ui.shot(s, "distribution_ids_filled.png")
    if seen != len(ids):
        dlg.locator("button").filter(has_text="取消").first.click()
        raise RuntimeError("后台计数与 CSV 行数对不上，已取消，不提交")

    if s.dry_run:
        dlg.locator("button").filter(has_text="取消").first.click()
        ui.wait_for(page, lambda: not dlg.is_visible(), timeout=5, what="新增弹窗关闭")
        ui.log("  彩排：已取消，未创建")
        mark("彩排取消并关弹窗")
        return True, False

    dlg.locator("button").filter(has_text="提交").first.click()
    mark("点提交（含 Playwright 自动等待）")
    # 2026-09-28 改：**等服务端落库回执**。后台要先校验/入库 10~46 万条 id，回执「保存成功」
    # 可能要几十秒到几分钟；原来只等 2 秒就跳页走人（实测大样本时提示是空的：`提交提示:[]`），
    # 既丢掉了成功/失败信号，也让"到底建成了没"只能靠回读猜。
    waited = _wait_submit_ack(page, ACK_TIMEOUT_S)
    if waited < 0:
        ui.log("  ⚠ 等提交回执超过 %d 秒（继续走，由回读核对兜底）" % ACK_TIMEOUT_S)
    mark("等提交回执（服务端落库）")
    msgs = [m.strip() for m in page.locator(".el-message").all_inner_texts() if m.strip()]

    # 回读核对：**小样本就在会话里核**（快：1 万条实测 2.0 秒）；
    # **大样本跳过**——2026-09-28 实测：提交 11.3 万条之后，本会话里任何页面操作都要等 ~190 秒
    # （回读那一段 192.8 秒 / 换新标签页 186.6 秒；各步的超时上限加起来才 16 秒，说明是页面被拖住），
    # 而这个会话结束后用只读方式访问同一张列表只要 6 秒。所以大样本以**回执**为准，回读交给事后体检。
    if len(ids) <= READBACK_MAX_IDS:
        ok = verify_created(page, name, msgs)
        mark("回读：筛条件 + 等这一行出现")
        return ok, False
    ui.log("  ✓ 提交回执：%s（%d 条 > %d → 本会话不再回读，避免白等 ~3 分钟）"
           % (msgs or ["无"], len(ids), READBACK_MAX_IDS))
    ui.log("     → 由外层**另起一个只读会话**核对（新会话立刻就能读，实测 5~6 秒）")
    mark("收尾")
    return True, True


def main():
    ap = cli.parser("真正点提交（默认彩排）", config=False, only=False, reset_progress=False)
    ap.add_argument("--csv", default="", help="圈选出来的 CSV（取 article_id 列）")
    ap.add_argument("--name", default="", help="分发名单名（不给就按 --config/--only 推）")
    ap.add_argument("--config", default="", help="整活动 / 重投 YAML（推名单名用）")
    ap.add_argument("--only", default="", help="桶（如 D），推名单名用")
    ap.add_argument("--suffix", default="", help="覆盖 YAML 里的 nameSuffix，如 -3")
    ap.add_argument("--verify-only", action="store_true",
                    help="只做回读核对、不建任何东西（大 payload 建完后的「另起进程核对」用）")
    args = ap.parse_args()

    if args.verify_only:
        # 2026-09-28：大 payload 提交过的那个会话，页面 ~3 分钟不可用；
        # **同一个进程里再开一个会话也慢**（实测 ~5 分钟），只有**另起一个进程**才快（5.9 秒）
        # → 核对一律走独立进程（本脚本的 --verify-only 模式），主流程用 subprocess 调它。
        if not args.name:
            raise SystemExit("--verify-only 需要 --name <名单名>")
        try:
            with ui.session(headed=args.headed, dry_run=True) as s:
                ok = verify_created(s.page, args.name)
        except Exception as e:
            ui.log("  ✗ 核对失败:%s" % cli.first_line(e))
            cli.exit_with("HAS_FAILURES", 1)
        cli.exit_with("OK" if ok else "HAS_WARN（回读没查到）", 0 if ok else 1)

    if not args.csv:
        raise SystemExit("要建名单就得给 --csv（或改用 --verify-only --name <名单名> 只核对）")

    if not args.name:
        if not (args.config and args.only):
            raise SystemExit("要么给 --name，要么给 --config + --only 让脚本按命名规则推名字")
        cfg = campaign.load_or_exit(args.config)
        auds = [a for a in cfg["audiences"] if str(a["id"]).upper() == args.only.strip().upper()]
        if not auds:
            raise SystemExit("--config 里没有桶 %s" % args.only)
        name = list_name(cfg["campaign"], auds[0], "", args.suffix)
        act_dir = campaign.activity_dir(args.config)
    else:
        name = args.name
        act_dir = os.path.dirname(os.path.dirname(os.path.abspath(args.csv)))

    ids = read_ids(args.csv)
    ui.log("CSV：%s" % args.csv)
    ui.log("取到 %d 个博文 id ｜ 名单名：%s" % (len(ids), name))
    if not ids:
        raise SystemExit("CSV 里没有 article_id")
    if any(" " in x or "\t" in x for x in ids):
        raise SystemExit("article_id 里有空白字符，先洗一下再灌（后台会当无效数据）")

    shot_dir = os.path.join(act_dir, "日志", "distribution_ids_shots")
    pending_verify = False
    try:
        with ui.session(headed=args.headed, dry_run=not args.submit, shot_dir=shot_dir) as s:
            ok, pending_verify = create_list(s, ids, name)
    except Exception as e:
        ui.log("  ✗ 失败:%s" % cli.first_line(e))
        cli.exit_with("HAS_FAILURES", 1)

    if ok and pending_verify:
        # 2026-09-28：**不能在本进程里补核对**——实测（同一份 113,285 条）：
        #   同进程第二个会话 ~5 分钟 ｜ 从活着的父进程 spawn 子进程 ~2.8 分钟 ｜ **等本进程退出后另起命令 6.3 秒**。
        # 原因：只要上一个浏览器还活着，新的浏览器实例就会被拖住（后台/浏览器重载期）。
        # 所以这里只打印一条**立刻可跑**的核对命令，由下一步（独立命令）做——别再自动化进本进程。
        ui.log("  ⚠ 本会话不回读（会被拖 ~3 分钟）→ 请**等本命令退出后**单独跑这条核对：")
        ui.log("     .venv\\Scripts\\python.exe -u automation/scripts/run_distribution_ids.py"
               " --verify-only --name \"%s\"" % name)
    cli.exit_with("OK" if ok else "HAS_WARN（提交了但回读没查到，下次重跑）", 0 if ok else 1)


if __name__ == "__main__":
    main()
