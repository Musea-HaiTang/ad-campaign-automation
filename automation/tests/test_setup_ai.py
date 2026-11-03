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
