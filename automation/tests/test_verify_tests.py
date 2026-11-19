# -*- coding: utf-8 -*-
from pathlib import Path
import sys
import unittest

from _temp import temp_workdir


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_tests  # noqa: E402


class VerifyTestsTest(unittest.TestCase):
    def test_自动模式检测_WORKBUDDY_删除垫片(self):
        mode, reason = verify_tests.choose_mode(
            "auto",
            {"CODEBUDDY_SAFE_DELETE_ENABLED": "1"},
        )
        self.assertEqual(mode, "by-file")
        self.assertIn("WorkBuddy", reason)

    def test_普通环境使用全量测试(self):
        self.assertEqual(verify_tests.choose_mode("auto", {})[0], "full")

    def test_解析_JUNIT_跳过_和失败数(self):
        with temp_workdir("verify-junit-") as tmp:
            report = Path(tmp) / "report.xml"
            report.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite tests="5" failures="1" errors="0" skipped="1">
    <testcase classname="A" name="ok"/>
    <testcase classname="A" name="bad"><failure message="boom"/></testcase>
  </testsuite>
</testsuites>
""",
                encoding="utf-8",
            )
            result = verify_tests.parse_report(report)
            self.assertEqual(
                (result["tests"], result["passed"], result["failed"], result["skipped"]),
                (5, 3, 1, 1),
            )
            self.assertEqual(result["failures"], ["A::bad"])


if __name__ == "__main__":
    unittest.main()
