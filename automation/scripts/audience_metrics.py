# -*- coding: utf-8 -*-
"""圈选任务的「达标读数」共用层：读后台四列 → 判达标 → 等它刷出来。

谁用：`check_campaign.py`（活动体检）和 `run_audience.py --verify`（建完就体检）。
只读页面：后台「圈选用户 → **博文圈选任务**」列表的四列
`实际圈选博客ID数 / 日均点击(预估) / 日均曝光(预估) / 日均pv(预估)`。

分工（2026-09-23 架构体检 候选 1 起）：**这一页怎么翻、怎么筛、怎么取行由 `list_page` 负责**；
本模块只剩客群这一层的语义——哪四列、哪一格是名字、多少算达标。

真机要点（2026-09-21 实测）：

1. **这几项建完、等后台算完才刷出来**；创建弹窗里只有「预估圈选总数」（= 博文ID个数，不是曝光）。
2. **列表默认只筛最近 4 天**（真机：09-18 ~ 09-21）→ 老客群根本不出现。所以查询前把
   开始日期拉到 `DATE_FROM`；否则体检会假报「客群缺失」。
3. 查询只在当前页（脚本用前缀筛过）内做，**不翻页**。

（一条记录被拆成三份 DOM 行、页签留在 DOM 里这些页面形状，见 `list_page.py` 的模块注释。）
"""
import re
from datetime import date

import csdn_ui as ui
import list_page

DISTUSER_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/distUser"
TAB_BLOG = "博文圈选任务"             # 圈选任务所在的页签
PH_TASK_NAME = "请输入圈选任务名称"
PH_CREATOR = "请输入用户名称"
PH_DATE_FROM = "开始日期"
PH_DATE_TO = "结束日期"

DATE_FROM = "2020-01-01"              # 老客群也要能查出来
DEF_TARGET_EXPOSURE = 10000           # 当前口径：日均曝光(预估)达标线
DEF_MIN_EXPOSURE = DEF_TARGET_EXPOSURE

OK = "达标"
NEAR = "过线未达标"
LOW = "不达标"
PENDING = "待后台（还没算完）"
MISSING = "列表里没有"


# ---------- 解析（纯函数，可单测） ----------
def row_metrics(cells):
    """合并后的一行 → (ID, 名称, 圈选博客ID数, 日均点击, 日均曝光, 日均pv)；认不出来返回 None。

    形状（真机 2026-09-21）：['', '140', '测试1', '2026-09-21 09:44:09', '12370',
    '62.61', '7757.27', '37576.92', <关键词列表>, '', 'creator01', '', ...]
    """
    ids = [i for i, c in enumerate(cells) if re.fullmatch(r"\d+", c)]
    dates = [i for i, c in enumerate(cells) if re.match(r"\d{4}-\d{2}-\d{2}", c)]
    if not ids or not dates:
        return None
    d = dates[0]
    if d < 1 or d + 4 >= len(cells):
        return None
    name = cells[d - 1].strip()
    if not name:
        return None
    nums = []
    for raw in cells[d + 1:d + 5]:
        try:
            nums.append(float(raw.replace(",", "")))
        except ValueError:
            nums.append(None)
    return (cells[ids[0]], name) + tuple(nums)


def verdict(exposure, target=DEF_TARGET_EXPOSURE, floor=DEF_MIN_EXPOSURE):
    """日均曝光(预估) → (判定词, 是否达标)。没刷出数（None）= 待后台。"""
    if exposure is None:
        return PENDING, None
    if exposure >= target:
        return OK, True
    if exposure >= floor:
        return NEAR, False
    return LOW, False


def fmt(v):
    if v is None:
        return "—"
    return str(int(v)) if float(v).is_integer() else "%.2f" % v


# ---------- 这一页：怎么翻、怎么筛（页面动作全在 `list_page`） ----------
def open_tab(page, url=None):
    """进「圈选用户 → 博文圈选任务」列表，返回 `list_page.ListPage` 把手。

    `url` 传了就先整页重开；不传就就地切菜单（已经在后台别的页面时用）。
    """
    if url:
        ui.goto(page, url)
    lp = list_page.open_list(page, menu="圈选用户", tab=TAB_BLOG, wait_input=PH_TASK_NAME)
    # 2026-09-22：表格行比筛选框晚渲染 —— 不等它，第一轮会读到空表（结论仍以实际读到为准）
    lp.wait_rows(timeout=6)
    return lp


def apply_filters(lp, prefix="", creator="", from_date=DATE_FROM, to_date=None, log=None):
    """填**客群这一页专用的**筛选：日期窗（后台默认只筛最近 4 天）+ 名称 + 创建人。

    只填不查——填完用同一个把手反复 `lp.query()`。返回没填上的字段名（空列表 = 全填上）。
    """
    to_date = to_date or date.today().isoformat()
    values = {PH_DATE_FROM: from_date, PH_DATE_TO: to_date}
    if prefix:
        values[PH_TASK_NAME] = prefix
    if creator:
        values[PH_CREATOR] = creator
    missed = lp.filter(values, enter=(PH_DATE_FROM, PH_DATE_TO))
    if log:
        log("  筛选: 名称含 %r | 创建人 %r | %s ~ %s %s"
            % (prefix, creator or "不限", from_date, to_date,
               "✓" if not missed else "⚠ 没填上：%s（可能沿用默认 4 天窄窗）" % "、".join(missed)))
    return missed


def read_metrics(lp):
    """读列表 → {圈选任务名: {id, blogs, click, exposure, pv}}（只读当前页）。

    取行、合并冻列碎片是 `list_page` 的事；这里只管「哪一格是什么」——客群这一页的列语义。
    """
    out = {}
    for row in lp.rows():
        m = row_metrics(row.cells)
        if not m:
            continue
        tid, name, blogs, click, exposure, pv = m
        out.setdefault(name, {"id": tid, "blogs": blogs, "click": click,
                              "exposure": exposure, "pv": pv})
    return out


def wait_ready(lp, names, *, timeout_s=900, interval_s=10, prefix="", creator="",
               target=DEF_TARGET_EXPOSURE, floor=DEF_MIN_EXPOSURE, log=print,
               sleep=None, clock=None):
    """反复点「查询」直到 names 都有数（或超时）。浏览器一直开着，页面就在这一页。

    调用前先 `open_tab(page)` + `apply_filters(lp, prefix=...)`：筛选条件留在表单里，
    之后只重复「点查询 + 读表」，不重开页面。

    返回 {名字: metrics}；等不到的按 None 记（调用方据此判「待后台」）。
    """
    import time as _time
    sleep = sleep or _time.sleep
    now = clock or _time.monotonic
    deadline = now() + timeout_s
    last = {}
    rounds = 0
    while True:
        rounds += 1
        # 「点查询 + 立刻读表」是这一层原来的节奏：数还没刷出来时读到的就是空表，
        # 空表由下面的 apply_filters 重填兜底（见 WaitReadyTest「列表整片空了就重填筛选」）
        lp.query(wait_rows=False)
        last = read_metrics(lp)
        ready = [n for n in names if last.get(n) and last[n]["exposure"] is not None]
        waiting = [n for n in names if n not in ready]
        log("  第 %d 次查询：已出数 %d/%d%s（间隔 %ds，上限 %ds）"
            % (rounds, len(ready), len(names),
               "" if not waiting else " | 还等：" + "、".join(w.split(" · ")[-1] for w in waiting),
               interval_s, timeout_s))
        if not waiting:
            return last
        if now() >= deadline:
            log("  ⚠ 等到上限还没出数，按「待后台」收尾（可以过会儿再跑一次 --verify）")
            return last
        if not last:                       # 列表空 → 筛选可能被重置，重填一遍再查
            apply_filters(lp, prefix=prefix, creator=creator, log=None)
        sleep(interval_s)


def report(page_names, metrics, target=DEF_TARGET_EXPOSURE, floor=DEF_MIN_EXPOSURE, log=print):
    """打达标表 + 汇总。返回 (达标数, 未达标数, 没读到数)。"""
    okc = miss = 0
    if target == floor:
        rule = "≥ %s" % fmt(target)
    else:
        rule = "目标 %s / 底线 %s" % (fmt(target), fmt(floor))
    log("---- 客群达标（日均曝光(预估) %s）----" % rule)
    for n in page_names:
        m = metrics.get(n)
        if not m:
            miss += 1
            log("  ? %s | %s" % (n, MISSING))
            continue
        word, good = verdict(m["exposure"], target, floor)
        if good:
            okc += 1
        elif m["exposure"] is None:
            miss += 1
        log("  %s %s | 圈选博客ID %s | 日均点击 %s | 日均曝光 %s | %s"
            % ("✓" if good else "✗", n, fmt(m["blogs"]), fmt(m["click"]),
               fmt(m["exposure"]), word))
    log("达标 %d / 未达标 %d / 没读到 %d（只报数，不影响退出码）"
        % (okc, len(page_names) - okc - miss, miss))
    return okc, len(page_names) - okc - miss, miss


# ---------- 行操作：停止 / 勾选 / 批量删除（用户 2026-09-21 给的步骤） ----------
def confirm_if_any(page, log=None, wait_ms=900):
    """有确认弹窗就点「确定」（停止 / 批量删除都可能弹）。"""
    page.wait_for_timeout(wait_ms)
    for sel in (".el-message-box:visible", ".el-dialog:visible"):
        d = page.locator(sel)
        if d.count():
            btn = d.last.locator("button").filter(has_text="确定")
            if btn.count():
                btn.last.click()
                page.wait_for_timeout(wait_ms)
                if log:
                    log("  （弹窗确认：点了「确定」）")
                return True
    return False


def _pane_button(lp, text):
    """页签里的页面级按钮（如「批量删除」）；行内按钮走 `Row.button()`。"""
    pre = (lp.scope + " ") if lp.scope else ""
    return lp.page.locator("%sbutton:visible" % pre).filter(has_text=text).first


def delete_tasks(lp, names, *, log=print, wait_ms=1200):
    """删圈选任务：每行先「停止」→ 勾选 → 点「批量删除」→ 确认。

    只动**圈选任务**（客群），绝不碰资源 / 分发名单 / 任务工单。
    返回真正删掉的名字列表（删完回列表复读确认）。
    """
    page = lp.page
    # ① 先把要删的都「停止」——停止会让表格重渲染，**会清掉已勾选的项**，
    #    所以不能边停止边勾选（踩坑 2026-09-21：那样只删掉最后一个）。
    for name in names:
        row = lp.row_by_name(name, timeout=0)
        if not row:
            log("  ✗ 找不到 %r（没建成 / 名字不对 / 已经删了）" % name)
            continue
        log("  停止 %s（id=%s）" % (name, row.id))
        if not row.button("停止"):
            log("  ⚠ 没找到「停止」按钮，直接进入勾选")
        confirm_if_any(page, log)
        page.wait_for_timeout(wait_ms)

    # ② 全部停完，再统一勾选
    picked = []
    for name in names:
        row = lp.row_by_name(name, timeout=0)
        if not row:
            log("  ✗ 停止后这一行不见了：%r" % name)
            continue
        ok = row.checkbox()
        if not ok:                              # 没勾上就再点一次（重渲染吃掉点击）
            # 2026-09-22：原来固定 400ms。改成等这一行重渲染回来（最多 2 秒）
            ui.wait_for(page, lambda: lp.row_by_name(name, timeout=0) is not None,
                        timeout=2, what="行重渲染")
            row = lp.row_by_name(name, timeout=0)
            ok = bool(row) and row.checkbox()
        if ok:
            picked.append(name)
        else:
            log("  ✗ 没勾上 %r" % name)
        # 2026-09-22：原来固定 400ms。改成等复选框真的显示"已勾选"（最多 2 秒）
        ui.wait_for(page, lambda: bool(row) and row.checked, timeout=2, what="复选框勾上")

    if not picked:
        log("  ✗ 一个都没勾上，不点批量删除")
        return []

    log("  批量删除 %d 个：%s" % (len(picked), "、".join(picked)))
    btn = _pane_button(lp, "批量删除")
    if not btn.count():
        log("  ✗ 找不到「批量删除」按钮")
        return []
    btn.click()
    confirm_if_any(page, log)
    # 2026-09-22：原来固定 1500ms。改成等这批名字从列表里消失（最多 5 秒）
    ui.wait_for(page, lambda: not any(n in page.locator("body").inner_text() for n in picked),
                timeout=5, what="批量删除生效")

    lp.query(wait_rows=False)
    left = read_metrics(lp)
    gone = [n for n in picked if n not in left]
    still = [n for n in picked if n in left]
    if still:
        log("  ⚠ 还在列表里（可能没删掉）：%s" % "、".join(still))
    log("  已确认删掉 %d 个" % len(gone))
    return gone
