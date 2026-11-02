# -*- coding: utf-8 -*-
"""活动体检（**只读**）：给一份整活动 YAML，核对后台这 5 类对象是否都在、名字是否一字不差。

为什么需要它：本轮真实创建里连续踩到"脚本报成功、后台其实没有"（圈选 A/E 假通过、
工单提交按钮名写错、投放日期跨月点错、分发名单被"圈选用户中"挡住）——本质都是
"我以为建成了"。这个命令让你随时一条命令确认后台现状（交付前、复盘中、怀疑时都能用）。

核对对象（名字一律问 naming.py 或配置里的 `distributionList`，不手写）：
  任务组 1 ｜ 资源 N×3 ｜ 客群 N ｜ 分发名单 N ｜ 任务工单 N
⚠ 客群名 / 分发名单名优先取 `audiences[].distributionList`（重投复用旧名单时名单名不带 nameSuffix，
  按命名规则算会误报缺失）；工单名与资源名永远按命名规则（naming.py）算。
⚠ **客群已删、分发名单还在 → 不算缺失**（用户 2026-09-23 口径："只要分发名单还在就行"）：
  重投/换词后常把圈选任务删掉只留名单，而工单认的是**分发名单**、投放不受影响。这类只在报告里
  提一句（`ⓘ 客群已删、分发名单在，不算缺失`），不计缺失、不影响退出码——退出码是给门禁用的，
  一直红着就等于门禁失效。客群与名单**都不在**才算真缺失。实现见 `split_deleted_audiences`。

**客群达标体检（2026-09-21 加）**：查客群时顺带读「博文圈选任务」列表那四列
（实际圈选博客ID数 / 日均点击(预估) / 日均曝光(预估) / 日均pv(预估)），按当期口径判达标。
口径默认：日均曝光(预估) ≥ 10000（`--min-exposure` 可覆盖）。
⚠ 这几项**建完、等后台算完才刷出来**（创建弹窗里没有）；还没刷出来会显示「待后台」。
达标只报数、**不影响退出码**（退出码仍只表示"对象在不在"）。

用法：
    .venv\\Scripts\\python.exe -u automation/scripts/check_campaign.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml
    ... --only ads,order        # 只看资源与工单（taskgroup/ads/audience/list/order）
    ... --headed                # 想看浏览器窗口
    ... --only audience

退出码：全部找到 0；有缺失 1（便于串进别的流程做门禁）。
⚠ 只做查询：填筛选框 + 点「查询」，绝不点新建/创建/确定。
"""
import argparse
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audience_metrics as am  # noqa: E402
import campaign  # noqa: E402
import csdn_ui as ui  # noqa: E402
import list_page  # noqa: E402
import naming  # noqa: E402

BASE = "https://mp-admin.csdn.net/silkroad-dist/#"
TEAM_URL = BASE + "/distribute/taskteam/team"
RESOURCE_URL = BASE + "/distribute/resource/list?channelType=page"
DISTUSER_URL = BASE + "/distribute/distUser"
ORDER_URL = BASE + "/distribute/distApplyOrder/list"

KINDS = ("taskgroup", "ads", "audience", "list", "order")

# 达标读数/判定/日期窗都在共用层 `audience_metrics.py`（run_audience --verify 也用同一套）
DEF_MIN_EXPOSURE = am.DEF_MIN_EXPOSURE


def read_page(page, url, placeholder, value, *, menu=None, tab=None, widen_dates=False):
    """打开某列表页 → 填筛选框 → 查询 → 返回这一页的把手（`list_page.ListPage`）。

    页面怎么翻、怎么等、"哪份输入框是真的"都在共用层 `list_page` 里；这里只说查什么。
    """
    ui.goto(page, url)
    lp = list_page.open_list(page, menu=menu, tab=tab, wait_input=placeholder)
    if widen_dates:
        # 客群列表**默认只筛最近 4 天**（真机 2026-09-21），老客群会被挡在列表外 → 先放宽日期窗
        am.apply_filters(lp, prefix=value, log=ui.log)
    else:
        lp.filter({placeholder: value})
    lp.query(wait_ms=2200)
    return lp


def expected_user_object_name(camp, aud):
    """本桶要核对的「客群名 / 分发名单名」。

    优先用 `audiences[].distributionList`：名单名与圈选任务名（客群名）本来就要求一致
    （`docs/run_taskorder.md`），而重投复用旧名单时它不带 `nameSuffix` —— 按命名规则算出来的
    `…-2` 在后台根本不存在，会误报「缺失」（2026-09-18 B/C 桶重投踩到）。
    没写 `distributionList` 才回落到 `naming.order_task_name()`（`{桶名} · {topic}` + nameSuffix）。
    """
    dl = (aud.get("distributionList") or "").strip()
    return dl or naming.order_task_name(camp, aud)


def split_deleted_audiences(missing_names, list_text):
    """客群缺失的名字里，哪些的**分发名单还在** → 降级成提示（用户 2026-09-23 口径）。

    口径原话（`activities/火山引擎MediaKit/README.md`，2026-09-18）：
    "这个没关系呀，只要分发名单还在就行"。

    重投 / 换词之后经常把圈选任务删掉、只留分发名单——工单认的是**分发名单**，投放不受影响。
    所以「客群没了」不该再算体检缺失：它会一直红着，还把退出码拉成 1（退出码是给门禁用的）。
    返回 (提示清单, 仍算缺失的名字)。
    """
    notes, real = [], []
    for name in missing_names:
        if name in list_text:
            notes.append("客群已不在后台，但分发名单还在：%s（投放不受影响；下次改词重圈时按新任务走）"
                         % name)
        else:
            real.append(name)
    return notes, real


def _resource_page_marker(page):
    pager = page.locator(".el-pagination:visible").last
    active = pager.locator(".el-pager li.is-active").first
    if active.count():
        return active.inner_text().strip()
    return ""


def _click_next_resource_page(page, lp, timeout=8):
    """翻到下一页；返回 (是否还有下一页, 翻页是否成功)。"""
    pager = page.locator(".el-pagination:visible").last
    if not pager.count():
        return False, True
    nxt = pager.locator("button.btn-next").first
    if not nxt.count() or not nxt.is_visible():
        return False, True
    classes = nxt.get_attribute("class") or ""
    if nxt.is_disabled() or "is-disabled" in classes:
        return False, True

    before_page = _resource_page_marker(page)
    before_text = lp.table_text()
    nxt.click()
    changed = ui.wait_for(
        page,
        lambda: _resource_page_marker(page) != before_page
        or lp.table_text() != before_text,
        timeout=timeout,
        what="资源列表下一页",
    )
    return True, changed


def collect_resource_rows(page, lp, max_pages=50):
    """收集当前筛选结果的全部页；返回 (去重后的行, 是否完整读完)。"""
    rows = {}
    for _ in range(max_pages):
        for row in lp.rows():
            key = row.id or tuple(row.cells)
            rows.setdefault(key, row)
        has_next, ok = _click_next_resource_page(page, lp)
        if not ok:
            return list(rows.values()), False
        if not has_next:
            return list(rows.values()), True
    return list(rows.values()), False


def search_resources_by_prefix(page, lp, prefix, timeout=12):
    """按资源名前缀搜索并读全部分页；返回 (资源名集合, 是否确认完成)。"""
    before = lp.table_text()
    lp.filter({"标题模糊查询": prefix})
    lp.query(wait_ms=0, wait_rows=False)
    changed = ui.wait_for(
        page,
        lambda: lp.table_text() != before,
        timeout=timeout,
        what=f"资源前缀 {prefix} 查询结果刷新",
    )
    rows, complete = collect_resource_rows(page, lp)
    names = {
        row.cells[1].strip()
        for row in rows
        if len(row.cells) > 1 and row.cells[1].strip()
    }
    has_prefix = any(name.startswith(prefix) for name in names)
    return names, complete and (changed or has_prefix)


def resource_name_matches(expected, actual):
    """执行层按完整业务键核对；版本差异必须已经写进 expected。"""
    return expected == actual


def classify_resource_names(expected, actual, verified):
    """资源检查三态：True=确认在位，False=确认缺失，None=未确认。"""
    if verified:
        return {
            name: any(resource_name_matches(name, got) for got in actual)
            for name in expected
        }
    return {
        name: True if any(resource_name_matches(name, got) for got in actual) else None
        for name in expected
    }


def check_resources_for_config(s, cfg, only_names=None):
    """按“日期窗 + 桶名前缀 + 全分页”核对资源，返回三态结果。

    `run_ads.py` 提交后的回读和 `check_campaign.py --only ads` 共用这一条路径，
    不再依赖列表页那个会异步返回空选项的“任务组”下拉。
    """
    camp = cfg["campaign"]
    auds = cfg["audiences"]
    selected = set(only_names or ())
    page = s.page
    ui.log("[资源] 按桶名前缀逐组搜索并读取全部分页")
    ui.goto(page, RESOURCE_URL)
    lp = list_page.open_list(page, wait_input="请选择任务组")
    date_missed = lp.filter(
        {
            am.PH_DATE_FROM: am.DATE_FROM,
            am.PH_DATE_TO: date.today().isoformat(),
        },
        enter=(am.PH_DATE_FROM, am.PH_DATE_TO),
    )
    date_window_ok = not date_missed
    if date_window_ok:
        ui.log("  [日期窗] %s ~ %s ✓" % (am.DATE_FROM, date.today().isoformat()))
    else:
        ui.log("  ⚠ 资源日期窗没填上：%s；未找到的资源只能报未确认"
               % "、".join(date_missed))

    expected = [r["name"] for aud in auds for r in aud["resources"]]
    if selected:
        expected = [name for name in expected if name in selected]
    if not expected:
        return {}

    common_prefix = naming.prefix(camp)
    if common_prefix:
        try:
            actual, verified = search_resources_by_prefix(page, lp, common_prefix)
            verified = verified and date_window_ok
            hits = classify_resource_names(expected, actual, verified)
        except Exception as e:
            ui.log("  ⚠ 资源公共前缀查询失败（%s）：%s"
                   % (common_prefix, str(e).splitlines()[0][:100]))
            hits = classify_resource_names(expected, set(), False)
        return hits

    hits = {}
    for aud in auds:
        bucket_prefix = naming.bucket_name(camp, aud)
        names = [r["name"] for r in aud["resources"]]
        if selected:
            names = [name for name in names if name in selected]
        if not names:
            continue
        try:
            actual, verified = search_resources_by_prefix(page, lp, bucket_prefix)
            verified = verified and date_window_ok
        except Exception as e:
            ui.log("  ⚠ 资源前缀查询失败（%s）：%s"
                   % (bucket_prefix, str(e).splitlines()[0][:100]))
            actual, verified = set(), False
        hits.update(classify_resource_names(names, actual, verified))
    return hits


def check_all(cfg, kinds, headed=False, min_exposure=DEF_MIN_EXPOSURE):
    camp = cfg["campaign"]
    prefix = naming.require_prefix(camp)
    team = camp["taskGroupName"]
    auds = cfg["audiences"]
    # 客群名与分发名单名 1:1 同名：都按「distributionList 优先」解析
    want_user_obj = [expected_user_object_name(camp, a) for a in auds]
    # 工单名永远按命名规则（带 nameSuffix）——重投建的就是新工单
    want_order = [naming.order_task_name(camp, a) for a in auds]

    results = []
    audit = []
    aud_missing = []      # 客群列表里没找到的名字（可能只是"按计划删了"）
    list_text = None      # 「分发名单」页签正文（查过就留着，用它核客群是不是只删了那一半）
    with ui.session(headed=headed, dry_run=True, shot_dir="") as s:
        page = s.page
        if "taskgroup" in kinds:
            ui.log("[任务组] 查 %r" % team)
            lp = read_page(page, TEAM_URL, "请输入任务组名称", team)
            text = lp.text()
            results.append(("任务组", team, team in text))
        if "ads" in kinds:
            for name, found in check_resources_for_config(s, cfg).items():
                results.append(("资源", name, found))
        if "audience" in kinds:
            ui.log("[客群] 查 %r" % prefix)
            lp = read_page(page, DISTUSER_URL, "请输入圈选任务名称", prefix,
                           menu="圈选用户", tab="博文圈选任务", widen_dates=True)
            text = lp.text()
            for n in want_user_obj:
                results.append(("客群", n, n in text))
            aud_missing = [n for n in want_user_obj if n not in text]
            audit = am.report(want_user_obj, am.read_metrics(lp),
                              target=min_exposure, floor=min_exposure, log=ui.log)
        if "list" in kinds:
            ui.log("[分发名单] 查 %r" % prefix)
            lp = read_page(page, DISTUSER_URL, "分发名单模糊查询", prefix,
                           menu="圈选用户", tab="分发名单")
            text = lp.text()
            list_text = text
            for n in want_user_obj:
                results.append(("分发名单", n, n in text))
        if "order" in kinds:
            ui.log("[工单] 查 %r" % prefix)
            lp = read_page(page, ORDER_URL, "请输入任务名称模糊查询", prefix)
            text = lp.text()
            for n in want_order:
                results.append(("工单", n, n in text))

        # 客群的缺失再核一次：**分发名单还在就不算缺失**（用户 2026-09-23 口径）
        if aud_missing:
            if list_text is None:          # 这次没查分发名单（--only audience）→ 补查一次
                list_text = read_page(page, DISTUSER_URL, "分发名单模糊查询", prefix,
                                      menu="圈选用户", tab="分发名单").text()
            notes, real_missing = split_deleted_audiences(aud_missing, list_text)
            deleted = [n for n in aud_missing if n not in real_missing]
        else:
            notes, deleted = [], []
    return results, audit, notes, deleted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="整活动 YAML")
    ap.add_argument("--only", default="", help="只查这些：taskgroup,ads,audience,list,order")
    ap.add_argument("--headed", action="store_true", help="显示浏览器")
    ap.add_argument("--min-exposure", type=int, default=DEF_MIN_EXPOSURE,
                    help="客群达标线：日均曝光(预估) ≥（默认 %s）" % DEF_MIN_EXPOSURE)
    args = ap.parse_args()

    only = [x.strip().lower() for x in args.only.split(",") if x.strip()]
    unknown = [x for x in only if x not in KINDS]
    if unknown:
        raise SystemExit("--only 里有未知项：%s（可选：%s）" % (", ".join(unknown), ", ".join(KINDS)))
    kinds = only or list(KINDS)

    cfg = campaign.load_or_exit(args.config)
    ui.log("体检活动：%s | 任务组：%s | 桶数：%d | 检查项：%s"
           % (cfg["label"], cfg["campaign"]["taskGroupName"], len(cfg["audiences"]), ",".join(kinds)))
    try:
        results, audit, notes, aud_deleted = check_all(cfg, kinds, headed=args.headed,
                                                       min_exposure=args.min_exposure)
    except Exception as e:
        ui.log("  ✗ 体检中断：%s" % e)
        ui.log("RESULT: 体检失败")
        sys.exit(1)

    # 客群已删但分发名单还在的那几条：只在报告里提一句，不算缺失、不影响退出码
    downgraded = [r for r in results if r[2] is False and r[1] in aud_deleted]
    missing = [r for r in results if r[2] is False and r[1] not in aud_deleted]
    unverified = [r for r in results if r[2] is None]
    ui.log("---- 体检结果 ----")
    for kind, name, ok in results:
        if ok is False and name in aud_deleted:
            ui.log("  ⓘ [%s] %s（客群已删、分发名单在，不算缺失）" % (kind, name))
            continue
        mark = "✓" if ok is True else ("? 未确认" if ok is None else "✗ 缺失")
        ui.log("  %s [%s] %s" % (mark, kind, name))
    found = sum(1 for _, _, ok in results if ok is True)
    ui.log("合计 %d 项，找到 %d 项，缺失 %d 项，未确认 %d 项%s"
           % (len(results), found, len(missing), len(unverified),
              "（另有 %d 项客群已删但名单在，不计缺失）" % len(downgraded) if downgraded else ""))
    if notes:
        ui.log("---- 提示（不算缺失）----")
        for line in notes:
            ui.log("  ⓘ %s" % line)
    if audit:
        ui.log("客群达标（只报数、不影响退出码）：%d 桶达标 / %d 桶不达标 / %d 桶没读到"
               % audit)
    if missing or unverified:
        ui.log("RESULT: 有缺失 %d 项 / 未确认 %d 项" % (len(missing), len(unverified)))
        sys.exit(1)
    ui.log("RESULT: 全部在位")
    sys.exit(0)


if __name__ == "__main__":
    main()
