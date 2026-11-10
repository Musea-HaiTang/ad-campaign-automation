# -*- coding: utf-8 -*-
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

from _temp import temp_workdir


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import setup_ai  # noqa: E402


class SetupAITest(unittest.TestCase):
    def test_支持_Python_3_11_到_3_15(self):
        for version in (
            "3.11.9",
            "3.12.4",
            "3.13.7",
            "3.14.10",
            "3.15.2",
        ):
            with self.subTest(version=version):
                self.assertTrue(setup_ai.compatible({"version": version}))

    def test_拒绝_Python_3_11_以下和_3_15_以上(self):
        for version in ("3.10.14", "3.16.0", "2.7.18"):
            with self.subTest(version=version):
                self.assertFalse(setup_ai.compatible({"version": version}))

    def test_虚拟环境路径按平台选择(self):
        with mock.patch.object(setup_ai.sys, "platform", "win32"):
            self.assertEqual(
                setup_ai.venv_python_path(),
                setup_ai.ROOT / ".venv" / "Scripts" / "python.exe",
            )
        with mock.patch.object(setup_ai.sys, "platform", "darwin"):
            self.assertEqual(
                setup_ai.venv_python_path(),
                setup_ai.ROOT / ".venv" / "bin" / "python",
            )

    def test_MAC通过看板服务启动而不是VBS(self):
        completed = mock.Mock(returncode=0, stdout="")
        with mock.patch.object(setup_ai.sys, "platform", "darwin"), \
                mock.patch.object(setup_ai, "run", return_value=completed) as run:
            setup_ai.launch_board("/repo/.venv/bin/python")
        run.assert_called_once_with(
            [
                "/repo/.venv/bin/python",
                str(setup_ai.ROOT / "automation" / "scripts" / "board_service.py"),
                "--start",
            ],
            timeout_seconds=45,
        )

    def test_新部署必须显式提供_owner(self):
        with temp_workdir("setup-ai-owner-") as tmp:
            local = Path(tmp)
            with mock.patch.object(setup_ai, "LOCAL", local):
                with self.assertRaisesRegex(setup_ai.SetupError, "--owner"):
                    setup_ai.ensure_owner("")

    def test_已有_owner_配置直接复用(self):
        with temp_workdir("setup-ai-existing-") as tmp:
            local = Path(tmp)
            (local / "operator.json").write_text(
                json.dumps({"owner": "existing", "ad_username": None}),
                encoding="utf-8",
            )
            with mock.patch.object(setup_ai, "LOCAL", local):
                self.assertEqual(setup_ai.ensure_owner("other"), "existing")

    def test_失败结果自动写入文件(self):
        with temp_workdir("setup-ai-result-") as tmp:
            result = Path(tmp) / "setup-result.json"
            with mock.patch.object(setup_ai, "SETUP_RESULT", result), \
                    mock.patch.object(setup_ai, "SETUP_LOG", Path(tmp) / "setup.log"):
                setup_ai.write_setup_result("failed", "boom")
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["message"], "boom")


if __name__ == "__main__":
    unittest.main()
