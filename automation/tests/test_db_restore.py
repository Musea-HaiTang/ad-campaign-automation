# -*- coding: utf-8 -*-
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import db_restore  # noqa: E402
import workspace_repo  # noqa: E402


def _make_db(path: Path, value: str) -> None:
    conn = workspace_repo.connect(str(path))
    try:
        conn.execute("CREATE TABLE marker(value TEXT)")
        conn.execute("INSERT INTO marker VALUES(?)", (value,))
        conn.commit()
    finally:
        conn.close()


class DatabaseRestoreTest(unittest.TestCase):
    def test_只读校验快照(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.db"
            _make_db(snapshot, "ok")
            result = db_restore.validate_snapshot(snapshot)
            self.assertEqual(result["schema_version"], 5)
            self.assertEqual(result["foreign_key_issues"], 0)

    def test_恢复前备份当前库并恢复快照(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "投放数据.db"
            snapshot = root / "snapshot.db"
            _make_db(target, "current")
            _make_db(snapshot, "restored")

            result = db_restore.restore_database(snapshot, target, confirm=True)

            conn = sqlite3.connect(target)
            try:
                self.assertEqual(conn.execute("SELECT value FROM marker").fetchone()[0], "restored")
            finally:
                conn.close()
            pre_backup = Path(result["pre_restore_backup"])
            self.assertTrue(pre_backup.is_file())
            conn = sqlite3.connect(pre_backup)
            try:
                self.assertEqual(conn.execute("SELECT value FROM marker").fetchone()[0], "current")
            finally:
                conn.close()

    def test_未确认时不覆盖正式库(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "投放数据.db"
            snapshot = root / "snapshot.db"
            _make_db(target, "current")
            _make_db(snapshot, "restored")

            with self.assertRaises(ValueError):
                db_restore.restore_database(snapshot, target, confirm=False)

            conn = sqlite3.connect(target)
            try:
                self.assertEqual(conn.execute("SELECT value FROM marker").fetchone()[0], "current")
            finally:
                conn.close()

    def test_待恢复快照在备份轮转目录中也能恢复(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "投放数据.db"
            backup_dir = root / "backups"
            backup_dir.mkdir()
            snapshot = backup_dir / "投放数据-backup-20260101-000000-old.db"
            _make_db(target, "current")
            _make_db(snapshot, "restored")

            db_restore.restore_database(snapshot, target, keep=1, confirm=True)

            conn = sqlite3.connect(target)
            try:
                self.assertEqual(conn.execute("SELECT value FROM marker").fetchone()[0], "restored")
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
