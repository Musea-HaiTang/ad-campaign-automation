# -*- coding: utf-8 -*-
"""测试用假柜台：不开真浏览器，直接喂一个假 page。

两套，按被测的层挑：
  - `FakePage` 家族（`QueryPage` / `TwoCopyPage` / `TablePage`）：**原语层**——下拉、弹窗、
    穿梭框、截图、条件等待、查询遮罩（`test_csdn_ui.py` 用）；
  - `FakeListPage` 家族：**列表页层**——多张表 / 冻列碎片 / 行内按钮 / 复选框 / 筛选框
    （`test_list_page.py` 用）。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
sys.path.insert(0, str(ROOT / "scripts"))

import csdn_ui  # noqa: E402

# 后台里这几栏是 el-select（点一下会弹出下拉），其余是普通输入框
SELECT_BOXES = {
    csdn_ui.PH_TASK_GROUP,
    csdn_ui.PH_DEPT,
    csdn_ui.PH_SUBLINE,
    csdn_ui.PH_DIST_MODE,
    csdn_ui.PH_DIST_LIST,
}
# 这几栏永远在页面上（不必先出现在 values 里）
ALWAYS_PRESENT = {csdn_ui.PH_TRANSFER_SEARCH}


def placeholder_of(sel):
    m = re.search(r"placeholder='([^']*)'", sel)
    return m.group(1) if m else None


# ---------- 假元素 / 假 locator ----------
class El:
    def __init__(self, text="", visible=True, enabled=True, clickable=True):
        self.text = text
        self.visible = visible
        self.enabled = enabled
        self.clickable = clickable


class FL:
    """假 locator：用一列假元素表示「这个选择器匹配到了几个东西」。"""

    def __init__(self, page, items, sel=""):
        self._page = page
        self._items = items
        self._sel = sel

    @property
    def first(self):
        return FL(self._page, self._items[:1], self._sel)

    @property
    def last(self):
        return FL(self._page, self._items[-1:], self._sel)

    def locator(self, sel):
        return FL(self._page, self._page.resolve(sel), sel)

    def filter(self, has_text=None):
        if not has_text:
            return self
        return FL(self._page, [e for e in self._items if has_text in e.text], self._sel)

    def count(self):
        return len(self._items)

    def nth(self, i):
        return FL(self._page, self._items[i : i + 1], self._sel)

    def inner_text(self):
        return self._items[0].text if self._items else ""

    def all_inner_texts(self):
        return [e.text for e in self._items]

    def input_value(self):
        return self._page.values.get(self._sel, "")

    def is_visible(self):
        return bool(self._items) and self._items[0].visible

    def is_enabled(self):
        return bool(self._items) and self._items[0].enabled

    def wait_for(self, state=None, timeout=None):
        if state == "visible" and not self.is_visible():
            raise RuntimeError("元素没有出现:%s" % self._sel)

    def click(self, force=False, timeout=None):
        if self._items:
            self._page.click(self._items[0], self._sel)

    def fill(self, value):
        self._page.values[self._sel] = value


class FakeKeyboard:
    def __init__(self, page):
        self._page = page
        self.presses = []

    def press(self, key):
        self.presses.append(key)
        if key == "Escape" and self._page.dialog_closes_on_esc:
            self._page.dialogs = max(0, self._page.dialogs - 1)

    def insert_text(self, text):
        self._page.search_text = text


class FakePage:
    """够用的假后台页面：下拉选项、弹窗、穿梭框、截图。"""

    def __init__(self, options=(), dialogs=0, dialog_closes_on_esc=True):
        self.options = list(options)
        self.dropdown_open = False
        self.dialogs = dialogs
        self.dialog_closes_on_esc = dialog_closes_on_esc
        self.clicked = []          # 被点中的下拉项文本
        self.screenshots = []      # 截图路径
        self.waits = 0             # wait_for_timeout 次数（用来证明「等过」）
        self.values = {}           # 输入框/文本域里的值，按选择器存
        self.keyboard = FakeKeyboard(self)
        self.dialog_close_clicks = 0
        self.transfer_checked = False
        self.transfer_moved = False
        self.blocked = set()      # 这些 placeholder 的下拉"点不动"（模拟被 .el-select__tags 盖住）
        self.wrap_clicks = 0      # 点外层容器的次数
        self.search_text = ""     # 检索框里输的内容（决定下拉返回哪些项）
        self.real_names = {}      # 选项显示文本 -> 后台真名（后台检索只认真名）

    # ---- 模块会用到的页面 API ----
    def locator(self, sel):
        return FL(self, self.resolve(sel), sel)

    def wait_for_selector(self, sel, timeout=None):
        if "el-select-dropdown:visible" in sel and not self.dropdown_open:
            raise AssertionError("下拉没打开就等浮层，说明顺序错了")

    def wait_for_timeout(self, ms):
        self.waits += 1

    def screenshot(self, path=None, full_page=False):
        self.screenshots.append(path)
        pathlib.Path(path).write_bytes(b"fake-png")

    def goto(self, url, wait_until=None, timeout=None):
        pass

    # ---- 选择器 -> 假元素 ----
    def resolve(self, sel):
        if "el-select-dropdown__item" in sel:
            if not self.dropdown_open:
                return []
            q = self.search_text
            return [
                El(t) for t in self.options if not q or self.real_names.get(t, t).startswith(q)
            ]
        if "el-select-dropdown:visible" in sel:
            return [El("dropdown")] if self.dropdown_open else []
        if "opt-name" in sel:
            return []  # 模块会退回到项自身文本，跟真后台一致
        if "el-dialog__headerbtn" in sel:
            return [El("x")] if self.dialogs else []
        if "el-dialog:visible" in sel:
            return [El("dialog") for _ in range(self.dialogs)]
        if "el-transfer-panel" in sel or "el-transfer" in sel:
            return [El("transfer")]
        if "label.el-checkbox" in sel:
            return [El(self.values.get("input[placeholder='%s']" % csdn_ui.PH_TRANSFER_SEARCH, ""))]
        if "el-checkbox__inner" in sel:
            return [El("inner")]
        if "input[type='checkbox']" in sel:
            return [El("cb", visible=self.transfer_checked)]
        if "el-checkbox__label" in sel:
            return [
                El(
                    self.values.get("input[placeholder='%s']" % csdn_ui.PH_TRANSFER_SEARCH, ""),
                    visible=self.transfer_moved,
                )
            ]
        if ".el-transfer__buttons button" in sel:
            return [El("move", enabled=True)]
        if sel.startswith("xpath=ancestor::div[contains(@class,'el-select')"):
            return [El("wrap")]  # 外层容器（fallback 用）
        ph = placeholder_of(sel)
        if ph is not None:
            if ph in SELECT_BOXES:
                return [El("select", clickable=ph not in self.blocked)]
            if ph in ALWAYS_PRESENT or sel in self.values:
                return [El("field")]
        return []

    def click(self, el, sel):
        if not el.clickable:
            raise RuntimeError("... intercepts pointer events（模拟被别的输入框盖住）")
        if "el-select-dropdown__item" in sel:
            self.clicked.append(el.text)
            self.dropdown_open = False  # 点中之后浮层收起
        elif sel.startswith("xpath=ancestor::div[contains(@class,'el-select')"):
            self.wrap_clicks += 1
            self.dropdown_open = True  # 点外层容器同样能点开
        elif "el-checkbox__inner" in sel:
            self.transfer_checked = True
        elif "el-transfer__buttons button" in sel:
            self.transfer_moved = True
        elif "el-dialog__headerbtn" in sel:
            self.dialog_close_clicks += 1
            self.dialogs = max(0, self.dialogs - 1)
        elif sel.startswith("input[placeholder=") and "搜索内容" not in sel:
            self.dropdown_open = True  # 点开 el-select


# ---------- 假 expect（真 expect 只认真 Playwright 对象） ----------
class QueryPage(FakePage):
    """体检/圈选查询用的假页面：一个「查询」按钮 + 可控的加载遮罩。

    `mask_reads` = 点完查询后，前几次读页面上还剩着加载遮罩（模拟后台还在算）；
    传 `None` = 遮罩永远不退（模拟后台卡死，用来验超时收尾）。
    `mask_visible=False` = 遮罩元素**一直在 DOM 里、但藏起来**（真机就是这样，见
    `_tmp/probe_mask.py`：`display:none`）——`:visible` 看不见它，`count()` 数得到它。
    """

    def __init__(self, mask_reads=0, mask_visible=True, **kw):
        super().__init__(**kw)
        self.mask_reads = mask_reads
        self.mask_visible = mask_visible
        self.query_clicks = 0

    def resolve(self, sel):
        if "el-loading-mask" in sel:
            want_visible = ":visible" in sel
            if not self.mask_visible:
                # 藏着的那份：只在"不要求可见"时数得到（真机就是 display:none）
                return [] if want_visible else [El("mask", visible=False)]
            if self.mask_reads is None:
                return [El("mask")]
            if self.mask_reads > 0:
                self.mask_reads -= 1
                return [El("mask")]
            return []
        if sel.strip() == "button:visible":
            return [El("查询")]
        return super().resolve(sel)

    def click(self, el, sel):
        if sel.strip() == "button:visible":
            self.query_clicks += 1
            return
        super().click(el, sel)


class TwoCopyPage(FakePage):
    """同一个 placeholder 在 DOM 里有隐藏副本 + 可见副本（后台固定列的常见形态）。"""

    def resolve(self, sel):
        if "dup-field" in sel:
            return [El("hidden", visible=False), El("shown", visible=True)]
        return super().resolve(sel)


class TablePage(FakePage):
    """带一张表格的假页面（`rows` = 表体有几行）。"""

    def __init__(self, rows=0, **kw):
        super().__init__(**kw)
        self.rows = rows

    def resolve(self, sel):
        if "el-table__body-wrapper" in sel:
            return [El("row") for _ in range(self.rows)]
        return super().resolve(sel)


class FakeExpect:
    def __init__(self, target):
        self._t = target

    def to_have_count(self, n, timeout=None):
        assert self._t.count() == n, "期望匹配 %d 个，实际 %d 个" % (n, self._t.count())

    def to_be_visible(self, timeout=None):
        assert self._t.is_visible(), "元素不可见:%s" % self._t._sel

    def to_be_checked(self, timeout=None):
        assert self._t.is_visible(), "没勾上:%s" % self._t._sel


# ---------- 列表页层的假页面（多表 / 冻列碎片 / 行内按钮 / 复选框） ----------
class LNode:
    """假 DOM 节点：文本 + 可见性 + 框 + 「子选择器 → 子节点」。"""

    def __init__(self, text="", visible=True, box=None, index=None, kinds=None,
                 checked=False, onclick=None):
        self.text = text
        self.visible = visible
        self.box = box
        self.index = index
        self.kinds = kinds or {}
        self.checked = checked
        self.onclick = onclick


class LLoc:
    """假 locator：包一串假节点（只做 `list_page` 用到的那几件事）。"""

    def __init__(self, page, items, sel=""):
        self._page = page
        self._items = list(items)
        self._sel = sel

    @property
    def first(self):
        return LLoc(self._page, self._items[:1], self._sel)

    @property
    def last(self):
        return LLoc(self._page, self._items[-1:], self._sel)

    def count(self):
        return len(self._items)

    def nth(self, i):
        return LLoc(self._page, self._items[i:i + 1], self._sel)

    def locator(self, sel):
        out = []
        for n in self._items:
            if sel == ".el-checkbox.is-checked":        # 真页面上是现查现算的，别用建节点时的快照
                out.extend([c for c in n.kinds.get(".el-checkbox", ()) if c.checked])
                continue
            out.extend(n.kinds.get(sel, ()))
        return LLoc(self._page, out, sel)

    def filter(self, has_text=None, **kw):
        if not has_text:
            return self
        return LLoc(self._page, [n for n in self._items if has_text in n.text], self._sel)

    def all_inner_texts(self):
        return [n.text for n in self._items]

    def inner_text(self):
        return self._items[0].text if self._items else ""

    def is_visible(self):
        return bool(self._items) and self._items[0].visible

    def is_enabled(self):
        return True

    def bounding_box(self):
        """框：测试里写成 (x, y, w, h) 元组，这里转成 Playwright 那种字典。"""
        b = self._items[0].box if self._items else None
        if not b:
            return None
        if isinstance(b, dict):
            return b
        x, y, w, h = b
        return {"x": x, "y": y, "width": w, "height": h}

    def evaluate(self, js):
        return self._items[0].index if self._items else None

    def get_attribute(self, name):
        if name == "class" and self._items and self._items[0].checked:
            return "el-checkbox is-checked"
        return ""

    def click(self, **kw):
        if self._items:
            self._page.click_node(self._items[0], self._sel)

    def fill(self, value):
        self._page.fill_node(self, value)

    def input_value(self):
        return self._page.values.get(self._sel, "")

    def press(self, key):
        self._page.presses.append(key)

    def wait_for(self, state=None, timeout=None):
        pass


class FakeListPage:
    """够用的假列表页：多张表 / 冻列碎片 / 行内按钮 / 复选框 / 筛选框 / 查询遮罩。

    rows 每项：
      {"cells": 主表那半边格子, "left": 左冻列那半边（含 ID 与名字）, "buttons": 右冻列那颗按钮,
       "checked": 复选框状态, "box": 这一行的框, "pane": False 表示它在**隐藏页签**的表里}
    真机就是这么拆的：一条记录 = 三份 DOM 行，三份行号相同（见 `list_page` 模块注释）。

    其它开关：
      tabs / menu / pane      页面上的页签、侧边菜单、有没有可见页签
      inputs / hidden_inputs  这个 placeholder 的输入框：有没有可见那份、有没有隐藏副本
      mask_reads              点完「查询」还要转几次圈（0 = 不转圈，None = 一直转）
      buttons                 页面级按钮（默认「查询 / 批量删除」）
      page_buttons            [(文案, 框)] 额外页面级按钮（验坐标兜底用）
    """

    def __init__(self, rows=(), tabs=("博文圈选任务", "分发名单"), pane=True, menu="圈选用户",
                 inputs=(), hidden_inputs=(), mask_reads=0,
                 buttons=("查询", "批量删除"), page_buttons=()):
        self.rows = [dict(r) for r in rows]
        self.tabs = list(tabs)
        self.pane = pane
        self.menu = menu
        self.inputs = list(inputs)
        self.hidden_inputs = list(hidden_inputs)
        self.mask_reads = mask_reads
        self.buttons = list(buttons)
        self.page_buttons = list(page_buttons)
        self.values = {}          # 输入框里的值，按选择器存
        self.clicks = []          # 点过的节点（文案 / 选择器）
        self.fills = []           # (选择器, 值, 那份是不是可见的)
        self.presses = []         # 按过的键
        self.query_clicks = 0
        self.waits = 0

    # ---- 模块会用到的页面 API ----
    def locator(self, sel):
        return LLoc(self, self.resolve(sel), sel)

    def get_by_text(self, text, exact=False):
        hit = [LNode(text=self.menu)] if text in self.menu else []
        return LLoc(self, hit, "text=%s" % text)

    def wait_for_timeout(self, ms):
        self.waits += 1

    def goto(self, url, wait_until=None, timeout=None):
        pass

    # ---- 选择器 → 假节点 ----
    def resolve(self, sel):
        s = sel.strip()
        scoped = ".el-tab-pane:visible" in s
        if s == "body":
            return [LNode(text=self.body_text())]
        if s == ".el-tab-pane:visible":
            return [LNode(text="pane")] if self.pane else []
        if s == ".el-tabs__item":
            return [LNode(text=t) for t in self.tabs]
        if "el-loading-mask" in s:
            if self.mask_reads is None:
                return [LNode(text="mask")]
            if self.mask_reads > 0:
                self.mask_reads -= 1
                return [LNode(text="mask")]
            return []
        if "el-table__fixed-body-wrapper" in s:
            return self.table_parts(scoped)[1]
        if "el-table__body-wrapper" in s:
            return self.table_parts(scoped)[0]
        if ".el-table" in s:
            # 表根：list_page 会按「表根 → 两种表体」取碎片
            body, fixed = self.table_parts(scoped)
            return [LNode(text="table", kinds={
                ".el-table__body-wrapper tbody tr": body,
                ".el-table__fixed-body-wrapper tbody tr": fixed,
            })]
        if "button:visible" in s:
            out = [LNode(text=t) for t in self.buttons]
            out += [LNode(text=t, box=b) for t, b in self.page_buttons]
            return out
        if "input[placeholder=" in s:
            ph = placeholder_of(s) or ""
            out = []
            if ph in self.hidden_inputs:
                out.append(LNode(text="", visible=False))
            if ph in self.inputs:
                out.append(LNode(text=""))
            return out
        return []

    def table_parts(self, scoped):
        """这一页（或可见页签里）的碎片：主表体一份，冻列副本一份。"""
        body, fixed = [], []
        for i, r in enumerate(self.rows):
            if scoped and not r.get("pane", True):
                continue
            one_body, one_fixed = self.fragments(i, r)
            body.extend(one_body)
            fixed.extend(one_fixed)
        return body, fixed

    def fragments(self, i, r):
        """一条记录 → 三份碎片：主表体一份 + 冻列副本两份（三份行号相同）。"""
        box = r.get("box")
        body, fixed = [], []
        if r.get("cells"):
            body.append(LNode(index=i, box=box,
                              kinds={"td": [LNode(text=c) for c in r["cells"]]}))
        if r.get("left"):
            fixed.append(LNode(index=i, box=box,
                               kinds={"td": [LNode(text=c) for c in r["left"]]}))
        kinds = {}
        btns = r.get("buttons") or ()
        if btns:
            kinds["button:visible"] = [LNode(text=b, box=box) for b in btns]
            # 右冻列那一格跟主表**同列对齐**（真机：格子里是「查看\n编辑\n导出\n停止」），
            # 所以往前垫空格子，让按钮文案落在最后那一列
            pad = max(len(r.get("cells") or ()) - 1, 0)
            kinds["td"] = [LNode(text="") for _ in range(pad)] + [LNode(text=" ".join(btns))]
        ckb = LNode(index=i, box=box, checked=bool(r.get("checked")))

        def toggle(node=ckb, spec=r):
            node.checked = not node.checked
            spec["checked"] = node.checked

        ckb.onclick = toggle
        kinds[".el-checkbox"] = [ckb]
        fixed.append(LNode(index=i, box=box, kinds=kinds))
        return body, fixed

    def body_text(self):
        parts = [self.menu] + list(self.tabs)
        for r in self.rows:
            parts.extend(r.get("cells") or ())
            parts.extend(r.get("left") or ())
            parts.extend(r.get("buttons") or ())
        return "\n".join(p for p in parts if p)

    # ---- 点击 / 填值 ----
    def click_node(self, node, sel):
        self.clicks.append(node.text or sel)
        if node.onclick:
            node.onclick()
            return
        if node.text == "查询":
            self.query_clicks += 1
        elif node.text == "批量删除":
            self.rows = [r for r in self.rows if not r.get("checked")]

    def fill_node(self, loc, value):
        self.values[loc._sel] = value
        self.fills.append((loc._sel, value, loc.is_visible()))
