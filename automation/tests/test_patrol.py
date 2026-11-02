# -*- coding: utf-8 -*-
import pathlib
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation" / "scripts"))

import patrol  # noqa: E402


class PatrolTest(unittest.TestCase):
    def test_报告包含取数判定和待复盘(self):
        batch = {"mode": "today", "done": 2, "errorCount": 0}
        reviews = [{
            "display_name": "示例活动",
            "bucket_key": "A",
            "task_name": "示例活动-A类",
            "total_exposure": 3000,
            "total_click": 9,
        }]
        text = patrol.report_text(
            batch, "【本轮结论】需要复盘", reviews,
            session_id="session-1", assigned=[10],
        )
        self.assertIn("模式：today；完成：2；失败：0", text)
        self.assertIn("【本轮结论】需要复盘", text)
        self.assertIn("示例活动 / A / 示例活动-A类", text)
        self.assertIn("当前会话：session-1", text)
        self.assertIn("自动回写：1 项", text)

    def test_WorkBuddy会话环境变量优先级(self):
        self.assertEqual(
            patrol.current_session_id({
                "CODEBUDDY_SESSION_ID": "workbuddy-session",
                "CLAUDE_SESSION_ID": "claude-session",
            }),
            "workbuddy-session",
        )
        self.assertEqual(
            patrol.current_session_id({"CLAUDE_SESSION_ID": "claude-session"}),
            "claude-session",
        )
        self.assertEqual(patrol.current_session_id({}), "")

    def test_只回写没有thread_id的待复盘(self):
        reviews = [
            {"id": 1, "thread_id": ""},
            {"id": 2, "thread_id": "existing"},
            {"id": 3},
        ]
        with mock.patch.object(patrol, "run_script", return_value="REVIEW_ASSIGNED") as run:
            assigned = patrol.assign_reviews(pathlib.Path("db.sqlite"), reviews, "session-1")
        self.assertEqual(assigned, [1, 3])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(reviews[0]["thread_id"], "session-1")
        self.assertEqual(reviews[1]["thread_id"], "existing")


if __name__ == "__main__":
    unittest.main()
