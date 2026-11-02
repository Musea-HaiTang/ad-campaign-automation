# -*- coding: utf-8 -*-
"""公共浏览器 broker：停止失败不能假报成功。"""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import browser_broker as broker  # noqa: E402


class BrokerStopTest(unittest.TestCase):
    def test_端口还在时stop必须报错(self):
        state = {"pid": 123, "port": 9222, "browserPath": "browser.exe"}
        with mock.patch.object(broker, "_state", return_value=state), \
                mock.patch.object(broker.runtime_state, "process_matches", return_value=True), \
                mock.patch.object(broker.runtime_state, "clear_state"), \
                mock.patch.object(broker.subprocess, "run"), \
                mock.patch.object(broker, "_responsive", return_value=True):
            with self.assertRaises(RuntimeError):
                broker.stop()

    def test_端口已经不通就正常返回(self):
        state = {"pid": 123, "port": 9222, "browserPath": "browser.exe"}
        with mock.patch.object(broker, "_state", return_value=state), \
                mock.patch.object(broker.runtime_state, "process_matches", return_value=True), \
                mock.patch.object(broker.runtime_state, "clear_state"), \
                mock.patch.object(broker.subprocess, "run"), \
                mock.patch.object(
                    broker.cleanup,
                    "maybe_clean_browser_profile",
                    return_value={"status": "skipped"},
                ), \
                mock.patch.object(broker, "_responsive", return_value=False):
            self.assertEqual(broker.stop(), 1)

    def test_读取浏览器配置文件(self):
        with tempfile.TemporaryDirectory() as tmp:
            browser = pathlib.Path(tmp) / "chrome.exe"
            browser.write_text("", encoding="utf-8")
            config = pathlib.Path(tmp) / "browser.json"
            config.write_text(
                '{"kind":"Chrome","path":"%s"}' % str(browser).replace("\\", "\\\\"),
                encoding="utf-8",
            )
            with mock.patch.object(broker, "CONFIG", str(config)), \
                    mock.patch.dict(broker.os.environ, {}, clear=False):
                broker.os.environ.pop(broker.BROWSER_ENV, None)
                self.assertEqual(broker.browser_exe(), str(browser))

    def test_自动检测优先Edge再回退Chrome(self):
        with mock.patch.object(broker, "_configured_browser", return_value=""), \
                mock.patch.object(
                    broker, "_browser_candidates",
                    side_effect=lambda kind: [] if kind == "Edge" else [r"C:\Chrome\chrome.exe"],
                ):
            self.assertEqual(broker.browser_exe(), r"C:\Chrome\chrome.exe")

    def test_CDP地址读取状态中的实际端口(self):
        with mock.patch.object(broker, "_state", return_value={"pid": 1, "port": 9231}):
            self.assertEqual(broker.cdp_url(), "http://127.0.0.1:9231")

    def test_没有本项目状态时不能仅凭端口响应认浏览器(self):
        with mock.patch.object(broker, "_state", return_value={}), \
                mock.patch.object(broker, "_responsive", return_value=True):
            self.assertFalse(broker.is_up())


if __name__ == "__main__":
    unittest.main()
