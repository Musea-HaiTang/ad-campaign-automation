# -*- coding: utf-8 -*-
"""CSDN 页面类广告 · 新建资源（数据驱动，条件等待版）

读一个**整活动 YAML**（`activities/{活动名}/配置/{品牌}{负责人}.yaml`），逐条创建资源
（7 桶 × 3 = 21 条）。

可靠性优先：全部用「条件等待」等真实状态（元素可见/下拉关闭/勾上/弹窗隐藏），
只在必要时回退到重载列表页；单条失败不影响下一条，首条/连续 3 条失败即中止。

页面交互（会话/下拉/穿梭框/截图）都在 `csdn_ui.py` 里；排队/断点/止损在 `bucket_runner.py` 里；
本脚本只管「这次要办什么」。

用法：
    .venv\\Scripts\\python.exe -u automation/scripts/run_ads.py --config activities/华为云码道/华为云码道hang.yaml
    默认彩排：只填+校验+截图，不点确定不创建
    加 --submit 真正点「确定」创建资源；加 --headed 显示窗口
    加 --only A（或 --only A,C）只跑指定桶——逐桶推进用（断点账本键含桶 id，先跑过的桶以后自动跳过）
    加 --reset-progress 清空断点账本（日志/ads_progress.json），从头全跑
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bucket_runner  # noqa: E402
import check_campaign  # noqa: E402
import cli  # noqa: E402
import csdn_ui as ui  # noqa: E402
import execution_state  # noqa: E402
import workspace_sync  # noqa: E402
import workspace_repo  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

LIST_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/resource/list?channelType=page"


def pick_business_line(s, dlg, value):
    """业务线 el-select 显示有值但模型可能为空，必须显式重选以绑定 departmentId。"""
    label = dlg.get_by_text("业务线", exact=True).first
    expect(label).to_be_visible(timeout=6000)
    item = label.locator("xpath=ancestor::div[contains(@class,'el-form-item')]").first
    ui.select(s, item.locator(".el-select input").first, value)
    ui.log("  业务线:", value)


def pick_material_path(s, dlg, path, final_placeholder):
    """按配置逐级选择素材路径，并等最后一个字段出现。"""
    for idx, step_name in enumerate(path):
        radio = dlg.locator("label.el-radio-button:visible").filter(has_text=step_name).first
        expect(radio).to_be_visible(timeout=10000)
        radio.click()
        if idx + 1 < len(path):
            nxt = dlg.locator("label.el-radio-button:visible").filter(has_text=path[idx + 1]).first
            expect(nxt).to_be_visible(timeout=8000)
        else:
            # 最后一级选完后，资源文案字段才出现
            expect(dlg.locator("input[placeholder='%s']" % final_placeholder).first).to_be_visible(
                timeout=8000
            )
        ui.log("  素材路径:", step_name)


def fill_text_field(dlg, placeholder, value, kind="input"):
    tag = "textarea" if kind == "textarea" else "input"
    loc = dlg.locator("%s[placeholder='%s']" % (tag, placeholder))
    expect(loc.first).to_be_visible(timeout=8000)
    loc.first.fill(value)


def open_create_dialog(page):
    nb = page.get_by_text("新建资源", exact=True).first
    try:
        expect(nb).to_be_visible(timeout=6000)
    except Exception:
        ui.goto(page, LIST_URL)
        expect(nb).to_be_visible(timeout=15000)
    nb.click()
    dlg = ui.dialog(page, "新建资源")
    expect(dlg).to_be_visible(timeout=12000)
    return dlg


def preflight_taskgroup(s, cfg):
    """跑前校验：打开新建资源弹窗，读「任务组」下拉的可选项，确认 taskGroupName 存在。
    返回 (found, options)。不存在时应立即中止主流程，避免 21 条连锁失败。"""
    camp = cfg["campaign"]
    expected = camp["taskGroupName"]
    biz = cfg["controls"]["defaults"]["businessLine"]
    sub = cfg["audiences"][0]["subBusinessLine"]
    page = s.page
    dlg = open_create_dialog(page)
    # 任务组选项要等业务线/子业务线选上才会加载，先选上再读下拉，避免误报
    pick_business_line(s, dlg, biz)
    try:
        ui.select(s, dlg.locator("input[placeholder='%s']" % ui.PH_SUBLINE).first, sub)
    except Exception:
        pass
    inp = dlg.locator("input[placeholder='%s']" % ui.PH_TASK_GROUP).first
    inp.click()
    page.wait_for_selector(ui.SEL_DROPDOWN, timeout=8000)
    ui.wait_for(page, lambda: ui.dropdown_options(page), timeout=6, what="任务组选项")
    options = ui.dropdown_options(page)
    found = expected in options
    ui.dismiss_dialogs(page)
    return found, options


def create_one(s, cfg, aud, res, idx):
    c = cfg["controls"]
    camp = cfg["campaign"]
    name = res.get("name")
    task_group = camp["taskGroupName"]
    sub = aud["subBusinessLine"]
    link = res.get("link") or camp["activityLink"]
    ui.log("[%d] %s" % (idx + 1, name))
    s.submitted = False      # 重试闸门：点过「确定」之后不许重试（防重复创建）
    dlg = open_create_dialog(s.page)

    # 1) 业务线（显式重选，绑 departmentId）
    pick_business_line(s, dlg, c["defaults"]["businessLine"])
    # 2) 子业务线/用户组
    ui.select(s, dlg.locator("input[placeholder='%s']" % ui.PH_SUBLINE).first, sub)
    # 3) 任务组
    ui.select(s, dlg.locator("input[placeholder='%s']" % ui.PH_TASK_GROUP).first, task_group)
    # 4) 资源名称
    dlg.locator("input[placeholder='%s']" % ui.PH_RESOURCE_NAME).first.fill(name)
    ok1 = ui.read_field(dlg, ui.PH_RESOURCE_NAME) == name
    ui.log("  %s 资源名称 | 期望:%r | 实际:%r" % ("✓" if ok1 else "✗", name,
                                                  ui.read_field(dlg, ui.PH_RESOURCE_NAME)))
    for ph, tag, want in ((ui.PH_SUBLINE, "子业务线/用户组", sub), (ui.PH_TASK_GROUP, "任务组", task_group)):
        actual = ui.read_field(dlg, ph)
        ui.log("  %s %s | 期望:%r | 实际:%r" % ("✓" if actual == want else "⚠", tag, want, actual))

    # 5) 渠道（穿梭框）
    ui.transfer(s, dlg, c["channel"])
    # 6) 素材路径
    pick_material_path(s, dlg, c["materialPath"], c["fields"]["title"]["placeholder"])
    # 7) 文案字段（title/summary 取资源；link 默认继承 campaign.activityLink；username 取 controls）
    ok2 = True
    for key, spec in c["fields"].items():
        if key == "link":
            val = link
        elif key == "username":
            val = c.get("username", "")
        else:
            val = res.get(key, "")
        val = (val or "").rstrip("\n")
        fill_text_field(dlg, spec["placeholder"], val, spec.get("type", "input"))
        actual = ui.read_field(dlg, spec["placeholder"])
        ok2 = (actual == val) and ok2
        ui.log("  %s %s | 期望:%r | 实际:%r" % ("✓" if actual == val else "✗", key, val, actual))

    ui.shot(s, "item_%02d_filled.png" % (idx + 1))
    ui.log("  基本信息校验:%s | 文案字段校验:%s" % (ok1, ok2))
    steps = [("资源名称", "ok" if ok1 else "fail"), ("文案字段", "ok" if ok2 else "fail")]

    if s.dry_run:
        cancel = dlg.locator("button").filter(has_text="取消").last
        cancel.click()
        expect(dlg).to_be_hidden(timeout=8000)
        ui.log("  [%d] 彩排：未提交，已关闭" % (idx + 1))
        return bucket_runner.steps_status(steps)

    # ⛔ 提交前闸门（2026-09-22 加，跟 run_taskorder 同一规矩）：**有一步没通过就不提交**。
    # 原来 ok1/ok2 只写日志，正式路径照样点「确定」——21 条规模下会批量建出字段写错的资源，
    # 而事后的回读只查"名字在不在"，查不出字段缺失。
    if bucket_runner.steps_status(steps) == bucket_runner.WARN:
        bad = "、".join(n for n, r in steps if r != "ok")
        ui.log("  !! 有步骤未通过（%s）→ **不提交**，关闭表单后整项重试" % bad)
        cancel = dlg.locator("button").filter(has_text="取消").last
        if cancel.count():
            cancel.click()
        else:
            ui.dismiss_dialogs(s.page)      # 兜底：别把弹窗留给下一条
        try:
            expect(dlg).to_be_hidden(timeout=8000)
        except Exception:
            pass
        raise bucket_runner.pre_submit_error(steps)

    submit_btn = dlg.locator("button.el-button--primary").filter(has_text="确定").last
    s.submitted = True       # 就这一下之后失败（弹窗没关 / 提示出错）不能再重试
    with s.page.expect_response(
            lambda r: r.request.method == "POST" and "tResourceBaseInfo/add" in r.url,
            timeout=15000) as response_info:
        try:
            submit_btn.click(timeout=1500)
        except Exception:
            ui.close_dropdown(s.page)     # 下拉浮层可能挡住按钮
            submit_btn.click()
    try:
        expect(dlg).to_be_hidden(timeout=15000)
    except Exception:
        errs = dlg.locator(".el-form-item__error").all_inner_texts()
        ui.log("  ✗ 提交失败，表单错误:%s" % errs)
        raise
    msgs = s.page.locator(".el-message").all_inner_texts()
    ui.log("  [%d] 提交成功 | 提示:%s" % (idx + 1, msgs))
    try:
        body = response_info.value.json()
        resource_id = body.get("data")
        if resource_id:
            detail = s.page.context.request.get(
                "https://csdn-distadmin.csdn.net/admin/tResourceBaseInfo/detail",
                params={"id": resource_id},
                headers={"Accept": "application/json"},
            ).json().get("data") or {}
            actual = (detail.get("createBy") or "").strip()
            expected = getattr(s, "login_user", "")
            if expected and actual == expected:
                ui.log("  ✓ 申请人 | %s" % actual)
            else:
                s.creator_mismatch = True
                ui.log("  ✗ 申请人 | 期望:%r | 实际:%r" % (expected, actual))
    except Exception as e:
        s.creator_mismatch = True
        ui.log("  ⚠ 申请人回读未确认：%s" % str(e).splitlines()[0][:120])
    return "submitted"   # 真创建了 → 账本记 submitted，再跑时永远跳过


def verify_created_resources(s, cfg, names):
    """提交后按精确体检同一条路径回读；空列表=全在，缺失=确认缺失，None=未确认。"""
    ui.log("---- 回读核对：与 check_campaign 共用精确资源检索，核对 %d 个资源名 ----"
           % len(names))
    hits = check_campaign.check_resources_for_config(s, cfg, only_names=names)
    miss = [name for name in names if hits.get(name) is False]
    unknown = [name for name in names if hits.get(name) is None]
    for name in names:
        mark = "✓ 已建" if hits.get(name) is True else (
            "? 未确认" if hits.get(name) is None else "✗ 查不到")
        ui.log("  %s %s" % (mark, name))
    ui.log("  回读核对：%d/%d 确认在位"
           % (sum(1 for name in names if hits.get(name) is True), len(names)))
    if miss:
        return miss
    return None if unknown else []


def payload_for(cfg, aud, res):
    """同一资源业务键下的完整创建载荷。"""
    controls = cfg["controls"]
    values = {}
    for key, spec in controls["fields"].items():
        if key == "link":
            values[key] = res.get("link") or cfg["campaign"]["activityLink"]
        elif key == "username":
            values[key] = controls.get("username", "")
        else:
            values[key] = res.get(key, "")
    return {
        "taskGroup": cfg["campaign"]["taskGroupName"],
        "bucket": aud["id"],
        "resourceName": res.get("name"),
        "subBusinessLine": aud["subBusinessLine"],
        "channel": controls["channel"],
        "materialPath": controls["materialPath"],
        "fields": values,
    }


def lookup_resource(s, cfg, name):
    found = check_campaign.check_resources_for_config(
        s, cfg, only_names=[name]).get(name)
    if found is True:
        return execution_state.found()
    if found is False:
        return execution_state.absent()
    return execution_state.unknown("资源精确查询未确认")


def main():
    ap = cli.parser("真正点『确定』创建资源（默认彩排）", only=True)
    ap.add_argument("--v2-db", default=workspace_repo.V2_DB, help="数据库 v2 路径")
    args = ap.parse_args()

    ctx = cli.context(args, shots="shots", progress="ads_progress.json")
    task_group = ctx.cfg["campaign"]["taskGroupName"]

    # 待跑清单：桶 × 资源摊平；编号按全集位置，跳过也不会让截图/日志编号错位
    items = []
    for a in ctx.auds:
        for res in a["resources"]:
            items.append((len(items) + 1, a, res))

    try:
        with ctx.session(args) as s:
            page = s.page
            ui.log("类型:%s | 条数:%d" % (ctx.cfg["label"], len(items)))
            if ctx.only:
                ui.log("--only %s → 只跑 %d 个桶（%s）"
                       % (",".join(ctx.only), len(ctx.auds),
                          ", ".join(str(a["id"]) for a in ctx.auds)))
            def prepare():
                ui.goto(s.page, LIST_URL)
                s.login_user = ui.require_login_identity(s.page)
                expect(s.page.get_by_text("新建资源", exact=True).first).to_be_visible(
                    timeout=15000)
                return preflight_taskgroup(s, ctx.cfg)

            # ---- preflight：任务组名不在下拉里就中止（避免 21 条连锁失败）----
            tg = ctx.cfg["campaign"]["taskGroupName"]
            found, options = ui.retry_browser_action(
                s, prepare, what="资源列表准备")
            blocked = not found
            if blocked:
                ui.log("!! PREFLIGHT 失败：任务组 '%s' 不在下拉可选项中。" % tg)
                ui.log("   实际可选项(%d 个)前 20：%s" % (len(options), options[:20]))
                ui.log("   请修正 campaign.taskGroupName 后重跑。")
            else:
                ui.log("preflight OK：任务组 '%s' 可选中。" % tg)

            if blocked:
                ctx.report.fatal = True
            else:
                ctx.report = bucket_runner.run_buckets(
                    items,
                    lambda it: create_one(s, ctx.cfg, it[1], it[2], it[0] - 1),
                    key_of=lambda it: "%s|%s|%s" % (task_group, it[1]["id"], it[2]["name"]),
                    describe=lambda it: "[%d] %s" % (it[0], it[2]["name"]),
                    progress=ctx.progress,
                    reconcile=lambda it: lookup_resource(
                        s, ctx.cfg, it[2]["name"]),
                    payload_of=lambda it: payload_for(ctx.cfg, it[1], it[2]),
                    on_item_fail=lambda it: ui.dismiss_dialogs(s.page),
                    on_retry=lambda it, e: ui.retry_reset(s, e, LIST_URL),
                    retry=1,
                    should_retry=lambda it, e: not getattr(s, "submitted", False),
                    log=ui.log,
                    dry_run=not args.submit,
                    unit="条", rest="条目")
                # 整批跑完一次性回读核对（只核对**这趟真提交了**的那些；查不到就记 warn → 退出码 1）
                if args.submit:
                    submitted = [it[2]["name"] for it in items
                                 if ctx.progress.get("%s|%s|%s" % (task_group, it[1]["id"],
                                                                   it[2]["name"]))
                                 == bucket_runner.SUBMITTED]
                    if submitted:
                        miss = verify_created_resources(s, ctx.cfg, submitted)
                        if miss is None:
                            ctx.report.warned += 1
                            for it in items:
                                key = "%s|%s|%s" % (task_group, it[1]["id"], it[2]["name"])
                                if ctx.progress.get(key) == bucket_runner.SUBMITTED:
                                    ctx.progress.set(key, bucket_runner.NEEDS_RECONCILE)
                        elif miss:
                            ctx.report.warned += len(miss)
                            for it in items:
                                key = "%s|%s|%s" % (task_group, it[1]["id"], it[2]["name"])
                                if (it[2]["name"] in miss and
                                        ctx.progress.get(key) == bucket_runner.SUBMITTED):
                                    ctx.progress.set(key, bucket_runner.NEEDS_RECONCILE)
                    if getattr(s, "creator_mismatch", False):
                        ctx.report.warned += 1
                    if args.v2_db:
                        submitted_ids = set()
                        for it in items:
                            key = "%s|%s|%s" % (task_group, it[1]["id"], it[2]["name"])
                            if ctx.progress.get(key) == bucket_runner.SUBMITTED:
                                submitted_ids.add(it[1]["id"])
                        auds = []
                        seen = set()
                        for _, aud, _ in items:
                            if aud["id"] in submitted_ids and aud["id"] not in seen:
                                seen.add(aud["id"])
                                auds.append(aud)
                        if auds:
                            workspace_sync.sync_config_batch(
                                args.v2_db, ctx.cfg, auds,
                                ctx.cfg["taskOrder"]["deliveryDate"]["start"],
                                change_reason=os.path.basename(args.config),
                                status="planned",
                            )
    except Exception as e:
        cli.fatal(ctx, e)
    cli.finish(ctx.report)


if __name__ == "__main__":
    main()
