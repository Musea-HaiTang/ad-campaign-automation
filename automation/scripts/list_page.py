# -*- coding: utf-8 -*-
"""后台「列表页」共用层：翻开一页 → 填筛选 → 查询 → 按名字取行。

为什么要有它（2026-09-23 架构体检 候选 1）：「筛一个框 → 点查询 → 等这张表真的出数据 →
按名字取出一条」这条知识原先在 5 个模块里各写一遍（`audience_metrics` / `check_campaign` /
`run_distribution` / `run_taskgroup` / `run_distribution_ids`），连「哪份输入框是真的」的判据
都分叉了——2026-09-22 就因此把 5 个**已经建好**的名单全报成「未找到」。

分工（别混）：
  - `csdn_ui.py`：无状态原语（点、填、等、截图、下拉、弹窗、清场）；
  - 本模块：**列表页这一层**——页签作用域、冻列碎片合并、按名字取行、查询落地；
  - 各 `run_*.py` 与 `audience_metrics.py`：这一页的**业务语义**（哪几列、多少算达标、步骤顺序）。

规矩：
  - **只读与查询**：不提供「新建 / 新增 / 提交 / 确定」这类写入动作——写入留在各 `run_*.py`
    的提交闸门里，这样「体检只读」是结构上的保证，不靠人记得；
  - 只用条件等待（`csdn_ui.wait_for`）：页面早好了就少等，慢就多等，不新增固定死等；
  - 等不到**不抛错**，返回「没等到」让调用方决定（体检报「未找到」、圈选重填筛选再试）；
    只有**结构性错误**（菜单/筛选框根本不在页面上）才抛，当场停下。

真机形状（2026-09-21/22 实测）：
  - 后台把**所有页签都留在 DOM 里**，隐藏页签的表也有行 → 数行/取行一律限定在「当前可见页签」；
  - Element UI 冻列把**一条记录拆成三份 DOM 行**（主表体 / 左冻列 / 右冻列），三份在各自 tbody 里
    **行号相同** → 按行号合并再解析。⚠ 冻列副本在 **`.el-table__fixed-body-wrapper`** 里，
    只读 `.el-table__body-wrapper` 拿到的是"半张行"（实测 2026-09-23：13 格里前三格空、既没 ID 也没名称）；
  - 一张 `.el-table` 根 = 一张逻辑表（冻列副本在根内部）→ 取行按「表根 → 两种表体」收集碎片；
  - 输入框常有隐藏副本 → 一律走 `csdn_ui.visible_input` / `fill_visible`。

用法：
    ui.goto(page, "https://mp-admin.csdn.net/silkroad-dist/#/distribute/distUser")
    lp = list_page.open_list(page, menu="圈选用户", tab="博文圈选任务",
                             wait_input="请输入圈选任务名称")
    lp.filter({"请输入圈选任务名称": "火山引擎MediaKit-hang"})
    lp.query(wait_ms=2500)
    row = lp.row_by_name("火山引擎MediaKit-hang-A类 · AI 编程 / Agent 工具")
    if row:
        row.button("停止")
"""
import re

import csdn_ui as ui

TAB_PANE = ".el-tab-pane:visible"
T_WAIT = 12.0            # 等侧边菜单 / 页签 / 筛选框
T_ROWS = 12.0            # 等这一页的表出数据（分发名单那张异步表实测要 ~3 秒）
T_QUERY = 8.0            # 点「查询」后最多等多久
DEFAULT_QUERY_MS = 1200  # 「查询」没转圈时的固定底；读达标数字的页面自己传大一点（防读到旧数）
ROW_TOLERANCE = 60       # 坐标兜底：按钮与这一行的 y 中线差多少算同一行
# 一条记录的碎片住在这两种表体里：主表体 + 冻列副本（左/右冻列共用后者）
BODY_WRAPPERS = (".el-table__body-wrapper tbody tr",
                 ".el-table__fixed-body-wrapper tbody tr")


def merge_cells(*parts):
    """同一逻辑行的几份 DOM 碎片 → 按列号合并，第一个非空值胜出。"""
    out = []
    for part in parts:
        for j, v in enumerate(part):
            if j >= len(out):
                out.append(v)
            elif not out[j] and v:
                out[j] = v
    return out


def scope_of(page, pane=None):
    """这一页的作用域：调用方给了就用给的；没给就「有可见页签就用它，没有就整页」。

    带页签的列表页必须限定在**当前可见页签**里数行/取行——隐藏页签的表也有行，全页数会被它满足。
    """
    if pane:
        return pane
    try:
        if page.locator(TAB_PANE).count():
            return TAB_PANE
    except Exception:
        pass
    return ""


def _sel(scope, rest):
    return ("%s %s" % (scope, rest)) if scope else rest


def _row_index(el):
    """这一份碎片的行号（同一逻辑行的几份碎片行号相同）。"""
    return el.evaluate("tr => Array.prototype.indexOf.call(tr.parentNode.children, tr)")


def _visible_box(loc):
    """元素可见且框非空时返回 bounding_box，否则 None。"""
    try:
        if not loc.is_visible():
            return None
        b = loc.bounding_box()
    except Exception:
        return None
    if not b or b["width"] <= 0 or b["height"] <= 0:
        return None
    return b


def _read_rows(page, scope):
    """当前页签里的记录行：按行号把冻列碎片合并成一行（读不到就是空列表）。

    **一张表内**合并（不是整页按行号合并）：多张表各有自己的行号，混在一起就把两张表缝成一条记录了。
    """
    out = []
    tables = page.locator(_sel(scope, ".el-table"))
    for i in range(tables.count()):
        groups = {}
        for sel in BODY_WRAPPERS:
            els = tables.nth(i).locator(sel)
            for j in range(els.count()):
                el = els.nth(j)
                cells = [c.strip() for c in el.locator("td").all_inner_texts()]
                try:
                    idx = _row_index(el)
                except Exception:
                    idx = j
                groups.setdefault(idx, []).append((el, cells))
        for idx in sorted(groups):
            pairs = groups[idx]
            with_cells = [cells for _, cells in pairs if cells]
            if not with_cells:
                continue                 # 这一行号上没有真格子（表头/占位行），不是一条记录
            # ⚠ 没有 td 的那几份碎片也要带进 `els`：按钮/复选框就住在那种碎片里
            out.append(Row(page, [el for el, _ in pairs], merge_cells(*with_cells)))
    return out


class Row:
    """列表里的一条记录：冻列碎片按行号合并成的一行。"""

    def __init__(self, page, els, cells, name=""):
        self.page = page
        self.els = list(els)
        self.cells = list(cells)
        self.name = name        # 按名字取到的那行才有名字；`rows()` 出来的为空串

    @property
    def id(self):
        """这一行里第一个**纯数字**格子（后台把记录 ID 放在某一列），没有就空串。"""
        for c in self.cells:
            if re.fullmatch(r"\d+", (c or "").strip()):
                return c.strip()
        return ""

    def text(self):
        """整行文字（业务列自己从 `cells` 取；这里只给一行连着看）。"""
        return " ".join(c.strip() for c in self.cells if c and c.strip())

    def button(self, text):
        """点这一行里写着这段文字的按钮（冻列副本里也算），点了返回 True。

        结构定位摸不到时按 y 中线找同排按钮：element-ui 的冻列克隆节点里按钮文案常常是空的，
        `run_distribution` 当年就是靠这个兜底才点到「一键创建分发名单」。
        """
        for el in self.els:
            try:
                cands = el.locator("button:visible").filter(has_text=text)
                for i in range(cands.count()):
                    if _visible_box(cands.nth(i)):
                        cands.nth(i).click()
                        return True
            except Exception:
                continue
        return self._button_by_row_y(text)

    def checkbox(self):
        """勾上这一行的复选框；返回是不是已勾上（没勾上调用方可以再点一次）。"""
        for el in self.els:
            try:
                boxes = el.locator(".el-checkbox")
                for i in range(boxes.count()):
                    b = boxes.nth(i)
                    if b.is_visible():
                        b.click()
                        return "is-checked" in (b.get_attribute("class") or "")
            except Exception:
                continue
        return False

    @property
    def checked(self):
        """这一行的复选框**现在**是不是勾上了（只看不点，条件等待用）。"""
        for el in self.els:
            try:
                if el.locator(".el-checkbox.is-checked").count():
                    return True
            except Exception:
                continue
        return False

    def _button_by_row_y(self, text):
        """坐标兜底：这一行的 y 中线上，最近的同名按钮（偏差在半行高内才算）。"""
        y = None
        for el in self.els:
            b = _visible_box(el)
            if b:
                y = b["y"] + b["height"] / 2.0
                break
        if y is None:
            return False
        btns = self.page.locator("button:visible").filter(has_text=text)
        best = None
        for i in range(btns.count()):
            b = _visible_box(btns.nth(i))
            if not b:
                continue
            d = abs((b["y"] + b["height"] / 2.0) - y)
            if best is None or d < best[0]:
                best = (d, btns.nth(i))
        if best is None or best[0] > ROW_TOLERANCE:
            return False
        best[1].click()
        return True


class ListPage:
    """翻开的一页：记住作用域（页签）与筛选表单，供反复查询。"""

    def __init__(self, page, scope=""):
        self.page = page
        self.scope = scope

    # ---------- 填 / 查 ----------
    def filter(self, values, enter=()):
        """填筛选条件（**只填不查**，填完可以反复点查询）。返回没填上的字段名列表。

        `values` = {筛选框 placeholder: 要填的值}；`enter` = 填完要按回车的字段
        （日期框需要——Element UI 不按回车不认账）。
        """
        if isinstance(enter, str):
            enter = (enter,)
        missed = []
        for ph, value in values.items():
            if value in (None, ""):
                continue
            if not ui.fill_visible(self.page, ph, str(value)):
                missed.append(ph)
            elif ph in enter:
                el = ui.visible_input(self.page, ph)
                try:
                    if el is None:
                        missed.append(ph)
                    else:
                        el.press("Enter")
                except Exception:
                    missed.append(ph)
        return missed

    def query(self, wait_ms=None, wait_rows=True):
        """点「查询」→ 等这次查询落地（加载遮罩）→ 等当前页签的表出数据。

        返回表有没有出数据。`wait_ms` 是「没看到遮罩」时的固定底：读达标数字的页面要传大一点
        （如 2500），否则可能读到上一次查询的旧数——2026-09-21 踩过。
        """
        ui.click_query(self.page,
                       floor_ms=DEFAULT_QUERY_MS if wait_ms is None else wait_ms,
                       timeout=T_QUERY, scope=self.scope)
        return self.wait_rows() if wait_rows else True

    def wait_rows(self, timeout=None):
        """等这一页的表出数据（条件等待；真的是空表就等满上限，返回 False）。

        上限在**调用时**取 `T_ROWS`（不是定义时），测试才能把它调小、调用方也能自己传。
        """
        timeout = T_ROWS if timeout is None else timeout
        return ui.wait_for(self.page, lambda: ui.table_has_rows(self.page, scope=self.scope),
                           timeout=timeout, what="列表出数据")

    # ---------- 取行 ----------
    def rows(self, timeout=None):
        """这一页当前的所有记录行（碎片已合并）。给了 timeout 就先等表出数据。"""
        if timeout:
            self.wait_rows(timeout)
        return _read_rows(self.page, self.scope)

    def row_by_name(self, name, timeout=None):
        """取「某一格**恰好等于** name」的那一行；等不到返回 None。

        只认全等（不认前缀/包含）：后台里 `…-4` 会排在同前缀的 `…` 前面，前缀匹配已经抢错过
        一次名单（见 `csdn_ui._pick_option` 的教训）。名字带展示后缀（`桶名 · 主题`）用
        `row_containing()`。
        """
        return self._wait_row(name, lambda r: any(c.strip() == name for c in r.cells), timeout)

    def row_containing(self, text, timeout=None):
        """取「行里任意一格含这段文字」的那一行；等不到返回 None。"""
        return self._wait_row(text, lambda r: text in r.text(), timeout)

    def text(self):
        """整页文字（体检核对名字在不在用）。"""
        return self.page.locator("body").inner_text()

    def _wait_row(self, name, match, timeout):
        """等某一行出现：等到就返回（行上带住名字），等不到返回 None。"""
        timeout = T_ROWS if timeout is None else timeout
        hit = []

        def probe():
            for row in _read_rows(self.page, self.scope):
                if match(row):
                    row.name = name
                    hit[:] = [row]
                    return True
            return False

        ui.wait_for(self.page, probe, timeout=timeout, what="列表里的一行 %r" % name)
        return hit[0] if hit else None


def open_list(page, menu=None, tab=None, wait_input=None, pane=None, timeout=None):
    """翻开一个列表页：点侧边菜单 → 切页签 → 等筛选框出现。返回 `ListPage`。

    整页重开用 `csdn_ui.goto()`（那是原语）；本函数只管「这一页怎么翻开来」。
    `wait_input` 传「下一步就要用的那个筛选框」——等它可见即算这一页渲染好（比固定死等既快又稳）。
    **菜单/筛选框都等不到就抛错**：那是结构性错误（没登录 / 页面结构变了），当场停下比一路跑空好。
    没有页签的列表页不传 `tab`；不传 `pane` 时按「有可见页签就用它」自动定作用域。
    """
    timeout = T_WAIT if timeout is None else timeout      # 上限在调用时取，测试/调用方才调得动
    if menu:
        m = page.get_by_text(menu, exact=False).first
        if not ui.wait_for(page, lambda: ui.is_visible(m), timeout=timeout,
                           what="侧边菜单 %s" % menu):
            raise RuntimeError("列表页上找不到侧边菜单「%s」——先确认登录态（wait_login.py）" % menu)
        m.click()
    if tab:
        t = page.locator(".el-tabs__item").filter(has_text=tab).first
        if not ui.wait_for(page, lambda: ui.is_visible(t), timeout=timeout, what="页签 %s" % tab):
            raise RuntimeError("列表页上找不到页签「%s」" % tab)
        t.click()
    lp = ListPage(page, scope_of(page, pane))
    if wait_input:
        if not ui.wait_for(page, lambda: ui.visible_input(page, wait_input) is not None,
                           timeout=timeout, what="筛选框 %r" % wait_input):
            raise RuntimeError("列表页上找不到可见的筛选框 %r" % wait_input)
    return lp
