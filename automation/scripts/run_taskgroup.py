# -*- coding: utf-8 -*-
"""CSDN 新建任务组 · 数据驱动自动化（保底步骤）

读一份整活动 YAML，打开后台「创建任务组」弹窗，填 任务组名称 / 业务线(事业部) /
子业务线/用户组；彩排只填+校验+截图，不点提交不创建。

定位：执行层第 1 步。这是保底逻辑——CRM 立项且分配团队后任务组会自动生成，平时跳过；
只有立项没自动建出来时才需要执行本步骤（开工前先问：是否新建任务组 + 叫什么）。

页面交互（会话/下拉/截图）都在 `csdn_ui.py` 里；本脚本只管「这次要办什么」。

用法：
    .venv\\Scripts\\python.exe -u automation/scripts/run_taskgroup.py --config activities/华为云码道/华为云码道hang.yaml
    默认彩排：只填+校验+截图，不点提交不创建
    加 --submit 才真正点「提交」建任务组；加 --headed 显示窗口

前置门控：必给项缺失（campaign.taskGroupName / audiences[].subBusinessLine）→ 直接中止，
不启动执行层。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bucket_runner  # noqa: E402
import cli  # noqa: E402
import csdn_ui as ui  # noqa: E402
import list_page  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

LIST_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/resource/list?channelType=page"
TEAM_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/taskteam/team"   # 任务组列表（回读核对用）
PH_TEAM_FILTER = "请输入任务组名称"


def open_dialog(page):
    """进「创建任务组」弹窗。"""
    ui.goto(page, LIST_URL)
    menu = page.get_by_text("1.创建任务组", exact=True).first
    expect(menu).to_be_visible(timeout=15000)
    menu.click()
    # 路由切到任务组列表页，等待「创建任务组」按钮出现
    btn = page.locator("button").filter(has_text="创建任务组").first
    expect(btn).to_be_visible(timeout=15000)
    btn.click()
    dlg = ui.dialog(page, "添加")
    expect(dlg).to_be_visible(timeout=12000)
    return dlg


def verify_created(page, name):
    """提交后回读核对：回任务组列表按名字查一次（只读，防"点了提交其实没建成"）。

    2026-09-22 加（`automation/README.md`「写入后台必须回读核对」）：原来提交后只读 `.el-message` 提示。
    任务组是后面三步的锚点——资源/客群/工单都按名字**精确字符串**匹配，名字对不上整条链都失效。
    页面怎么翻、怎么筛在共用层 `list_page`。
    """
    try:
        ui.goto(page, TEAM_URL)
        lp = list_page.open_list(page, wait_input=PH_TEAM_FILTER)
        lp.filter({PH_TEAM_FILTER: name})
        lp.query(wait_ms=0, wait_rows=False)      # 下一句已经在等这一行
        hit = lp.row_containing(name, timeout=8) is not None
        ui.log("  回读核对: %s" % ("✓ 列表里已出现该任务组" if hit else "✗ 列表里查不到该任务组"))
        return hit
    except Exception as e:
        ui.log("  回读核对异常（按未通过处理）: %s" % str(e).splitlines()[0][:120])
        return False


def run(s, cfg):
    camp = cfg["campaign"]
    ctrl = cfg["controls"]["defaults"]
    auds = cfg["audiences"]

    name = camp["taskGroupName"]
    biz = ctrl["businessLine"]
    sub = auds[0]["subBusinessLine"]

    dlg = open_dialog(s.page)

    # 1) 任务组名称
    dlg.locator("input[placeholder='%s']" % ui.PH_TASKGROUP_NAME).first.fill(name)
    ok_name = ui.read_field(dlg, ui.PH_TASKGROUP_NAME) == name
    ui.log("  %s 任务组名称 | %r" % ("✓" if ok_name else "✗", name))
    # 2) 业务线（事业部）：显式重选，绑定后台值，避免只显示不绑定
    ui.select(s, dlg.locator("input[placeholder='%s']" % ui.PH_DEPT).first, biz)
    ok_biz = ui.read_field(dlg, ui.PH_DEPT) == biz
    ui.log("  %s 业务线 | %r" % ("✓" if ok_biz else "⚠", biz))
    # 3) 子业务线/用户组
    ui.select(s, dlg.locator("input[placeholder='%s']" % ui.PH_SUBLINE).first, sub)
    ok_sub = ui.read_field(dlg, ui.PH_SUBLINE) == sub
    ui.log("  %s 子业务线/用户组 | %r" % ("✓" if ok_sub else "⚠", sub))
    # 签呈号选填，不填
    ui.log("  签呈号: 不填(选填)")

    ui.shot(s, "taskgroup_filled.png")
    ui.log("  校验: 名称%s | 业务线%s | 子业务线%s" % (ok_name, ok_biz, ok_sub))
    steps = [("任务组名称", "ok" if ok_name else "fail"),
             ("业务线", "ok" if ok_biz else "fail"),
             ("子业务线", "ok" if ok_sub else "fail")]

    if s.dry_run:
        cancel = dlg.locator("button").filter(has_text="取消").last
        cancel.click()
        expect(dlg).to_be_hidden(timeout=8000)
        ui.log("  彩排：未提交，已关闭（未创建任务组）")
        return bucket_runner.steps_status(steps)

    # ⛔ 提交前闸门（2026-09-22 加，跟 run_taskorder 同一规矩）：**有一步没通过就不提交**。
    # 原来三个校验值只写日志，正式路径照样点「提交」——名字/子业务线错了，后面三步全部选不中。
    if bucket_runner.steps_status(steps) == bucket_runner.WARN:
        bad = "、".join(n for n, r in steps if r != "ok")
        ui.log("  !! 有步骤未通过（%s）→ **不提交**，记 warn（下次重跑）" % bad)
        cancel = dlg.locator("button").filter(has_text="取消").last
        if cancel.count():
            cancel.click()
        else:
            ui.dismiss_dialogs(s.page)      # 兜底：关不掉就清场，别留残留弹窗
        try:
            expect(dlg).to_be_hidden(timeout=8000)
        except Exception:
            pass
        return bucket_runner.WARN

    btn = dlg.locator("button.el-button--primary").filter(has_text="提交").last
    btn.click()
    try:
        expect(dlg).to_be_hidden(timeout=15000)
    except Exception:
        errs = dlg.locator(".el-form-item__error").all_inner_texts()
        ui.log("  ✗ 提交失败，表单错误:%s" % errs)
        return False
    msgs = s.page.locator(".el-message").all_inner_texts()
    ui.log("  已提交任务组 | 提示:%s" % msgs)
    if not verify_created(s.page, name):
        ui.log("  ⚠ 提交后回读查不到该任务组 → 记 warn（下次重跑；结尾 RESULT: HAS_WARN）")
        return bucket_runner.WARN
    return "submitted"   # 真创建了 → 账本记 submitted，再跑时永远跳过


def main():
    ap = cli.parser("真正点『提交』建任务组（默认彩排）")
    args = ap.parse_args()

    ctx = cli.context(args, shots="taskgroup_shots", progress="taskgroup_progress.json")
    camp = ctx.cfg["campaign"]

    ui.log("任务组名:%s | 业务线:%s | 子业务线:%s | 模式:%s"
           % (camp["taskGroupName"],
              ctx.cfg["controls"]["defaults"]["businessLine"],
              ctx.auds[0]["subBusinessLine"],
              "SUBMIT" if args.submit else "DRY-RUN"))

    try:
        with ctx.session(args) as s:
            ctx.report = bucket_runner.run_buckets(
                [ctx.cfg],
                lambda c: run(s, c),
                key_of=lambda c: "taskGroup|%s" % camp["taskGroupName"],
                describe=lambda c: camp["taskGroupName"],
                progress=ctx.progress,
                on_item_fail=lambda c: ui.dismiss_dialogs(s.page),
                log=ui.log,
                dry_run=not args.submit,
                unit="个", rest="项")
    except Exception as e:
        cli.fatal(ctx, e)
    cli.finish(ctx.report)


if __name__ == "__main__":
    main()
