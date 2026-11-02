# -*- coding: utf-8 -*-
"""v2 自动复盘判断与简短汇报测试。"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import workspace_repo as repo  # noqa: E402
import workspace_review as review_mod  # noqa: E402


class WorkspaceReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="workspace-review-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db_path = os.path.join(self.tmp, "v2.db")
        self.conn = repo.connect(self.db_path)
        self.addCleanup(self.conn.close)
        self.activity = repo.save_activity(self.conn, {
            "activity_key": "demo", "display_name": "示例活动",
            "brand": "示例", "owner": "hang", "name_prefix": "demo-hang",
            "task_group_name": "demo-hang", "activity_link": "https://example.com",
            "status": "active", "started_on": "2026-10-01", "ended_on": None,
        })
        self.bucket = repo.save_bucket(self.conn, self.activity["id"], {
            "bucket_key": "A", "display_name": "demo-hang-A类",
            "topic": "", "target": "", "keywords_text": "",
            "default_threshold_exposure": 1000, "status": "active",
        })
        self.batch = repo.create_bucket_batch(
            self.conn, self.bucket["id"], "2026-10-01", status="running"
        )
        with self.conn:
            self.conn.execute(
                "UPDATE bucket_batch SET task_id='t1', task_name='demo-hang-A类', "
                "task_state='进行中' WHERE id=?",
                (self.batch["id"],),
            )
        self.creative = repo.add_creative(
            self.conn, self.batch["id"], "r1", "demo-hang-A类 · 对照",
            "copy-1", "标题", "摘要", "", "", "control", 100, status="running",
        )
        self.fetch = repo.start_fetch_run(
            self.conn, self.activity["id"], scope="today", triggered_by="auto",
            requested_from="2026-10-01", requested_to="2026-10-01",
        )
        repo.finish_fetch_run(
            self.conn, self.fetch["id"], status="ok", returned_days=1,
            total_exposure=1200, total_click=4,
        )
        repo.upsert_daily_metric(
            self.conn, self.batch["id"], "2026-10-01", 1200, 4, 800, 3,
            self.fetch["id"],
        )
        repo.add_resource_reading(
            self.conn, self.batch["id"], self.creative["id"], self.fetch["id"],
            captured_at="2026-10-01T10:00:00+08:00", exposure=1200, click=4,
        )

    def test_review_due_is_created_and_brief_starts_with_decision(self):
        result = review_mod.evaluate(self.conn, self.activity["id"], mark_due=True)
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["due"][0]["bucket"], "A")
        self.assertIsNotNone(repo.get_review(self.conn, self.batch["id"]))
        text = review_mod.format_brief(result)
        self.assertTrue(text.startswith("【本轮结论】需要复盘"))
        self.assertIn("A", text)

    def test_below_threshold_only_shows_nearest_buckets(self):
        with self.conn:
            self.conn.execute(
                "UPDATE bucket_batch SET task_state='进行中' WHERE id=?", (self.batch["id"],)
            )
        repo.add_resource_reading(
            self.conn, self.batch["id"], self.creative["id"], self.fetch["id"],
            captured_at="2026-10-01T11:00:00+08:00", exposure=800, click=1,
        )
        result = review_mod.evaluate(self.conn, self.activity["id"], mark_due=False)
        self.assertFalse(result["needs_review"])
        text = review_mod.format_brief(result)
        self.assertTrue(text.startswith("【本轮结论】无需复盘"))
        self.assertIn("最接近", text)

    def test_no_running_task_does_not_show_historical_progress(self):
        with self.conn:
            self.conn.execute(
                "UPDATE bucket_batch SET task_state='下线' WHERE id=?", (self.batch["id"],)
            )
        result = review_mod.evaluate(self.conn, self.activity["id"], mark_due=True)
        self.assertFalse(result["needs_review"])
        self.assertFalse(result["has_running_task"])
        self.assertEqual(result["bucket_count"], 0)
        self.assertEqual(result["near"], [])
        text = review_mod.format_brief(result)
        self.assertTrue(text.startswith("【本轮结论】当前没有任务进行"))
        self.assertIn("【桶进度】无在跑任务", text)
        self.assertNotIn("最接近", text)
        self.assertNotIn("1200 / 1000", text)

    def test_judge_batch_v2_cli_marks_due_and_prints_brief(self):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                              "scripts", "judge_batch.py")
        proc = subprocess.run(
            [sys.executable, script, "--v2-db", self.db_path,
             "--activity", "demo", "--mark", "--brief"],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("【本轮结论】需要复盘"))
        self.assertIsNotNone(repo.get_review(self.conn, self.batch["id"]))

    def test_review_queue_assigns_thread(self):
        result = review_mod.evaluate(self.conn, self.activity["id"], mark_due=True)
        review = repo.get_review(self.conn, self.batch["id"])
        assigned = repo.assign_review_thread(
            self.conn, review["id"], "thread-1", status="drafting"
        )
        self.assertEqual(assigned["thread_id"], "thread-1")
        self.assertEqual(assigned["status"], "drafting")
        self.assertTrue(result["needs_review"])


if __name__ == "__main__":
    unittest.main()
