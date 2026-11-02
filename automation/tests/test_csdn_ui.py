# -*- coding: utf-8 -*-
"""csdn_ui 的「假柜台」单测：不开真浏览器，直接喂一个假 page。

假页面本身在 `fakes.py`（列表页层的假页面也在那儿，两边共用）。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import os
import pathlib
import shutil
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))

import csdn_ui  # noqa: E402
from fakes import FakeExpect, FakePage, QueryPage, TablePage, TwoCopyPage  # noqa: E402


class CsdnUiTest(unittest.TestCase):
    def setUp(self):
        self._patches = [
            mock.patch.object(csdn_ui, "expect", FakeExpect),
            mock.patch.object(csdn_ui, "POLL_SECONDS", 0.05),  # 别真等 6 秒
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _session(self, page, dry_run=True, shot_dir=""):
        return csdn_ui.Session(page, dry_run, shot_dir)

    # ---- 下拉选择 ----
    def test_select_点中同名选项并等浮层收起(self):
        page = FakePage(options=["华为云码道hang"])
        s = self._session(page)
        box = page.locator("input[placeholder='请选择任务组']")

        csdn_ui.select(s, box, "华为云码道hang")

        self.assertEqual(page.clicked, ["华为云码道hang"])
        self.assertFalse(page.dropdown_open, "选完之后下拉应收起")

    def test_select_找不到时报错并列出看到的选项(self):
        page = FakePage(options=["别的组A", "别的组B"])
        s = self._session(page)
        box = page.locator("input[placeholder='请选择任务组']")

        with self.assertRaises(RuntimeError) as ctx:
            csdn_ui.select(s, box, "想选的组")

        msg = str(ctx.exception)
        self.assertIn("想选的组", msg)
        self.assertIn("别的组A", msg, "报错要带上实际看到的选项")
        self.assertGreaterEqual(page.waits, 1, "选项异步加载，应该重试过而不是只找一圈")

    def test_下拉点不动时改点外层容器(self):
        """readonly 输入框被 .el-select__tags 盖住时，普通点击会被拦；
        共用层应该退回去点外层 .el-select 容器（工单的「用户名单」就是这个坑）。"""
        page = FakePage(options=["华为码道分发名单社区运营分组_17 用户名"])
        page.blocked = {csdn_ui.PH_DIST_LIST}
        s = self._session(page)
        box = page.locator("input[placeholder='%s']" % csdn_ui.PH_DIST_LIST)
        # 先确认直接点真的会被拦
        with self.assertRaises(RuntimeError):
            box.click()

        csdn_ui.search_select(s, box, "华为码道分发名单社区运营分组_17 用户名")

        self.assertEqual(page.wrap_clicks, 1, "应该退回去点了 1 次外层容器")
        self.assertEqual(page.clicked, ["华为码道分发名单社区运营分组_17 用户名"])

    def test_选项文本带后缀时_去掉最后一个词再搜(self):
        """实测：用户名单显示成「xxx_17 用户名」，但后台检索只认「xxx_17」。
        拿带后缀的原值去搜，后台返回 0 项。"""
        shown = "华为码道分发名单社区运营分组_17 用户名"
        page = FakePage(options=[shown])
        page.real_names = {shown: "华为码道分发名单社区运营分组_17"}
        s = self._session(page)
        box = page.locator("input[placeholder='%s']" % csdn_ui.PH_DIST_LIST)

        csdn_ui.search_select(s, box, shown)

        self.assertEqual(page.clicked, [shown])
        self.assertEqual(page.search_text, "华为码道分发名单社区运营分组_17", "应该退回用去掉后缀的词搜")

    def test_选项文本带系统后缀时按前缀认(self):
        """后台用真名能搜到，但选项文本带系统加的「 用户名」后缀；
        配置里存的是真名，所以不能用全等匹配（实测踩过）。"""
        shown = "鸿蒙稿事节征文短信（万粉以上） 用户名"
        real = "鸿蒙稿事节征文短信（万粉以上）"
        page = FakePage(options=[shown])
        page.real_names = {shown: real}
        s = self._session(page)
        box = page.locator("input[placeholder='%s']" % csdn_ui.PH_DIST_LIST)

        csdn_ui.search_select(s, box, real)

        self.assertEqual(page.clicked, [shown], "应该点中带后缀的那一项")

    # ---- 弹窗清场 ----
    def test_清弹窗_没有弹窗时什么都不做(self):
        """每个桶都会调一次清场；没有残留弹窗时不该按 Escape、也不该白等 400ms。"""
        page = FakePage(dialogs=0)
        csdn_ui.dismiss_dialogs(page)
        self.assertEqual(page.keyboard.presses, [])
        self.assertEqual(page.waits, 0)

    def test_清弹窗_esc能关就只按esc(self):
        page = FakePage(dialogs=1, dialog_closes_on_esc=True)
        csdn_ui.dismiss_dialogs(page)
        self.assertEqual(page.keyboard.presses, ["Escape"])
        self.assertEqual(page.dialog_close_clicks, 0)

    def test_清弹窗_esc关不掉时点关闭按钮(self):
        page = FakePage(dialogs=1, dialog_closes_on_esc=False)
        csdn_ui.dismiss_dialogs(page)
        self.assertEqual(len(page.keyboard.presses), 4, "先按满 4 次 Escape 再兜底")
        self.assertEqual(page.dialog_close_clicks, 1)
        self.assertEqual(page.dialogs, 0)

    # ---- 截图：只有彩排才拍 ----
    def test_彩排才截图(self):
        # automation/_tmp/ 已在 .gitignore 里，测试产物不会进仓库
        d = ROOT / "_tmp" / "test_shots"
        shutil.rmtree(d, ignore_errors=True)
        try:
            page = FakePage()
            path = csdn_ui.shot(self._session(page, dry_run=True, shot_dir=str(d)), "a.png")
            self.assertTrue(path and os.path.exists(path))
            self.assertEqual(page.screenshots, [path])

            page2 = FakePage()
            self.assertIsNone(csdn_ui.shot(self._session(page2, dry_run=False), "a.png"))
            self.assertEqual(page2.screenshots, [], "正式跑不该截图")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # ---- 字段回读 ----
    def test_回读字段_文本域也能读(self):
        page = FakePage()
        page.values["textarea[placeholder='请输入广告摘要']"] = "多行摘要"
        self.assertEqual(csdn_ui.read_field(page, "请输入广告摘要"), "多行摘要")
        self.assertEqual(csdn_ui.read_field(page, "不存在的字段"), "")

    # ---- 穿梭框 ----
    def test_穿梭框_勾选并移到右侧(self):
        page = FakePage()
        s = self._session(page)
        csdn_ui.transfer(s, page, "PC博客详情页-新模版-T0")
        self.assertTrue(page.transfer_checked, "左侧应勾上")
        self.assertTrue(page.transfer_moved, "应移到右侧")


class WaitHelpersTest(unittest.TestCase):
    """条件等待原语（2026-09-22 加：取代各脚本里的固定死等）。"""

    def test_等条件成立_成立就立刻返回_不白等(self):
        page = FakePage()
        self.assertTrue(csdn_ui.wait_for(page, lambda: True, timeout=5, what="随便什么"))
        self.assertEqual(page.waits, 0, "条件已经成立就不该再等")

    def test_等条件超时_返回False不抛错(self):
        page = FakePage()
        self.assertFalse(csdn_ui.wait_for(page, lambda: False, timeout=0.05, interval=0.01,
                                          what="永远不会好的东西"))
        self.assertGreaterEqual(page.waits, 1, "超时前应该轮询过，而不是只看一眼")

    def test_条件里抛异常_当作还没好继续等(self):
        page = FakePage()
        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] < 3:
                raise RuntimeError("元素正在重渲染")
            return True

        self.assertTrue(csdn_ui.wait_for(page, flaky, timeout=1, interval=0.01, what="闪断的元素"))

    def test_只认可见那份输入框_隐藏副本跳过(self):
        page = TwoCopyPage()
        el = csdn_ui.visible_input(page, "dup-field")
        self.assertIsNotNone(el)
        self.assertTrue(el.is_visible(), "应该跳过 0×0 的隐藏副本")
        self.assertTrue(csdn_ui.fill_visible(page, "dup-field", "筛这个"))
        self.assertEqual(page.values["input[placeholder='dup-field']"], "筛这个")

    def test_没有可见输入框时_返回空而不是报错(self):
        page = FakePage()
        self.assertIsNone(csdn_ui.visible_input(page, "页面上没有这个框"))
        self.assertFalse(csdn_ui.fill_visible(page, "页面上没有这个框", "x"))

    def test_表格有没有数据行(self):
        """读正文前用它兜一下：筛选框比表格行先渲染（2026-09-22 踩到过误判）。"""
        self.assertFalse(csdn_ui.table_has_rows(TablePage(rows=0)))
        self.assertTrue(csdn_ui.table_has_rows(TablePage(rows=3)))

    def test_查询_转圈了就等遮罩消失再走(self):
        page = QueryPage(mask_reads=2)
        # 固定底给 5 秒：只有在"遮罩出现→消失"时提前返回，才可能这么快走完
        t0 = time.time()
        self.assertTrue(csdn_ui.click_query(page, floor_ms=5000, timeout=5))
        self.assertEqual(page.query_clicks, 1)
        self.assertLess(time.time() - t0, 2, "遮罩消失就该走，不该把 5 秒的底等满")

    def test_查询_没看到遮罩就守住固定底(self):
        page = QueryPage(mask_reads=0)
        t0 = time.time()
        self.assertTrue(csdn_ui.click_query(page, floor_ms=300, timeout=5))
        self.assertGreaterEqual(time.time() - t0, 0.25,
                                "没转圈的查询必须守住原来的固定底，不能读上一次查询的旧数据")

    def test_查询_超时返回False(self):
        page = QueryPage(mask_reads=None)   # 遮罩永远不退
        self.assertFalse(csdn_ui.click_query(page, floor_ms=1, timeout=0.3))

    def test_藏着不放的遮罩不算数_按底收尾不误报(self):
        """真机 2026-09-23：加载完遮罩元素留在 DOM 里、只是 display:none。

        原来数元素个数会永远判成"还在转圈"→ 每个查询白等 3 秒 + 误报"数可能是旧的"。
        """
        page = QueryPage(mask_visible=False)
        logs = []
        with mock.patch.object(csdn_ui, "log", logs.append):
            t0 = time.time()
            self.assertTrue(csdn_ui.click_query(page, floor_ms=300, timeout=5))
        self.assertLess(time.time() - t0, 1.0, "不该等满 3 秒那个兜底")
        self.assertFalse(any("遮罩" in x for x in logs), "更不该报「遮罩一直没退」")

    def test_遮罩一直看得见_等到上限并说清数可能是旧的(self):
        page = QueryPage(mask_reads=None)
        logs = []
        with mock.patch.object(csdn_ui, "log", logs.append):
            t0 = time.time()
            self.assertFalse(csdn_ui.click_query(page, floor_ms=1, timeout=0.4))
        self.assertGreaterEqual(time.time() - t0, 0.35, "看得见的遮罩要等到上限，别提前收手")
        self.assertTrue(any("可能是旧的" in x for x in logs), "要留下「这次数可能是旧的」的说明")


class WriteLockTest(unittest.TestCase):
    """真办事（--submit）那把写锁：同一时刻只许一个脚本往后台建东西。"""

    def test_第二个写锁被拦下来(self):
        with csdn_ui._write_lock():
            with self.assertRaises(RuntimeError):
                with csdn_ui._write_lock():
                    pass
        with csdn_ui._write_lock():          # 松手后还能再拿
            pass


class LoginIdentityTest(unittest.TestCase):
    class Page:
        def __init__(self, data):
            self.data = data

        def evaluate(self, js):
            return self.data

        def wait_for_timeout(self, ms):
            pass

    def test_身份齐全时返回当前用户名(self):
        page = self.Page({
            "userName": "sample-user", "hasToken": True, "hasUser": True,
            "url": "https://mp-admin.csdn.net/",
        })
        self.assertEqual(csdn_ui.require_login_identity(page, timeout=0.01), "sample-user")

    def test_只有旧会话没有用户名时拒绝执行(self):
        page = self.Page({
            "userName": "", "hasToken": False, "hasUser": False,
            "url": "https://mp-admin.csdn.net/",
        })
        with self.assertRaises(RuntimeError) as ctx:
            csdn_ui.require_login_identity(page, timeout=0.01)
        self.assertIn("登录身份不完整", str(ctx.exception))
        self.assertIn("wait_login.py", str(ctx.exception))


class BrowserRecoveryTest(unittest.TestCase):
    def test_恢复页面时重启公共浏览器(self):
        page = mock.Mock()
        fresh = object()
        s = SimpleNamespace(page=page, playwright=object(), headed=False)
        with mock.patch.object(csdn_ui.broker, "stop") as stop, \
                mock.patch.object(csdn_ui, "open_healthy_page", return_value=fresh) as opened:
            csdn_ui.recover(s)

        stop.assert_called_once_with()
        opened.assert_called_once_with(s.playwright, headed=False)
        self.assertIs(s.page, fresh)

    def test_目标页导航超时后直接重启浏览器再重试(self):
        s = SimpleNamespace(page=mock.Mock(), playwright=object(), headed=False)
        action = mock.Mock(side_effect=[
            RuntimeError("Page.goto: Timeout 25000ms exceeded"),
            "ok",
        ])
        with mock.patch.object(csdn_ui, "recover") as recover:
            result = csdn_ui.retry_browser_action(s, action, what="资源列表准备")

        self.assertEqual(result, "ok")
        self.assertEqual(action.call_count, 2)
        recover.assert_called_once_with(s)


if __name__ == "__main__":
    unittest.main()
