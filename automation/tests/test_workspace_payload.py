# -*- coding: utf-8 -*-
"""数据库 v2 的看板 payload 对拍测试。"""
import os
import shutil
import sys
import unittest

from _temp import make_temp_workdir

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import workspace_payload as payload_mod  # noqa: E402
import workspace_repo as repo  # noqa: E402


class WorkspacePayloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_workdir("workspace-payload-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.conn = repo.connect(os.path.join(self.tmp, "v2.db"))
        self.addCleanup(self.conn.close)
        self.activity = repo.save_activity(self.conn, {
            "activity_key": "demo",
            "display_name": "示例活动",
            "brand": "示例",
            "owner": "hang",
            "name_prefix": "demo-hang",
            "task_group_name": "demo-hang",
            "activity_link": "https://example.com",
            "status": "active",
            "started_on": "2026-10-01",
            "ended_on": None,
        })
        self.bucket = repo.save_bucket(self.conn, self.activity["id"], {
            "bucket_key": "A",
            "display_name": "demo-hang-A类",
            "topic": "主题",
            "target": "",
            "keywords_text": "",
            "default_threshold_exposure": 1000,
            "status": "active",
        })
        self.batch = repo.create_bucket_batch(
            self.conn, self.bucket["id"], "2026-10-01",
            change_reason="首测", status="running",
        )
        with self.conn:
            self.conn.execute(
                "UPDATE bucket_batch SET task_id='t1', task_name='demo-hang-A类 · 主题', "
                "task_state='进行中' WHERE id=?",
                (self.batch["id"],),
            )
        self.creative = repo.add_creative(
            self.conn, self.batch["id"], "r1", "demo-hang-A类 · 对照",
            "copy-1", "标题", "摘要", "angle-1", "regular",
            "control", 100, status="running",
        )
        fetch = repo.start_fetch_run(
            self.conn, self.activity["id"], scope="today", triggered_by="manual",
            requested_from="2026-10-01", requested_to="2026-10-01",
        )
        repo.upsert_daily_metric(
            self.conn, self.batch["id"], "2026-10-01",
            exposure=1200, click=4, login_exposure=900, login_click=3,
            fetch_run_id=fetch["id"],
        )
        repo.add_resource_reading(
            self.conn, self.batch["id"], self.creative["id"], fetch["id"],
            captured_at="2026-10-01T10:00:00+08:00", exposure=1200, click=4,
        )
        review = repo.ensure_review(
            self.conn, self.batch["id"], fetch["id"], threshold_exposure=1000,
            total_exposure=1200, total_click=4,
        )
        repo.add_review_resource(
            self.conn, review["id"], self.creative["id"], exposure=1200,
            click=4, action="keep", reason="有点击",
        )
        repo.save_review(
            self.conn, review["id"], status="done", conclusion="pass",
            new_copy_count=0, report_text="保留",
            completed_at="2026-10-01T12:00:00+08:00",
        )

    def test_payload_preserves_bucket_current_batch_and_metrics(self):
        payload = payload_mod.build_payload(self.conn, self.activity["id"], today="2026-10-02")
        self.assertEqual(payload["label"], "示例活动")
        self.assertEqual(payload["days"], ["2026-10-01"])
        self.assertEqual(payload["buckets"][0]["currentBatch"], "A:1")
        self.assertEqual(payload["buckets"][0]["batches"][0]["exposure"], 1200)
        self.assertEqual(payload["bucketCells"]["A"]["all"]["2026-10-01"], (1200, 4, 900, 3))
        self.assertEqual(payload["batchJudge"]["A:1"][0]["pass"], True)
        self.assertEqual(payload["batchJudge"]["A:1"][0]["action"]["keep"],
                         ["demo-hang-A类 · 对照"])

    def test_offline_current_batch_keeps_history_but_leaves_threshold(self):
        payload = payload_mod.build_payload(self.conn, self.activity["id"], today="2026-10-03")
        self.assertEqual(payload["batchStats"][0]["runDays"], 3)

        with self.conn:
            self.conn.execute(
                "UPDATE bucket_batch SET task_state='下线' WHERE id=?",
                (self.batch["id"],),
            )
        payload = payload_mod.build_payload(self.conn, self.activity["id"], today="2026-10-03")
        self.assertEqual(len(payload["buckets"]), 1)
        self.assertFalse(payload["buckets"][0]["thresholdEligible"])
        self.assertEqual(payload["batchStats"][0]["e"], 1200)

    def test_todo_rows_come_from_due_reviews_only(self):
        second = repo.create_bucket_batch(
            self.conn, self.bucket["id"], "2026-10-02",
            change_reason="补验", status="running",
        )
        with self.conn:
            self.conn.execute(
                "UPDATE bucket_batch SET task_id='t2', task_name='demo-hang-A类 · 主题-2', "
                "task_state='进行中' WHERE id=?",
                (second["id"],),
            )
        fetch = repo.start_fetch_run(
            self.conn, self.activity["id"], scope="today", triggered_by="auto",
            requested_from="2026-10-02", requested_to="2026-10-02",
        )
        repo.ensure_review(
            self.conn, second["id"], fetch["id"], threshold_exposure=1000,
            total_exposure=1100, total_click=1,
        )
        rows = payload_mod.todo_rows(self.conn, self.activity["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            (rows[0]["activityId"], rows[0]["bucket"], rows[0]["task"],
             rows[0]["exposure"], rows[0]["pass"]),
            ("demo", "A", "demo-hang-A类 · 主题-2", 1100, False),
        )

    def test_offline_current_batch_is_hidden_only_from_threshold(self):
        bucket_b = repo.save_bucket(self.conn, self.activity["id"], {
            "bucket_key": "B",
            "display_name": "demo-hang-B类",
            "topic": "主题B",
            "target": "",
            "keywords_text": "",
            "default_threshold_exposure": 1000,
            "status": "active",
        })
        batch_b = repo.create_bucket_batch(
            self.conn, bucket_b["id"], "2026-10-02",
            change_reason="B 批", status="running",
        )
        with self.conn:
            self.conn.execute(
                "UPDATE bucket_batch SET task_id='t2', task_name='demo-hang-B类 · 主题B', "
                "task_state='进行中' WHERE id=?",
                (batch_b["id"],),
            )
            self.conn.execute(
                "UPDATE bucket_batch SET task_state='下线' WHERE id=?",
                (self.batch["id"],),
            )
        fetch = repo.start_fetch_run(
            self.conn, self.activity["id"], scope="today", triggered_by="manual",
            requested_from="2026-10-02", requested_to="2026-10-02",
        )
        repo.upsert_daily_metric(
            self.conn, batch_b["id"], "2026-10-02",
            exposure=800, click=2, login_exposure=700, login_click=2,
            fetch_run_id=fetch["id"],
        )

        payload = payload_mod.build_payload(
            self.conn, self.activity["id"], today="2026-10-03")

        by_id = {bucket["id"]: bucket for bucket in payload["buckets"]}
        self.assertEqual(set(by_id), {"A", "B"})
        self.assertFalse(by_id["A"]["thresholdEligible"])
        self.assertTrue(by_id["B"]["thresholdEligible"])
        self.assertIn("A", payload["bucketCells"])
        self.assertIn("A:1", payload["batchJudge"])
        self.assertEqual({row["bucket"] for row in payload["batchStats"]}, {"A", "B"})
        self.assertEqual(payload["days"], ["2026-10-01", "2026-10-02"])

    def test_todo_rows_skip_offline_current_batch(self):
        second = repo.create_bucket_batch(
            self.conn, self.bucket["id"], "2026-10-02",
            change_reason="补验", status="running",
        )
        with self.conn:
            self.conn.execute(
                "UPDATE bucket_batch SET task_id='t2', task_name='demo-hang-A类 · 主题-2', "
                "task_state='下线' WHERE id=?",
                (second["id"],),
            )
        fetch = repo.start_fetch_run(
            self.conn, self.activity["id"], scope="today", triggered_by="auto",
            requested_from="2026-10-02", requested_to="2026-10-02",
        )
        repo.ensure_review(
            self.conn, second["id"], fetch["id"], threshold_exposure=1000,
            total_exposure=1100, total_click=1,
        )

        self.assertEqual(payload_mod.todo_rows(self.conn, self.activity["id"]), [])


if __name__ == "__main__":
    unittest.main()
