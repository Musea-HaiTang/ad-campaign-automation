# -*- coding: utf-8 -*-
"""list_page（后台列表页共用层）的单测：假页面，不开浏览器。

覆盖的判据都是真事故换来的：
  - 隐藏页签的表**不算数**（2026-09-22 因此把 5 个已建名单全报成未找到）；
  - 筛选框要挑**可见**那份（后台固定列会渲染隐藏副本）；
  - 按名字取行**只认全等**（`…-4` 会抢同前缀的 `…`，`csdn_ui._pick_option` 踩过一次）；
  - 空表要判「未就绪」而不是「没有」（超时返回 False，不抛错）；
  - 行内按钮：结构定位优先，摸不到时按同排按钮兜底（冻列克隆节点里按钮文案是空的）。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))

import list_page  # noqa: E402
from fakes import FakeListPage  # noqa: E402

PH_NAME = "请输入圈选任务名称"
PANE = list_page.TAB_PANE

# 主表那半边的行形状（真机 2026-09-21）：前 3 列空着，日期从第 4 列起，最后一列留给右冻列
MAIN_CELLS = ["", "", "", "2026-09-21 09:44:09", "12370", "62.61", "7757.27", "37576.92",
              "视频剪辑,混剪", ""]


def mkrow(name, rid="141", pane=True, checked=False, buttons=("查看", "停止"),
          box=(0, 100, 800, 40)):
    """一条记录 = 三份碎片，列号要对齐（对不齐就合并错，见 `list_page.merge_cells`）。"""
    return {"pane": pane, "checked": checked, "buttons": list(buttons), "box": box,
            "cells": list(MAIN_CELLS),
            "left": ["", rid, name] + [""] * (len(MAIN_CELLS) - 3)}


def open_lp(page):
    return list_page.open_list(page, menu="圈选用户", tab="博文圈选任务", wait_input=PH_NAME)


class OpenListTest(unittest.TestCase):
    def test_点菜单切页签_等筛选框出现才算翻开(self):
        page = FakeListPage(inputs=[PH_NAME])
        lp = open_lp(page)
        self.assertEqual(page.clicks, ["圈选用户", "博文圈选任务"])
        self.assertEqual(lp.scope, PANE, "有可见页签就该限定在页签里")

    def test_没有可见页签时作用域是整页(self):
        page = FakeListPage(inputs=[PH_NAME], pane=False)
        self.assertEqual(open_lp(page).scope, "")

    def test_找不到筛选框_当场报错(self):
        page = FakeListPage(inputs=[])        # 这一页没有那个筛选框
        with mock.patch.object(list_page, "T_WAIT", 0.05):
            with self.assertRaises(RuntimeError):
                open_lp(page)

    def test_没登录_菜单都找不到_当场报错(self):
        page = FakeListPage(inputs=[PH_NAME], menu="别的菜单")
        with mock.patch.object(list_page, "T_WAIT", 0.05):
            with self.assertRaises(RuntimeError):
                open_lp(page)


class FilterTest(unittest.TestCase):
    def test_只填不查_并跳过后台那份隐藏输入框(self):
        page = FakeListPage(inputs=[PH_NAME], hidden_inputs=[PH_NAME])
        lp = open_lp(page)
        missed = lp.filter({PH_NAME: "火山引擎MediaKit-hang", "开始日期": "2020-01-01"},
                           enter=PH_NAME)
        self.assertEqual(page.values["input[placeholder='%s']" % PH_NAME], "火山引擎MediaKit-hang")
        self.assertTrue(page.fills[0][2], "应该填在可见那份上")
        self.assertEqual(missed, ["开始日期"], "页面上没有的筛选框要报出来")
        self.assertEqual(page.query_clicks, 0, "filter 只填，点查询是 query 的事")
        self.assertEqual(page.presses, ["Enter"], "只有说了要回车的字段才按回车")


class RowsTest(unittest.TestCase):
    def test_三份冻列碎片按行号合并成一行(self):
        page = FakeListPage(rows=[mkrow("A类 · 测试")], inputs=[PH_NAME])
        row = open_lp(page).rows()[0]
        self.assertIn("A类 · 测试", row.cells, "左冻列那份（名字）")
        self.assertIn("12370", row.cells, "主表那份（数字）")
        self.assertIn("停止", row.text(), "右冻列那份（按钮）")
        self.assertEqual(row.id, "141", "ID 取第一个纯数字格子")

    def test_隐藏页签里的行不算数(self):
        page = FakeListPage(rows=[mkrow("A类 · 测试"), mkrow("X类 · 别的", pane=False)],
                            inputs=[PH_NAME])
        lp = open_lp(page)
        self.assertEqual(len(lp.rows()), 1)
        self.assertIsNone(lp.row_by_name("X类 · 别的", timeout=0),
                          "隐藏页签的行不能被当成这一页的行")

    def test_按名字取行只认全等_同前缀的抢不走(self):
        page = FakeListPage(rows=[mkrow("A类 · AI 编程 / Agent 工具-4", rid="142"),
                                  mkrow("A类 · AI 编程 / Agent 工具", rid="141")],
                            inputs=[PH_NAME])
        lp = open_lp(page)
        row = lp.row_by_name("A类 · AI 编程 / Agent 工具")
        self.assertEqual(row.id, "141")
        self.assertEqual(row.name, "A类 · AI 编程 / Agent 工具")
        self.assertIsNone(lp.row_by_name("A类", timeout=0), "前缀不算命中")

    def test_row_containing_认名字带后缀的那种行(self):
        page = FakeListPage(rows=[mkrow("火山引擎MediaKit-hang-A类 · AI 编程 / Agent 工具")],
                            inputs=[PH_NAME])
        lp = open_lp(page)
        self.assertIsNotNone(lp.row_containing("火山引擎MediaKit-hang-A类"))
        self.assertIsNone(lp.row_by_name("火山引擎MediaKit-hang-A类", timeout=0))


class QueryTest(unittest.TestCase):
    def test_查询_表出数据返回True(self):
        page = FakeListPage(rows=[mkrow("A类 · 测试")], inputs=[PH_NAME])
        lp = open_lp(page)
        with mock.patch.object(list_page, "T_ROWS", 0.05):
            self.assertTrue(lp.query(wait_ms=0))
        self.assertEqual(page.query_clicks, 1)

    def test_空表_等满上限返回False且不抛错(self):
        page = FakeListPage(rows=[], inputs=[PH_NAME])
        lp = open_lp(page)
        with mock.patch.object(list_page, "T_ROWS", 0.05):
            self.assertFalse(lp.query(wait_ms=0))
        self.assertEqual(lp.rows(), [])


class RowActionTest(unittest.TestCase):
    def test_点行内按钮_结构定位优先(self):
        page = FakeListPage(rows=[mkrow("A类 · 测试")], inputs=[PH_NAME])
        row = open_lp(page).row_by_name("A类 · 测试")
        self.assertTrue(row.button("停止"))
        self.assertIn("停止", page.clicks)

    def test_冻列里按钮文案为空时_按同排按钮兜底(self):
        page = FakeListPage(rows=[mkrow("A类 · 测试", buttons=())], inputs=[PH_NAME],
                            page_buttons=[("一键创建分发名单", (300, 100, 120, 30))])
        row = open_lp(page).row_by_name("A类 · 测试")
        self.assertTrue(row.button("一键创建分发名单"))
        self.assertIn("一键创建分发名单", page.clicks)

    def test_同排没有那个按钮_就不点(self):
        page = FakeListPage(rows=[mkrow("A类 · 测试", buttons=())], inputs=[PH_NAME],
                            page_buttons=[("一键创建分发名单", (300, 400, 120, 30))])
        row = open_lp(page).row_by_name("A类 · 测试")
        self.assertFalse(row.button("一键创建分发名单"))
        self.assertNotIn("一键创建分发名单", page.clicks, "不在同一排就别乱点")

    def test_勾选复选框并回读勾没勾上(self):
        page = FakeListPage(rows=[mkrow("A类 · 测试")], inputs=[PH_NAME])
        row = open_lp(page).row_by_name("A类 · 测试")
        self.assertFalse(row.checked)
        self.assertTrue(row.checkbox())
        self.assertTrue(row.checked, "勾上之后再读就该是勾上的")


if __name__ == "__main__":
    unittest.main()
