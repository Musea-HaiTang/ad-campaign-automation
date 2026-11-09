# -*- coding: utf-8 -*-
"""workspace_repo 的公开接口测试：不依赖旧台账和旧 YAML。"""
import os
import shutil
import sqlite3
import sys
import unittest

from _temp import make_temp_workdir

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import workspace_repo as repo  # noqa: E402


class WorkspaceRepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_workdir("workspace-repo-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.conn = repo.connect(os.path.join(self.tmp, "投放数据.db"))
        self.addCleanup(self.conn.close)

    def _activity(self, key="demo"):
        self.conn.execute(
            "INSERT INTO activity(activity_key, display_name, brand, owner, name_prefix, "
            "task_group_name, activity_link, status, started_on) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (key, "示例活动", "示例", "hang", key + "-hang", key + "-hang",
             "https://example.com", "active", "2026-10-01"),
        )
        return self.conn.execute(
            "SELECT id FROM activity WHERE activity_key=?", (key,)
        ).fetchone()["id"]

    def _bucket(self, activity_id, key):
        self.conn.execute(
            "INSERT INTO bucket(activity_id, bucket_key, display_name, topic, target, "
            "keywords_text, default_threshold_exposure, status) VALUES(?,?,?,?,?,?,?,?)",
            (activity_id, key, key, "", "", "", 1000, "active"),
        )
        return self.conn.execute(
            "SELECT id FROM bucket WHERE activity_id=? AND bucket_key=?",
            (activity_id, key),
        ).fetchone()["id"]

    def test_schema_has_final_tables_and_foreign_keys(self):
        names = {
            row["name"] for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        self.assertEqual(names, {
            "activity", "bucket", "bucket_batch", "creative", "daily_metric",
            "resource_reading", "selection_run", "fetch_run", "review", "review_resource",
            "schema_version",
        })
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0], 6)
        creative_columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(creative)").fetchall()
        }
        self.assertIn("presentation_type", creative_columns)
        self.assertIn("validation_slot", creative_columns)

    def test_每个数据库版本都有升级与回滚说明(self):
        doc = (
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            + os.sep + "automation" + os.sep + "docs" + os.sep + "数据库迁移版本.md"
        )
        with open(doc, encoding="utf-8") as source:
            text = source.read()
        for version in range(1, repo.SCHEMA_VERSION + 1):
            self.assertIn(f"| v{version} |", text)

    def test_旧库迁移前强制备份(self):
        path = os.path.join(self.tmp, "旧库.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES(4, '2026-10-01')"
        )
        conn.commit()
        conn.close()

        migrated = repo.connect(path)
        migrated.close()

        backups = [
            name for name in os.listdir(os.path.join(self.tmp, "backups"))
            if name.startswith("投放数据-backup-") and "-pre-v4" in name
        ]
        self.assertEqual(len(backups), 1)
        snapshot = sqlite3.connect(os.path.join(self.tmp, "backups", backups[0]))
        try:
            version = snapshot.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            tables = {
                row[0] for row in snapshot.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            snapshot.close()
        self.assertEqual(version, 4)
        self.assertNotIn("activity", tables)

    def test_v5_creative_migrates_classification_columns(self):
        path = os.path.join(self.tmp, "v5.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE schema_version(
              version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version(version, applied_at)
              VALUES(5, '2026-10-28');
            CREATE TABLE creative (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              batch_id INTEGER NOT NULL,
              resource_id TEXT,
              resource_name TEXT NOT NULL DEFAULT '',
              copy_id TEXT NOT NULL,
              title TEXT NOT NULL,
              summary TEXT NOT NULL,
              highlight TEXT NOT NULL DEFAULT '',
              angle_key TEXT NOT NULL DEFAULT '',
              style_key TEXT NOT NULL DEFAULT '',
              slot TEXT NOT NULL,
              weight_pct INTEGER NOT NULL,
              status TEXT NOT NULL,
              UNIQUE(batch_id, slot)
            );
            CREATE UNIQUE INDEX uq_creative_resource
              ON creative(batch_id, resource_id) WHERE resource_id IS NOT NULL;
        """)
        conn.commit()
        conn.close()

        migrated = repo.connect(path)
        try:
            columns = {
                row["name"] for row in migrated.execute(
                    "PRAGMA table_info(creative)").fetchall()
            }
            version = migrated.execute(
                "SELECT MAX(version) FROM schema_version").fetchone()[0]
        finally:
            migrated.close()

        self.assertEqual(version, repo.SCHEMA_VERSION)
        self.assertIn("presentation_type", columns)
        self.assertIn("validation_slot", columns)

    def test_batch_numbers_are_independent_per_bucket(self):
        activity_id = self._activity()
        a = self._bucket(activity_id, "A")
        b = self._bucket(activity_id, "B")
        a1 = repo.create_bucket_batch(self.conn, a, "2026-10-01", status="closed")
        a2 = repo.create_bucket_batch(self.conn, a, "2026-10-02")
        b1 = repo.create_bucket_batch(self.conn, b, "2026-10-01")
        self.assertEqual((a1["batch_no"], a2["batch_no"], b1["batch_no"]), (1, 2, 1))
        self.assertEqual(repo.get_current_batch(self.conn, a)["id"], a2["id"])
        self.assertEqual(repo.get_current_batch(self.conn, b)["id"], b1["id"])

    def test_current_batch_is_latest_even_before_it_has_readings(self):
        activity_id = self._activity()
        bucket_id = self._bucket(activity_id, "A")
        first = repo.create_bucket_batch(
            self.conn, bucket_id, "2026-10-01", status="running")
        creative = repo.add_creative(
            self.conn, first["id"], "r1", "A类 · 对照", "copy-1",
            "标题", "摘要", "", "", "control", 100, status="running",
        )
        fetch = repo.start_fetch_run(
            self.conn, activity_id, scope="today", triggered_by="manual",
            requested_from="2026-10-01", requested_to="2026-10-01",
        )
        repo.add_resource_reading(
            self.conn, first["id"], creative["id"], fetch["id"],
            captured_at="2026-10-01T10:00:00+08:00", exposure=1200, click=4,
        )
        second = repo.create_bucket_batch(
            self.conn, bucket_id, "2026-10-02", status="running")
        self.assertEqual(repo.get_current_batch(self.conn, bucket_id)["id"], second["id"])

    def test_imported_first_batch_order_is_repaired_without_changing_task_state(self):
        activity_id = self._activity()
        bucket_id = self._bucket(activity_id, "A")
        later_2 = repo.create_bucket_batch(
            self.conn, bucket_id, "2026-10-14", change_reason="10-14 -2",
            status="running")
        later_3 = repo.create_bucket_batch(
            self.conn, bucket_id, "2026-10-15", change_reason="10-15 -3",
            status="running")
        first = repo.create_bucket_batch(
            self.conn, bucket_id, "2026-10-21", change_reason="首批",
            status="running")
        updates = {
            later_2["id"]: ("200", "A类-2"),
            later_3["id"]: ("300", "A类-3"),
            first["id"]: ("100", "A类"),
        }
        for batch_id, (task_id, task_name) in updates.items():
            self.conn.execute(
                "UPDATE bucket_batch SET task_id=?, task_name=?, task_state='下线' WHERE id=?",
                (task_id, task_name, batch_id),
            )
        fetch = repo.start_fetch_run(
            self.conn, activity_id, scope="full", triggered_by="system",
            requested_from="2026-10-12", requested_to="2026-10-12",
        )
        repo.upsert_daily_metric(
            self.conn, first["id"], "2026-10-12",
            exposure=100, click=1, login_exposure=80, login_click=1,
            fetch_run_id=fetch["id"],
        )

        repo._repair_imported_batch_order(self.conn)

        rows = self.conn.execute(
            "SELECT batch_no, started_on, status, task_state "
            "FROM bucket_batch WHERE bucket_id=? ORDER BY batch_no",
            (bucket_id,),
        ).fetchall()
        self.assertEqual(
            [(r["batch_no"], r["started_on"]) for r in rows],
            [(1, "2026-10-12"), (2, "2026-10-14"), (3, "2026-10-15")],
        )
        self.assertTrue(all(r["status"] == "running" for r in rows))
        self.assertTrue(all(r["task_state"] == "下线" for r in rows))
        self.assertEqual(repo.get_current_batch(self.conn, bucket_id)["id"], later_3["id"])

    def test_activity_and_bucket_upsert_keep_stable_keys(self):
        activity = repo.save_activity(self.conn, {
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
        bucket = repo.save_bucket(self.conn, activity["id"], {
            "bucket_key": "A",
            "display_name": "A类",
            "topic": "主题",
            "target": "读者",
            "keywords_text": "词一,词二",
            "default_threshold_exposure": 1000,
            "status": "active",
        })
        activity2 = repo.save_activity(self.conn, {
            **activity,
            "display_name": "示例活动新名称",
        })
        bucket2 = repo.save_bucket(self.conn, activity["id"], {
            **bucket,
            "display_name": "A类新名称",
        })
        self.assertEqual(activity["id"], activity2["id"])
        self.assertEqual(bucket["id"], bucket2["id"])
        self.assertEqual(repo.list_activities(self.conn)[0]["display_name"], "示例活动新名称")
        self.assertEqual(repo.list_buckets(self.conn, activity["id"])[0]["display_name"], "A类新名称")

    def test_activity_status_can_end_and_restart(self):
        activity_id = self._activity()
        ended = repo.set_activity_status(
            self.conn, "demo", "ended", "2026-10-20")
        self.assertEqual((ended["id"], ended["status"], ended["ended_on"]),
                         (activity_id, "ended", "2026-10-20"))
        active = repo.set_activity_status(self.conn, "demo", "active")
        self.assertEqual((active["status"], active["ended_on"]), ("active", None))

    def test_aborted_batch_is_not_current(self):
        activity_id = self._activity()
        bucket_id = self._bucket(activity_id, "A")
        first = repo.create_bucket_batch(self.conn, bucket_id, "2026-10-01")
        repo.create_bucket_batch(self.conn, bucket_id, "2026-10-02", status="aborted")
        self.assertEqual(repo.get_current_batch(self.conn, bucket_id)["id"], first["id"])

    def test_selection_runs_are_per_bucket_and_idempotent(self):
        activity_id = self._activity()
        self._bucket(activity_id, "A")
        first = repo.save_selection_run(
            self.conn, activity_id, "A", "2026-10-20 16:39", 92, 81768, 1046302)
        again = repo.save_selection_run(
            self.conn, activity_id, "A", "2026-10-20 16:39", 92, 81768, 1046302)
        self.assertEqual(first["id"], again["id"])
        rows = repo.list_selection_runs(self.conn, activity_id)
        self.assertEqual(rows[0]["bucket_key"], "A")
        self.assertEqual(rows[0]["article_count"], 81768)

    def test_ensure_batch_for_task_is_idempotent_by_task_name(self):
        activity_id = self._activity()
        bucket_id = self._bucket(activity_id, "A")
        first = repo.ensure_batch_for_task(
            self.conn, activity_id, "A", "demo-hang-A类", "2026-10-01",
            change_reason="首测",
        )
        second = repo.ensure_batch_for_task(
            self.conn, activity_id, "A", "demo-hang-A类", "2026-10-01",
            change_reason="首测",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["batch_no"], 1)

    def test_save_creative_updates_same_slot_without_duplicate(self):
        activity_id = self._activity()
        bucket_id = self._bucket(activity_id, "A")
        batch = repo.create_bucket_batch(self.conn, bucket_id, "2026-10-01")
        first = repo.save_creative(
            self.conn, batch["id"], None, "A类 · 对照", "copy-1",
            "旧标题", "旧摘要", "", "", "control", 100, "planned",
        )
        second = repo.save_creative(
            self.conn, batch["id"], "r1", "A类 · 对照", "copy-1",
            "新标题", "新摘要", "angle", "regular", "control", 100, "running",
            presentation_type="direct_marketing", validation_slot="first_test",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["resource_id"], "r1")
        self.assertEqual(second["title"], "新标题")
        self.assertEqual(second["presentation_type"], "direct_marketing")
        self.assertEqual(second["validation_slot"], "first_test")

    def test_review_is_unique_per_batch_and_due_list_is_actionable(self):
        activity_id = self._activity()
        bucket_id = self._bucket(activity_id, "A")
        batch = repo.create_bucket_batch(self.conn, bucket_id, "2026-10-01", status="running")
        fetch = repo.start_fetch_run(
            self.conn, activity_id, scope="today", triggered_by="manual",
            requested_from="2026-10-01", requested_to="2026-10-01",
        )
        first = repo.ensure_review(
            self.conn, batch["id"], fetch["id"], threshold_exposure=1000,
            total_exposure=1200, total_click=2,
        )
        second = repo.ensure_review(
            self.conn, batch["id"], fetch["id"], threshold_exposure=1000,
            total_exposure=1300, total_click=3,
        )
        self.assertEqual(first["id"], second["id"])
        due = repo.list_review_due(self.conn, activity_id)
        self.assertEqual(len(due), 1)
        self.assertEqual((due[0]["bucket_key"], due[0]["exposure"]), ("A", 1200))

    def test_review_resource_keeps_evidence_and_decision(self):
        activity_id = self._activity()
        bucket_id = self._bucket(activity_id, "A")
        batch = repo.create_bucket_batch(self.conn, bucket_id, "2026-10-01", status="running")
        creative = repo.add_creative(
            self.conn, batch["id"], "r1", "A类 · 对照", "copy-1",
            "标题", "摘要", "", "", "control", 100,
        )
        fetch = repo.start_fetch_run(
            self.conn, activity_id, scope="full", triggered_by="auto",
            requested_from="2026-10-01", requested_to="2026-10-01",
        )
        review = repo.ensure_review(
            self.conn, batch["id"], fetch["id"], threshold_exposure=1000,
            total_exposure=1200, total_click=2,
        )
        repo.add_review_resource(
            self.conn, review["id"], creative["id"], exposure=1200,
            click=2, action="keep", reason="有点击，保留",
        )
        rows = repo.list_review_resources(self.conn, review["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["action"], rows[0]["click"]), ("keep", 2))

    def test_creative_daily_and_reading_round_trip(self):
        activity_id = self._activity()
        bucket_id = self._bucket(activity_id, "A")
        batch = repo.create_bucket_batch(self.conn, bucket_id, "2026-10-01")
        creative = repo.add_creative(
            self.conn, batch["id"], resource_id="r1", resource_name="A类 · 对照",
            copy_id="copy-1", title="标题", summary="摘要",
            angle_key="angle", style_key="regular", slot="control", weight_pct=100,
        )
        fetch = repo.start_fetch_run(
            self.conn, activity_id, scope="full", triggered_by="auto",
            requested_from="2026-10-01", requested_to="2026-10-01",
        )
        repo.upsert_daily_metric(
            self.conn, batch["id"], "2026-10-01",
            exposure=120, click=1, login_exposure=80, login_click=1,
            fetch_run_id=fetch["id"],
        )
        repo.add_resource_reading(
            self.conn, batch["id"], creative["id"], fetch["id"],
            captured_at="2026-10-01T10:00:00+08:00", exposure=120, click=1,
        )
        self.assertEqual(repo.latest_resource_readings(self.conn, batch["id"])[0]["click"], 1)
        self.assertEqual(repo.daily_metrics(self.conn, batch["id"])[0]["exposure"], 120)
        repo.finish_fetch_run(
            self.conn, fetch["id"], status="ok", returned_days=1,
            total_exposure=120, total_click=1,
        )
        self.assertEqual(repo.activity_days(self.conn, activity_id), ["2026-10-01"])
        self.assertEqual(repo.last_successful_fetch(self.conn, activity_id)["id"], fetch["id"])
        self.assertEqual(
            repo.full_fetch_on(self.conn, activity_id, fetch["started_at"][:10])["id"],
            fetch["id"],
        )

    def test_foreign_key_violations_are_rejected(self):
        with self.assertRaises(Exception):
            repo.create_bucket_batch(self.conn, 999999, "2026-10-01")


if __name__ == "__main__":
    unittest.main()
