# -*- coding: utf-8 -*-
"""run_audience 的「提交前闸门」单测（假页面，不开浏览器）。

⛔ 闸门规矩（2026-09-22 加，跟 run_taskorder 同一套）：字段校验没过**就不提交**。
以前正式路径不看 `ok`，照样点「确定」——而事后的回读只查"任务名在不在列表里"，
查不出字段缺失（名字对、子业务线没绑上这种事它发现不了）。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
sys.path.insert(0, str(ROOT / "scripts"))

import run_audience  # noqa: E402


# ---------- 假 locator / 假页面（只够 submit_or_cancel 用） ----------
class _Loc:
    """假 locator：记录被点过的按钮文案（按 `filter(has_text=…)` 认按钮名）。"""

    def __init__(self, clicks, text=""):
        self._clicks = clicks
        self._text = text

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def filter(self, has_text=None, **kw):
        return _Loc(self._clicks, has_text or self._text)

    def count(self):
        return 1

    def click(self, **kw):
        self._clicks.append(self._text)


class _Empty:
    """什么都没匹配到的假 locator（用来证明"页面上没有弹窗"）。"""

    def count(self):
        return 0

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def filter(self, **kw):
        return self

    def all_inner_texts(self):
        return []

    def click(self, **kw):
        raise AssertionError("没有弹窗时不该点任何东西")


class _Keyboard:
    def press(self, key):
        raise AssertionError("没有弹窗时不该按键盘：%s" % key)


class _Page:
    def __init__(self):
        self.keyboard = _Keyboard()

    def locator(self, sel):
        return _Empty()

    def wait_for_timeout(self, ms):
        pass


class _Session:
    def __init__(self, dry_run):
        self.page = _Page()
        self.dry_run = dry_run


class _Confirm:
    """假确认弹窗：记录被点过的按钮。"""

    def __init__(self):
        self.clicks = []

    def locator(self, sel):
        return _Loc(self.clicks)


class _FakeExpect:
    def __init__(self, target):
        self._t = target

    def to_be_visible(self, timeout=None):
        return True

    def to_be_hidden(self, timeout=None):
        return True


class SubmitGateTest(unittest.TestCase):
    def test_字段校验没过_正式跑不提交(self):
        cd = _Confirm()
        self.assertFalse(run_audience.submit_or_cancel(_Session(dry_run=False), cd, ok=False))
        self.assertEqual(cd.clicks, ["取消"], "校验没过就只能点取消，绝不能点「确定」")

    def test_字段校验过了_正式跑才点确定(self):
        cd = _Confirm()
        with mock.patch.object(run_audience, "expect", _FakeExpect):
            self.assertTrue(run_audience.submit_or_cancel(_Session(dry_run=False), cd, ok=True))
        self.assertEqual(cd.clicks, ["确定"])

    def test_彩排_不管校验结果都不提交(self):
        cd = _Confirm()
        self.assertTrue(run_audience.submit_or_cancel(_Session(dry_run=True), cd, ok=False))
        self.assertEqual(cd.clicks, ["取消"])


if __name__ == "__main__":
    unittest.main()
