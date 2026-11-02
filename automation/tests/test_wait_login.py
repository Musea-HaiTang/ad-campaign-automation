# -*- coding: utf-8 -*-
"""wait_login 两个站的探测口径单测（假页面，不开浏览器）。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
sys.path.insert(0, str(ROOT / "scripts"))

import wait_login as wl  # noqa: E402


class _Locator:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class _Page:
    """假页面：goto 后把 url 换成给定值（模拟被重定向到 /login）。"""

    def __init__(self, url, composer_count):
        self.url = url
        self._target = url
        self._composer = composer_count
        self.visited = []

    def goto(self, url, **kw):
        self.visited.append(url)
        self.url = self._target

    def wait_for_timeout(self, ms):
        return None

    def locator(self, sel):
        return _Locator(self._composer)


class ProbeDatabiTest(unittest.TestCase):
    def test_对话页有输入框算已登录(self):
        page = _Page("https://data.csdn.net/chat", 1)
        ok, why = wl.probe_databi(page)
        self.assertTrue(ok, why)
        self.assertEqual(page.visited, [wl.DATABI_URL])

    def test_被踢到login算未登录(self):
        page = _Page("https://data.csdn.net/login", 0)
        ok, why = wl.probe_databi(page)
        self.assertFalse(ok)
        self.assertIn("/login", why)

    def test_登录后停在projects也算成功(self):
        page = _Page("https://data.csdn.net/projects", 0)
        ok, why = wl.probe_databi(page, navigate=False)
        self.assertTrue(ok, why)

    def test_对话页没有输入框仍算未就绪(self):
        page = _Page("https://data.csdn.net/chat", 0)
        ok, why = wl.probe_databi(page, navigate=False)
        self.assertFalse(ok, why)

    def test_检查当前页时不刷新用户表单(self):
        page = _Page("https://data.csdn.net/login", 0)
        ok, _ = wl.probe_databi(page, navigate=False)
        self.assertFalse(ok)
        self.assertEqual(page.visited, [])

    def test_两个站各有默认页(self):
        self.assertIn("mp-admin.csdn.net", wl.DEFAULT_URL)
        self.assertIn("data.csdn.net", wl.DATABI_URL)


class ProbeAdminTest(unittest.TestCase):
    class _Page:
        def __init__(self, identity):
            self.identity = identity

        def evaluate(self, js):
            return self.identity

    def test_有身份信息才算登录完成(self):
        page = self._Page({
            "userName": "sample-user", "hasToken": True, "hasUser": True,
            "url": "https://mp-admin.csdn.net/",
        })
        ok, why = wl.probe_admin(page)
        self.assertTrue(ok)
        self.assertIn("sample-user", why)

    def test_旧会话但无用户名不算登录完成(self):
        page = self._Page({
            "userName": "", "hasToken": False, "hasUser": False,
            "url": "https://mp-admin.csdn.net/",
        })
        ok, why = wl.probe_admin(page)
        self.assertFalse(ok)
        self.assertIn("userName=''", why)


if __name__ == "__main__":
    unittest.main()
