# -*- coding: utf-8 -*-
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

from _temp import temp_workdir


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import doctor  # noqa: E402


class DoctorTest(unittest.TestCase):
    def test_解析端口监听进程(self):
        text = """
  TCP    127.0.0.1:8770         0.0.0.0:0              LISTENING       1234
  TCP    127.0.0.1:8771         0.0.0.0:0              LISTENING       5678
  TCP    [::1]:9222             [::]:0                 LISTENING       9999
"""
        self.assertEqual(doctor.parse_listener_pids(text, 8770), [1234])
        self.assertEqual(doctor.parse_listener_pids(text, 9222), [9999])
        self.assertEqual(doctor.parse_listener_pids(text, 8772), [])

    def test_识别项目看板进程(self):
        info = {
            "CommandLine": (
                '"D:\\repo\\.venv\\Scripts\\pythonw.exe" -u app.py '
                '--db "D:\\repo\\activities\\_db\\投放数据.db"'
            )
        }
        old_repo = doctor.REPO
        try:
            doctor.REPO = Path(r"D:\repo")
            self.assertTrue(doctor.is_project_port_owner(8770, info))
        finally:
            doctor.REPO = old_repo

    def test_识别项目公共浏览器进程(self):
        info = {
            "CommandLine": (
                '"msedge.exe" --user-data-dir="D:\\repo\\.browser-profile" '
                "--remote-debugging-port=9222"
            )
        }
        old_repo = doctor.REPO
        try:
            doctor.REPO = Path(r"D:\repo")
            self.assertTrue(doctor.is_project_port_owner(9222, info))
        finally:
            doctor.REPO = old_repo

    def test_识别_MAC项目看板进程(self):
        info = {
            "CommandLine": (
                "/repo/.venv/bin/python -u app.py "
                "--db /repo/activities/_db/投放数据.db"
            )
        }
        old_repo = doctor.REPO
        try:
            doctor.REPO = Path("/repo")
            self.assertTrue(doctor.is_project_port_owner(8770, info))
        finally:
            doctor.REPO = old_repo

    def test_保存广告用户名保留owner(self):
        with temp_workdir("doctor-") as tmp:
            path = Path(tmp) / "operator.json"
            path.write_text('{"owner": "hang", "ad_username": null}\n', encoding="utf-8")
            old_path = doctor.OPERATOR_PATH
            try:
                doctor.OPERATOR_PATH = path
                doctor.write_ad_username("sample-user")
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data, {"owner": "hang", "ad_username": "sample-user"})
            finally:
                doctor.OPERATOR_PATH = old_path

    def test_首选端口被占用时可自动回退(self):
        info = {"Name": "other.exe", "CommandLine": "other.exe"}
        old_repo = doctor.REPO
        failures = []
        try:
            doctor.REPO = Path(r"D:\repo")
            with mock.patch.object(doctor, "listener_pids", return_value=[1234]), \
                    mock.patch.object(doctor, "process_info", return_value=info), \
                    mock.patch.object(doctor.runtime_state, "next_free_port", return_value=8771):
                self.assertTrue(doctor.check_port(8770, "看板端口", failures, allow_fallback=True))
        finally:
            doctor.REPO = old_repo
        self.assertEqual(failures, [])

    def test_数据平台导航到第二个页面(self):
        events = []

        class Page:
            def __init__(self):
                self.url = ""
                self.closed = False

            def goto(self, url, **_kwargs):
                self.url = url

            def wait_for_timeout(self, _milliseconds):
                pass

            def close(self):
                self.closed = True

        for login in (True, False):
            with self.subTest(login=login):
                events.clear()
                admin_page = Page()
                data_page = Page()
                context = mock.Mock()
                context.new_page.side_effect = [admin_page, data_page]
                broker = types.SimpleNamespace(
                    ensure=lambda _mode: events.append(("browser", None)),
                    connect=lambda _playwright: context,
                )

                def probe_admin(page):
                    events.append(("admin", page.url))
                    return page.url == "https://admin.example", "admin"

                def probe_databi(page, navigate=True):
                    events.append(("data", page.url))
                    return page.url == "https://data.example", "data"

                wait_login = types.SimpleNamespace(
                    DEFAULT_URL="https://admin.example",
                    DATABI_URL="https://data.example",
                    probe_admin=probe_admin,
                    probe_databi=probe_databi,
                    ui=types.SimpleNamespace(
                        login_identity=lambda _page: {"userName": "tester"}
                    ),
                )
                sync_playwright = mock.MagicMock()
                sync_playwright.return_value.__enter__.return_value = mock.Mock()
                playwright_module = types.SimpleNamespace(
                    sync_playwright=sync_playwright
                )
                failures = []

                with mock.patch.dict(sys.modules, {
                    "browser_broker": broker,
                    "wait_login": wait_login,
                    "playwright.sync_api": playwright_module,
                }), mock.patch.object(doctor, "write_ad_username"), \
                        mock.patch(
                            "builtins.print",
                            side_effect=lambda *_args, **_kwargs: events.append(
                                ("print", None)
                            ),
                        ):
                    doctor.check_logins(login, 0, failures, operator_ok=True)

                self.assertEqual(admin_page.url, "https://admin.example")
                self.assertEqual(data_page.url, "https://data.example")
                self.assertEqual(failures, [])
                browser_index = events.index(("browser", None))
                admin_index = events.index(("admin", "https://admin.example"))
                data_index = events.index(("data", "https://data.example"))
                self.assertLess(browser_index, admin_index)
                self.assertLess(browser_index, data_index)
                if login:
                    self.assertGreater(browser_index, 0)


if __name__ == "__main__":
    unittest.main()
