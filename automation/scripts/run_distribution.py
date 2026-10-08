# -*- coding: utf-8 -*-
"""CSDN 客群 · 一键创建分发名单（执行层第 3.5 步）

圈选任务建好后，每一条都要在「圈选用户 → 博文圈选任务」列表里点**该行**的
「一键创建分发名单」，才会生成与圈选任务同名的用户名单；第 4 步工单的
「分发方式 = 分发名单 → 选用户名单」才选得到（名字必须一致）。

用法：
    .venv\\Scripts\\python.exe -u automation/scripts/run_distribution.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml
    默认 dry-run：只点开按钮、打印弹窗内容 + 截图，然后取消，**不创建**
    加 --submit 真正点「确定」创建；加 --only A（或 --only A,C）只做指定桶

断点账本：activities/{活动名}/日志/distribution_progress.json（键 = 任务组|桶）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bucket_runner  # noqa: E402
import cli  # noqa: E402
import csdn_ui as ui  # noqa: E402
import list_page  # noqa: E402
import naming  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

START_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/resource/list?channelType=page"
BUTTON_TEXT = "一键创建分发名单"
MSG_BOX = ".el-message-box"
PH_LIST_FILTER = "分发名单模糊查询"          # 「分发名单」页签的筛选框（回读核对用）
# 每个页签渲染好的标志：它自己的筛选框出现（用来替掉固定死等）
TAB_FILTER_PH = {"博文圈选任务": "请输入圈选任务名称", "分发名单": PH_LIST_FILTER}


def open_entry(page, tab_name="博文圈选任务"):
    """进「圈选用户 → <tab>」列表（默认博文圈选任务）。返回页面把手。

    已登录、且在后台里时只切菜单/页签，不整页重开（每个桶都要来一次，重开太贵）。
    """
    return list_page.open_list(page, menu="圈选用户", tab=tab_name,
                               wait_input=TAB_FILTER_PH.get(tab_name))


# 后台「圈选用户中」时不允许建名单，要等它跑完再试
RETRY_TOKENS = ("圈选用户中", "请稍候")
ERROR_TOKENS = ("失败", "错误", "已存在", "不能", "异常")
ATTEMPTS = 4
WAIT_S = 30
VERIFY_QUERY_MS = 2200      # --verify：点完「查询」至少等这么久再读（和体检 read_page 同一个底）


def read_back_one(s, bucket_name):
    """提交后回读：切到「分发名单」页签查一次，确认名单真的落了库（2026-09-22 加）。

    跟 `run_taskorder.verify_created()` 同一规矩（`automation/README.md`「写入后台必须回读核对」）：
    「点了确定 + 读到提示」不算建成。查不到就记 warn、下次重跑——账本里的 `submitted` 是**永远跳过**。
    ⚠ 用「行里含桶名」而不是全等：分发名单名是 `桶名 · 主题`，桶名只是它前面那截。
    """
    page = s.page
    try:
        ui.goto(page, START_URL)
        lp = open_entry(page, tab_name="分发名单")
        lp.filter({PH_LIST_FILTER: bucket_name})
        lp.query(wait_ms=0, wait_rows=False)      # 下一句已经在等这一行
        hit = lp.row_containing(bucket_name, timeout=8) is not None
        ui.log("  回读核对: %s（分发名单页签）" % ("✓ 已出现该名单" if hit else "✗ 查不到该名单"))
        return hit
    except Exception as e:
        ui.log("  回读核对异常（按未通过处理）: %s" % str(e).splitlines()[0][:120])
        return False


def check_confirm_name(box, bucket_name):
    """保险丝：确认框里的名单名称必须含目标桶名，否则取消并报错（防点错行建错名单）。"""
    txt = box.inner_text()
    flat = " / ".join(x.strip() for x in txt.splitlines() if x.strip())
    if bucket_name not in txt:
        raise RuntimeError("确认框名单名称与目标桶不符，已中止！\n  期望包含: %s\n  弹窗内容: %s"
                           % (bucket_name, flat[:200]))
    ui.log("  保险丝 OK：确认框名单名称含目标桶 %s" % bucket_name)
    return flat


def do_one(s, task_name, bucket_name, aid, shot_dir):
    page = s.page
    ui.log("[%s] %s" % (aid, task_name))
    msgs = []
    for attempt in range(1, ATTEMPTS + 1):
        # 每个桶都重新打开一次列表：状态干净，也不会因为上一步的滚动/刷新找不到行
        lp = open_entry(page)
        # 用列表自带的筛选框把目标记录筛成唯一一行，再点这一行的按钮
        lp.filter({TAB_FILTER_PH["博文圈选任务"]: bucket_name})
        lp.query(wait_ms=0, wait_rows=False)      # 下一句已经在等这一行
        row = lp.row_containing(bucket_name, timeout=8)
        if row is None:
            raise RuntimeError("筛选后列表里找不到这一行：%s" % bucket_name)
        if not row.button(BUTTON_TEXT):
            raise RuntimeError("这一行里找不到「%s」按钮" % BUTTON_TEXT)
        ui.log("  定位方式：筛选框过滤 + 这一行的按钮")
        # 2026-09-14 真机：点按钮弹的是 message-box（不是 el-dialog）
        box = page.locator(MSG_BOX).first
        expect(box).to_be_visible(timeout=10000)
        flat = check_confirm_name(box, bucket_name)   # 保险丝：名单名称必须对得上
        ui.log("  确认框：%s" % flat[:300])

        if s.dry_run:
            cancel = box.locator("button").filter(has_text="取消").first
            expect(cancel).to_be_visible(timeout=5000)
            cancel.click()
            ui.wait_for(page, lambda: not box.is_visible(), timeout=5, what="确认框收起")
            ui.log("  [%s] dry-run：已取消确认框，未创建" % aid)
            return "done"

        ok_btn = box.locator("button.el-button--primary").last
        expect(ok_btn).to_be_visible(timeout=5000)
        ok_btn.click()
        try:
            expect(box).to_be_hidden(timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        msgs = [m.strip() for m in page.locator(".el-message").all_inner_texts() if m.strip()]
        ui.log("  提交(第%d次) | 提示:%s" % (attempt, msgs))

        if any(any(t in m for t in RETRY_TOKENS) for m in msgs):
            if attempt < ATTEMPTS:
                ui.log("  ⏳ 后台还在圈选，等 %d 秒后重试…" % WAIT_S)
                page.wait_for_timeout(WAIT_S * 1000)
                continue
            ui.log("  ⚠ 重试 %d 次仍是「圈选用户中」→ 记 warn（稍后重跑）" % ATTEMPTS)
            break
        if any(any(t in m for t in ERROR_TOKENS) for m in msgs):
            ui.log("  ✗ 后台报错 → 记 warn（下次重跑）")
            break
        break

    # 注意：ui.shot 只在 dry-run 存图，正式跑要留证据得自己截
    try:
        os.makedirs(shot_dir, exist_ok=True)
        path = os.path.join(shot_dir, "dist_%s_submitted.png" % aid)
        page.screenshot(path=path)
        ui.log("  📸 提交后截图：%s" % path)
    except Exception as e:
        ui.log("  截图失败：%s" % e)

    if any(any(t in m for t in RETRY_TOKENS) for m in msgs):
        return "warn"
    if any(any(t in m for t in ERROR_TOKENS) for m in msgs):
        return "warn"
    # 2026-09-22 加：提示干净也不算成功 —— **回读名单管理**确认真的落了库。
    # 原来只看 `.el-message` 文本：提示为空（什么都没读到）也记 submitted，
    # 而 submitted 在账本里是"永远跳过"，误记就等于这桶再也不建。
    if not read_back_one(s, bucket_name):
        ui.log("  ⚠ 提交后回读查不到该名单 → 记 warn（下次重跑；结尾 RESULT: HAS_WARN）")
        return "warn"
    return "submitted"


def verify_lists(s, items, prefix=""):
    """只读核对：打开「分发名单」页签（URL `#/distribute/distUser`），逐个查桶名是否已存在。

    2026-09-23 同一处踩了两次，合起来才是对的：

    ① 这张列表是**全系统**的、一页 30 条——**不按活动前缀筛**，自己那几条排在后面就报「未找到」
       （实测 5 桶报 3/5：B/C/E 恰好在第 1 页）。
    ② **筛完还要等结果落地**：点完查询立刻读，读到的还是筛之前那批行（30 条），连 `wait_rows()`
       都会被那批旧行立刻满足 → 加完筛选依旧 3/5。给足底（2200ms；遮罩转圈就等它转完）再读。

    为什么不按"等这一行出现"来做：这一页有 30 行、每轮读行都慢，实测会把一句核对拖到 3 分钟以上
    （2026-09-23 卡住过一次）；体检 `read_page()` 那套「筛前缀 + 给底 + 读正文」实测稳，这里跟它一致。
    """
    page = s.page
    ui.goto(page, START_URL)
    lp = open_entry(page, tab_name="分发名单")
    if prefix:
        lp.filter({PH_LIST_FILTER: prefix})
    lp.query(wait_ms=VERIFY_QUERY_MS, wait_rows=False)
    # 2026-09-22 踩到：这张表是**异步加载**（切页签后 ~3 秒才出数据，先显示"暂无数据"）——
    # 不等它就会读到空表、把已建的名单全报成"未找到"（实测 5/5 全误报）
    ready = lp.wait_rows(timeout=12)
    ui.log("  分发名单表格就绪:%s（筛选前缀 %r）" % (ready, prefix or "不限"))
    body = lp.text()
    ok = 0
    for a, task_name, bucket_name in items:
        hit = bucket_name in body
        ok += 1 if hit else 0
        ui.log("  %s %s" % ("✓ 已建" if hit else "✗ 未找到", bucket_name))
    ui.log("名单管理核对：%d/%d 已建（筛选前缀 %r）" % (ok, len(items), prefix or "不限"))


def main():
    ap = cli.parser("真正点『确定』创建分发名单（默认只探路）", only=True)
    ap.add_argument("--verify", action="store_true", help="只读核对：打开「名单管理」看各桶名单是否已建")
    args = ap.parse_args()

    ctx = cli.context(args, shots="distribution_shots", progress="distribution_progress.json")
    camp = ctx.cfg["campaign"]
    items = [(a, naming.audience_task_name(camp, a), naming.bucket_name(camp, a))
             for a in ctx.auds]
    try:
        with ctx.session(args) as s:
            if args.verify:
                verify_lists(s, items, prefix=naming.prefix(camp))
                ui.log("RESULT: OK")
                sys.exit(0)
            ui.goto(s.page, START_URL)
            ctx.report = bucket_runner.run_buckets(
                items,
                lambda it: do_one(s, it[1], it[2], it[0]["id"], ctx.shot_dir),
                key_of=lambda it: "%s|%s" % (camp["taskGroupName"], it[0]["id"]),
                describe=lambda it: "[%s] %s" % (it[0]["id"], it[1]),
                progress=ctx.progress,
                on_item_fail=lambda it: ui.dismiss_dialogs(s.page),
                log=ui.log,
                dry_run=not args.submit,
                unit="桶", rest="桶")
    except Exception as e:
        cli.fatal(ctx, e)
    cli.finish(ctx.report)


if __name__ == "__main__":
    main()
