# -*- coding: utf-8 -*-
"""run_distribution 的假页面单测（不开浏览器）。

盯的是 2026-09-23 这次修的坑：`--verify` 原来**不筛选就读整页正文**，而「分发名单」是全系统的
列表、一页 30 条 —— 自己那几条排在后面就被报成「未找到」（实测 5 桶报 3/5，B/C/E 恰好在第一页）。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import sys
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))

import run_distribution  # noqa: E402
from fakes import FakeListPage  # noqa: E402

PH_LIST_FILTER = run_distribution.PH_LIST_FILTER
NAME_A = "火山引擎MediaKit-hang-A类 · AI 编程 / Agent 工具"
NAME_B = "火山引擎MediaKit-hang-B类 · FFmpeg / 命令行音视频"
BUCKET_A = "火山引擎MediaKit-hang-A类"
BUCKET_C = "火山引擎MediaKit-hang-C类"


def mklist(name):
    """一条分发名单记录（主表体 + 冻列副本两份碎片）。"""
    return {"pane": True, "buttons": [], "box": (0, 100, 800, 40),
            "cells": ["", "206853", name],
            "left": ["", "206853", name]}


class VerifyListsTest(unittest.TestCase):
    def _run(self, items, prefix="火山引擎MediaKit-hang"):
        # mask_reads=1：让「查询」走"遮罩转了圈就等它转完"那条路，测试不用真等 2200ms 的底
        page = FakeListPage(rows=[mklist(NAME_A), mklist(NAME_B)], inputs=[PH_LIST_FILTER],
                            mask_reads=1)
        logs = []
        with mock.patch.object(run_distribution.ui, "log", logs.append):
            run_distribution.verify_lists(types.SimpleNamespace(page=page), items, prefix=prefix)
        return page, logs

    def test_先按活动前缀筛选再读(self):
        page, logs = self._run([(None, NAME_A, BUCKET_A)])
        self.assertEqual(page.values["input[placeholder='%s']" % PH_LIST_FILTER],
                         "火山引擎MediaKit-hang", "不筛选就只能看到全系统列表的第 1 页")
        self.assertGreaterEqual(page.query_clicks, 1, "填了筛选必须点查询，否则读到的还是旧列表")
        self.assertTrue(any("筛选前缀" in x for x in logs), "日志要说清这次筛了什么")

    def test_在列表里的报已建_不在的报未找到(self):
        _, logs = self._run([(None, NAME_A, BUCKET_A), (None, "别的名单", BUCKET_C)])
        self.assertTrue(any(BUCKET_A in x and "已建" in x for x in logs))
        self.assertTrue(any(BUCKET_C in x and "未找到" in x for x in logs))

    def test_没给前缀时照旧不筛(self):
        page, _ = self._run([(None, NAME_A, BUCKET_A)], prefix="")
        self.assertEqual(page.values, {}, "没有前缀就不动筛选框")


if __name__ == "__main__":
    unittest.main()
