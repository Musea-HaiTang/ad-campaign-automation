# -*- coding: utf-8 -*-
"""圈选达标读数/判定/轮询的单测（纯函数 + 假页面，不开浏览器）。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
sys.path.insert(0, str(ROOT / "scripts"))

import audience_metrics as am  # noqa: E402
import list_page  # noqa: E402
from fakes import FakeListPage  # noqa: E402

GOOD = {"A类 · 测试": {"id": "1", "blogs": 57023.0, "click": 183.29,
                       "exposure": 23176.98, "pv": 100.0}}
PENDING = {"A类 · 测试": {"id": "1", "blogs": None, "click": None,
                          "exposure": None, "pv": None}}


class ParseTest(unittest.TestCase):
    """真机 2026-09-21 的行形状：一条记录被拆成三份 DOM 行。"""

    def test_完整行(self):
        cells = ["", "141", "测试2", "2026-09-21 09:44:28", "300000", "47.75", "5130.34",
                 "51907.29", "视频剪辑,混剪", "", "creator01", "一键创建分发名单",
                 "查看 编辑 导出 停止"]
        self.assertEqual(am.row_metrics(cells),
                         ("141", "测试2", 300000.0, 47.75, 5130.34, 51907.29))

    def test_一行拆三份_合并后才认得出(self):
        main = ["", "", "", "2026-09-21 09:44:09", "12370", "62.61", "7757.27", "37576.92",
                "视频剪辑,混剪", "", "lihang1", "", ""]
        left = ["", "140", "测试1", "", "", "", "", "", "", "", "", "", ""]
        right = ["", "", "", "", "", "", "", "", "", "", "", "一键创建分发名单",
                 "查看\n编辑\n导出\n停止"]
        self.assertIsNone(am.row_metrics(main))       # 单看主表：没有 ID/名称
        self.assertEqual(am.row_metrics(list_page.merge_cells(main, left, right)),
                         ("140", "测试1", 12370.0, 62.61, 7757.27, 37576.92))

    def test_合并时已有值不被空值覆盖(self):
        self.assertEqual(list_page.merge_cells(["a", "", "c"], ["x", "y", "", "z"]),
                         ["a", "y", "c", "z"])

    def test_数字还没刷出来_值为_None(self):
        # 后台还在算：四个数格是空 → 判「待后台」，不当 0
        cells = ["", "9", "A类 · 测试", "2026-09-21 09:44:28", "", "", "", "", "词"]
        self.assertEqual(am.row_metrics(cells), ("9", "A类 · 测试", None, None, None, None))


class VerdictTest(unittest.TestCase):
    def test_按当期口径_2万目标_1万底线(self):
        v = am.verdict
        self.assertEqual(v(25000), (am.OK, True))
        self.assertEqual(v(20000), (am.OK, True))
        self.assertEqual(v(19999.99), (am.NEAR, False))
        self.assertEqual(v(10000), (am.NEAR, False))
        self.assertEqual(v(9999), (am.LOW, False))
        self.assertEqual(v(None), (am.PENDING, None))

    def test_口径可改(self):
        self.assertEqual(am.verdict(45000, 50000, 40000), (am.NEAR, False))
        self.assertEqual(am.verdict(30000, 50000, 40000), (am.LOW, False))

    def test_数字格式化_整数不带小数点(self):
        self.assertEqual(am.fmt(300000.0), "300000")
        self.assertEqual(am.fmt(5130.34), "5130.34")
        self.assertEqual(am.fmt(None), "—")


class DeleteTasksTest(unittest.TestCase):
    """删圈选任务：停止 → 勾选 → 批量删除 → 回读确认（假列表页，不开浏览器）。"""

    PH = am.PH_TASK_NAME
    NAME = "火山引擎MediaKit-hang-A类 · AI 编程 / Agent 工具"

    def _lp(self, checked=False):
        page = FakeListPage(inputs=[self.PH], rows=[{
            "pane": True, "checked": checked, "box": (0, 100, 800, 40),
            "buttons": ["查看", "停止"],
            "cells": ["", "", "", "2026-09-21 09:44:09", "12370", "", "", "", ""],
            "left": ["", "141", self.NAME],
        }])
        return list_page.open_list(page, menu="圈选用户", tab="博文圈选任务",
                                   wait_input=self.PH), page

    def test_停止_勾选_批量删除_回读确认(self):
        lp, page = self._lp()
        logs = []
        gone = am.delete_tasks(lp, [self.NAME], log=logs.append, wait_ms=0)
        self.assertEqual(gone, [self.NAME], "只算**真的从列表里消失**的那些")
        self.assertIn("停止", page.clicks, "先点这一行的「停止」")
        self.assertIn("批量删除", page.clicks)
        self.assertTrue(any("id=141" in x for x in logs), "日志要带上这一行的 ID")
        self.assertEqual(lp.rows(), [], "删完列表里就不该再有它")

    def test_列表里没有这个名字_不点批量删除(self):
        lp, page = self._lp()
        gone = am.delete_tasks(lp, ["不存在的名字"], log=lambda *a: None, wait_ms=0)
        self.assertEqual(gone, [])
        self.assertNotIn("批量删除", page.clicks, "一个都没勾上就不许点批量删除")


class WaitReadyTest(unittest.TestCase):
    """轮询：每 interval 点一次查询，出数就停，到上限收手（假页面 + 假时钟）。"""

    def _run(self, snaps, timeout_s=60, interval_s=10):
        seq = list(snaps)
        state = {"t": 0.0, "queries": 0, "filters": 0}

        class FakeLP:
            """假把手：轮询只用到它的 query()。"""

            def query(self, *a, **k):
                state["queries"] += 1

        def fake_read(_lp):
            return seq.pop(0) if seq else {}

        def fake_filters(*a, **k):
            state["filters"] += 1

        def fake_sleep(s):
            state["t"] += s

        logs = []
        originals = (am.read_metrics, am.apply_filters)
        am.read_metrics, am.apply_filters = fake_read, fake_filters
        try:
            got = am.wait_ready(FakeLP(), ["A类 · 测试"], timeout_s=timeout_s,
                                interval_s=interval_s, log=logs.append,
                                sleep=fake_sleep, clock=lambda: state["t"])
        finally:
            am.read_metrics, am.apply_filters = originals
        return got, state, logs

    def test_出数就停(self):
        got, state, logs = self._run([PENDING, PENDING, GOOD])
        self.assertEqual(got["A类 · 测试"]["exposure"], 23176.98)
        self.assertEqual(state["queries"], 3)          # 查到出数为止，不多点
        self.assertEqual(state["t"], 20)               # 中间只等了 2 次 10 秒
        self.assertTrue(any("第 3 次查询" in x for x in logs))

    def test_到上限收手_不当成达标(self):
        got, state, logs = self._run([PENDING] * 20)
        self.assertIsNone(got["A类 · 测试"]["exposure"])
        self.assertEqual(state["queries"], 7)          # 0,10,...60 秒 → 第 7 次时到点
        self.assertLessEqual(state["t"], 60)
        self.assertTrue(any("等到上限" in x for x in logs))

    def test_列表整片空了就重填筛选(self):
        got, state, logs = self._run([{}, PENDING, GOOD])
        self.assertEqual(got["A类 · 测试"]["exposure"], 23176.98)
        self.assertEqual(state["filters"], 1)          # 空那次之后重填


if __name__ == "__main__":
    unittest.main()
