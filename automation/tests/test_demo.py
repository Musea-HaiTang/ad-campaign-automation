# -*- coding: utf-8 -*-
import datetime
from pathlib import Path
import sys
import unittest

from _temp import temp_workdir


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "automation" / "scripts"))

import demo  # noqa: E402
import workspace_repo  # noqa: E402


class DemoTest(unittest.TestCase):
    def test_空库写入示例且重复执行跳过(self):
        with temp_workdir("demo-") as tmp:
            db = Path(tmp) / "demo.db"
            today = datetime.date(2026, 11, 2)

            first = demo.seed_demo(db, today=today)
            second = demo.seed_demo(db, today=today)

            self.assertEqual(first["status"], "created")
            self.assertEqual(first["buckets"], ["A", "B"])
            self.assertEqual(first["days"], ["2026-10-30", "2026-10-31", "2026-11-01"])
            self.assertEqual(first["orders"], 2)
            self.assertEqual(first["resources"], 2)
            self.assertEqual(second["status"], "skipped")

            conn = workspace_repo.connect(str(db))
            try:
                self.assertEqual(len(workspace_repo.list_activities(conn)), 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM daily_metric").fetchone()[0], 6)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fetch_run WHERE status='ok'").fetchone()[0], 1)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
