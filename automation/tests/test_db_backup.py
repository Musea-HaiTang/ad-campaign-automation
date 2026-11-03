# -*- coding: utf-8 -*-
import datetime
import sqlite3
import unittest
from pathlib import Path
import sys

from _temp import temp_workdir


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import db_backup  # noqa: E402


class DatabaseBackupTest(unittest.TestCase):
    def test_备份可读取且只轮转本工具文件(self):
        with temp_workdir("db-backup-read-") as tmp:
            root = Path(tmp)
            db_path = root / "投放数据.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE sample(value TEXT)")
            conn.execute("INSERT INTO sample VALUES('ok')")
            conn.commit()
            conn.close()

            backup_dir = root / "backups"
            backup_dir.mkdir()
            legacy = backup_dir / "投放数据-pre-v5-20261028.db"
            legacy.write_bytes(b"legacy")

            result = db_backup.backup_database(
                db_path,
                backup_dir,
                keep=7,
                tag="manual",
                now=datetime.datetime(2026, 11, 2, 12, 0, 0),
            )

            target = Path(result["path"])
            self.assertTrue(target.is_file())
            self.assertTrue(legacy.is_file())
            conn = sqlite3.connect(target)
            try:
                self.assertEqual(conn.execute("SELECT value FROM sample").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                conn.close()

    def test_默认只保留最近七份(self):
        with temp_workdir("db-backup-rotate-") as tmp:
            root = Path(tmp)
            db_path = root / "投放数据.db"
            sqlite3.connect(db_path).close()
            start = datetime.datetime(2026, 11, 2, 12, 0, 0)
            paths = []
            for index in range(9):
                result = db_backup.backup_database(
                    db_path,
                    root / "backups",
                    keep=7,
                    now=start + datetime.timedelta(minutes=index),
                )
                paths.append(Path(result["path"]))

            existing = sorted((root / "backups").glob(db_backup.BACKUP_GLOB))
            self.assertEqual(len(existing), 7)
            self.assertFalse(paths[0].exists())
            self.assertFalse(paths[1].exists())
            self.assertTrue(paths[-1].exists())

    def test_数据库不存在时失败(self):
        with temp_workdir("db-backup-missing-") as tmp:
            with self.assertRaises(FileNotFoundError):
                db_backup.backup_database(Path(tmp) / "missing.db")


if __name__ == "__main__":
    unittest.main()
