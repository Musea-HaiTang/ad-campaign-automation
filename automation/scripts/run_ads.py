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
import cli  # noqa: E402
import csdn_ui as ui  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

LIST_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/resource/list?channelType=page"


def pick_business_line(s, dlg, value):
    """业务线 el-select 显示有值但模型可能为空，必须显式重选以绑定 departmentId。"""
    label = dlg.get_by_text("业务线", exact=True).first
    expect(label).to_be_visible(timeout=6000)
    item = label.locator("xpath=ancestor::div[contains(@class,'el-form-item')]").first
    ui.select(s, item.locator(".el-select input").first, value)
    ui.log("  业务线:", value)


def pick_material_path(s, dlg, path):
    """素材路径三级：静态广告 → 信息流 → 文本。"""
    for idx, step_name in enumerate(path):
        radio = dlg.locator("label.el-radio-button:visible").filter(has_text=step_name).first
        expect(radio).to_be_visible(timeout=10000)
        radio.click()
        if idx + 1 < len(path):
            nxt = dlg.locator("label.el-radio-button:visible").filter(has_text=path[idx + 1]).first
            expect(nxt).to_be_visible(timeout=8000)
        else:
            # 最后一级（文本）选完后，广告标题等三栏字段才出现
            expect(dlg.locator("input[placeholder='%s']" % ui.PH_AD_TITLE).first).to_be_visible(
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


def pick_highlight(s, dlg, word):
    """「是否飘红」：填了飘红词就选「是」并填词；没填就保持默认「否」。

    2026-09-24 加（结构来自只读探针 `automation/_tmp/_probe_highlight.py`）：
    「是否飘红」是一个 el-form-item，里面 2 个 el-radio（否 / 是）+ 一个输入框 `请输入飘红词`。
    机制（用户 2026-09-24 实测，**不当结论用、先当口径**）：只能填一个表达（逗号分隔无效），
    按正则最长匹配，**标题 + 摘要里所有出现处都会标红**，且必须字面出现才标得出来。
    YAML 字段：`resources[].highlight`（飘红词；留空 = 不飘红）。
    """
    word = (word or "").strip()
    label = dlg.get_by_text("是否飘红", exact=True).first
    expect(label).to_be_visible(timeout=6000)
    item = label.locator("xpath=ancestor::div[contains(@class,'el-form-item')]").first
    want = "是" if word else "否"
    item.locator("label.el-radio").filter(has_text=want).first.click()
    if not word:
        ui.log("  飘红: 否")
        return True
    box = item.locator("input[placeholder='%s']" % ui.PH_HIGHLIGHT_WORD).first
    expect(box).to_be_visible(timeout=6000)
    box.fill(word)
    actual = box.input_value()
    ui.log("  %s 飘红词 | 期望:%r | 实际:%r" % ("✓" if actual == word else "✗", word, actual))
    return actual == word


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
    page.wait_for_timeout(200)
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
    pick_material_path(s, dlg, c["materialPath"])
    # 7) 三栏（title/summary 取资源；link 取 link，默认继承 campaign.activityLink）
    ok2 = True
    for key, spec in c["fields"].items():
        val = link if key == "link" else res.get(key, "")
        val = (val or "").rstrip("\n")
        fill_text_field(dlg, spec["placeholder"], val, spec.get("type", "input"))
        actual = ui.read_field(dlg, spec["placeholder"])
        ok2 = (actual == val) and ok2
        ui.log("  %s %s | 期望:%r | 实际:%r" % ("✓" if actual == val else "✗", key, val, actual))

    # 8) 飘红（2026-09-24 加）：res.highlight = 飘红词，空 = 不飘红（保持默认「否」）
    ok3 = pick_highlight(s, dlg, res.get("highlight"))

    ui.shot(s, "item_%02d_filled.png" % (idx + 1))
    ui.log("  基本信息校验:%s | 三栏校验:%s | 飘红校验:%s" % (ok1, ok2, ok3))
    steps = [("资源名称", "ok" if ok1 else "fail"), ("三栏", "ok" if ok2 else "fail"),
             ("飘红", "ok" if ok3 else "fail")]

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
        ui.log("  !! 有步骤未通过（%s）→ **不提交**，记 warn（下次重跑）" % bad)
        cancel = dlg.locator("button").filter(has_text="取消").last
        if cancel.count():
            cancel.click()
        else:
            ui.dismiss_dialogs(s.page)      # 兜底：别把弹窗留给下一条
        try:
            expect(dlg).to_be_hidden(timeout=8000)
        except Exception:
            pass
        return bucket_runner.WARN

    submit_btn = dlg.locator("button.el-button--primary").filter(has_text="确定").last
    submit_btn.click()
    try:
        expect(dlg).to_be_hidden(timeout=15000)
    except Exception:
        errs = dlg.locator(".el-form-item__error").all_inner_texts()
        ui.log("  ✗ 提交失败，表单错误:%s" % errs)
        raise
    msgs = s.page.locator(".el-message").all_inner_texts()
    ui.log("  [%d] 提交成功 | 提示:%s" % (idx + 1, msgs))
    return "submitted"   # 真创建了 → 账本记 submitted，再跑时永远跳过


def verify_created_resources(s, cfg, names):
    """整批跑完**一次性回读**：资源列表按「任务组」筛一遍，核对这批资源名在不在。

    2026-09-22 加（`automation/README.md`「写入后台必须回读核对」）：原来提交后只等弹窗关闭 + 读提示，
    后台其实没落库也会记 `submitted`。逐条核对要多付 21 次列表往返，所以**整批核一次**
    （跟 `check_campaign.py` 查资源同一个方式：用「任务组」下拉一次列全）。
    返回没找到的资源名；空列表 = 全部在位。
    """
    page = s.page
    team = cfg["campaign"]["taskGroupName"]
    ui.log("---- 回读核对：资源列表按任务组 %r 筛一遍，核对 %d 个资源名 ----" % (team, len(names)))
    ui.goto(page, LIST_URL)
    ui.wait_for(page, lambda: ui.visible_input(page, ui.PH_TASK_GROUP) is not None,
                timeout=12, what="资源列表筛选框")
    try:
        ui.select(s, ui.visible_input(page, ui.PH_TASK_GROUP), team)
    except Exception as e:
        ui.log("  ⚠ 任务组筛选不可用（%s）→ 回读跳过（不当作缺失；需要自己跑 check_campaign 核一遍）"
               % str(e).splitlines()[0][:100])
        return []
    page.locator("button:visible").filter(has_text="查询").first.click()
    ui.wait_for(page, lambda: all(n in page.locator("body").inner_text() for n in names),
                timeout=10, what="资源列表查询结果")
    text = page.locator("body").inner_text()
    miss = [n for n in names if n not in text]
    for n in names:
        ui.log("  %s %s" % ("✗ 查不到" if n in miss else "✓ 已建", n))
    ui.log("  回读核对：%d/%d 在位" % (len(names) - len(miss), len(names)))
    return miss


def main():
    ap = cli.parser("真正点『确定』创建资源（默认彩排）", only=True)
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
            ui.goto(page, LIST_URL)
            expect(page.get_by_text("新建资源", exact=True).first).to_be_visible(timeout=15000)

            # ---- preflight：任务组名不在下拉里就中止（避免 21 条连锁失败）----
            tg = ctx.cfg["campaign"]["taskGroupName"]
            found, options = preflight_taskgroup(s, ctx.cfg)
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
                    on_item_fail=lambda it: ui.dismiss_dialogs(page),
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
                        if miss:
                            ctx.report.warned += len(miss)
    except Exception as e:
        cli.fatal(ctx, e)
    cli.finish(ctx.report)


if __name__ == "__main__":
    main()
