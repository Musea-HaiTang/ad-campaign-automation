# -*- coding: utf-8 -*-
"""执行结果写入数据库 v2 的幂等测试。"""
import os
import shutil
import sys
import unittest
from copy import deepcopy
from unittest import mock

from _temp import make_temp_workdir

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import campaign  # noqa: E402
import workspace_repo as repo  # noqa: E402
import workspace_sync  # noqa: E402

CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "activities", "_示例活动", "配置", "示例活动-hang.yaml",
)


class WorkspaceSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_workdir("workspace-sync-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db_path = os.path.join(self.tmp, "v2.db")
        self.cfg = campaign.load(CONFIG)

    def test_plan_then_running_updates_same_batches_and_creatives(self):
        audience = self.cfg["audiences"][0]
        first = workspace_sync.sync_config_batch(
            self.db_path, self.cfg, [audience], "2026-01-05",
            "首批", status="planned",
        )
        second = workspace_sync.sync_config_batch(
            self.db_path, self.cfg, [audience], "2026-01-05",
            "首批", status="running",
        )
        self.assertEqual(first["batch_ids"], second["batch_ids"])
        conn = repo.connect(self.db_path)
        self.addCleanup(conn.close)
        batch = repo.get_bucket_batch(conn, first["batch_ids"][0])
        self.assertEqual((batch["status"], batch["task_state"]), ("running", "进行中"))
        bucket = conn.execute(
            "SELECT default_threshold_exposure FROM bucket WHERE id=?",
            (batch["bucket_id"],),
        ).fetchone()
        self.assertEqual(bucket["default_threshold_exposure"], 3000)
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM creative WHERE batch_id=?", (batch["id"],)
            ).fetchone()[0],
            3,
        )
        first_copy = conn.execute(
            "SELECT angle_key, presentation_type, style_key, validation_slot "
            "FROM creative WHERE batch_id=? ORDER BY slot LIMIT 1",
            (batch["id"],),
        ).fetchone()
        self.assertEqual(
            tuple(first_copy),
            ("A-场景痛点", "direct_marketing", "regular", "first_test"),
        )

    def test_execution_yaml_cannot_reactivate_ended_activity(self):
        audience = self.cfg["audiences"][0]
        first = workspace_sync.sync_config_batch(
            self.db_path, self.cfg, [audience], "2026-01-05",
            "首批", status="planned",
        )
        conn = repo.connect(self.db_path)
        repo.set_activity_status(
            conn, self.cfg["campaign"]["taskGroupName"], "ended", "2026-01-10")
        conn.close()
        workspace_sync.sync_config_batch(
            self.db_path, self.cfg, [audience], "2026-01-05",
            "重新执行", status="running",
        )
        conn = repo.connect(self.db_path)
        self.addCleanup(conn.close)
        activity = repo.get_activity(conn, self.cfg["campaign"]["taskGroupName"])
        self.assertEqual((activity["status"], activity["ended_on"]),
                         ("ended", "2026-01-10"))
        self.assertEqual(repo.get_bucket_batch(conn, first["batch_ids"][0])["status"],
                         "running")

    def test_execution_yaml_cannot_overwrite_activity_display_name(self):
        audience = self.cfg["audiences"][0]
        workspace_sync.sync_config_batch(
            self.db_path, self.cfg, [audience], "2026-01-05",
            "首批", status="running",
        )
        conn = repo.connect(self.db_path)
        original = repo.get_activity(conn, self.cfg["campaign"]["taskGroupName"])
        conn.close()

        next_cfg = deepcopy(self.cfg)
        next_cfg["label"] = "错误覆盖-1类"
        workspace_sync.sync_config_batch(
            self.db_path, next_cfg, [audience], "2026-01-05",
            "批次执行", status="running",
        )
        conn = repo.connect(self.db_path)
        self.addCleanup(conn.close)
        current = repo.get_activity(conn, self.cfg["campaign"]["taskGroupName"])
        self.assertEqual(current["display_name"], original["display_name"])

    def test_reused_resource_keeps_copy_snapshot_in_new_batch(self):
        first_aud = self.cfg["audiences"][0]
        first = workspace_sync.sync_config_batch(
            self.db_path, self.cfg, [first_aud], "2026-01-05",
            "首批", status="running",
        )
        next_cfg = deepcopy(self.cfg)
        next_aud = next_cfg["audiences"][0]
        next_aud["nameSuffix"] = "-2"
        next_aud["resources"] = []
        next_aud["abGroups"] = deepcopy(first_aud["abGroups"])
        second = workspace_sync.sync_config_batch(
            self.db_path, next_cfg, [next_aud], "2026-01-06",
            "复用资源", status="running",
        )

        conn = repo.connect(self.db_path)
        self.addCleanup(conn.close)
        old_rows = conn.execute(
            "SELECT resource_name, title, summary, angle_key, presentation_type, "
            "style_key, validation_slot FROM creative "
            "WHERE batch_id=? ORDER BY slot",
            (first["batch_ids"][0],),
        ).fetchall()
        new_rows = conn.execute(
            "SELECT resource_name, title, summary, angle_key, presentation_type, "
            "style_key, validation_slot FROM creative "
            "WHERE batch_id=? ORDER BY slot",
            (second["batch_ids"][0],),
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in new_rows],
            [tuple(row) for row in old_rows],
        )

    def test_单资源桶写入single槽位和100占比(self):
        cfg = deepcopy(self.cfg)
        audience = cfg["audiences"][0]
        audience["abTest"] = False
        audience["resources"] = audience["resources"][:1]
        audience["abGroups"] = [{
            "label": "对照组",
            "resource": audience["resources"][0]["name"],
        }]
        result = workspace_sync.sync_config_batch(
            self.db_path, cfg, [audience], "2026-01-05", status="running",
        )

        conn = repo.connect(self.db_path)
        self.addCleanup(conn.close)
        row = conn.execute(
            "SELECT slot, weight_pct FROM creative WHERE batch_id=?",
            (result["batch_ids"][0],),
        ).fetchone()
        self.assertEqual(tuple(row), ("single", 100))

    def test_数据库同步中途失败会整批回滚(self):
        audience = self.cfg["audiences"][0]
        with mock.patch.object(repo, "save_creative",
                               side_effect=RuntimeError("模拟第三条文案失败")):
            with self.assertRaisesRegex(RuntimeError, "模拟第三条文案失败"):
                workspace_sync.sync_config_batch(
                    self.db_path, self.cfg, [audience], "2026-01-05",
                    "首批", status="running",
                )

        conn = repo.connect(self.db_path)
        self.addCleanup(conn.close)
        self.assertIsNone(repo.get_activity(
            conn, self.cfg["campaign"]["taskGroupName"]))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM bucket").fetchone()[0], 0)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM bucket_batch").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
