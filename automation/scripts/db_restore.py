# -*- coding: utf-8 -*-
"""校验并恢复数据库 v2 快照。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import sys


REPO = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO / "activities" / "_db" / "投放数据.db"
REQUIRED_TABLES = {
    "activity",
    "bucket",
    "bucket_batch",
    "creative",
    "daily_metric",
    "fetch_run",
    "resource_reading",
    "review",
    "review_resource",
    "schema_version",
    "selection_run",
}
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db_backup  # noqa: E402
import workspace_repo  # noqa: E402


def _open_read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def validate_snapshot(snapshot: Path | str) -> dict:
    """只读校验快照；返回 schema 版本和完整性结果。"""
    snapshot = Path(snapshot).resolve()
    if not snapshot.is_file():
        raise FileNotFoundError(f"快照不存在：{snapshot}")
    conn = _open_read_only(snapshot)
    try:
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            version = int(row[0] or 0) if row else 0
        except sqlite3.OperationalError as exc:
            raise RuntimeError("快照缺少 schema_version，不能作为项目数据库恢复") from exc
        if version < 1 or version > workspace_repo.SCHEMA_VERSION:
            raise RuntimeError(
                f"快照 schema v{version} 不受当前版本 v{workspace_repo.SCHEMA_VERSION} 支持"
            )
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise RuntimeError("快照缺少项目表：" + "、".join(missing))
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"快照完整性检查失败：{integrity}")
        foreign_key_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_issues:
            raise RuntimeError(f"快照存在 {len(foreign_key_issues)} 个外键问题")
        return {
            "path": str(snapshot),
            "schema_version": version,
            "foreign_key_issues": 0,
        }
    finally:
        conn.close()


def _check_target_free(target: Path) -> None:
    if not target.exists():
        return
    conn = sqlite3.connect(target, timeout=5)
    try:
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        busy = int(result[0] or 0)
        if busy:
            raise RuntimeError("正式库仍被其他进程使用，请先停止看板和取数任务后重试")
    finally:
        conn.close()


def _remove_sidecars(target: Path) -> None:
    for suffix in ("-wal", "-shm"):
        try:
            Path(str(target) + suffix).unlink()
        except FileNotFoundError:
            pass


def restore_database(
    snapshot: Path | str,
    db_path: Path | str = DEFAULT_DB,
    keep: int = 7,
    confirm: bool = False,
) -> dict:
    """先校验、备份当前库，再原子替换正式库。"""
    if not confirm:
        raise ValueError("恢复会覆盖正式库，必须显式传入 --confirm")
    snapshot = Path(snapshot).resolve()
    target = Path(db_path).resolve()
    validate_snapshot(snapshot)

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.restore-{os.getpid()}.tmp")
    source = None
    destination = None
    try:
        source = _open_read_only(snapshot)
        destination = sqlite3.connect(temp)
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_issues = destination.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_key_issues:
            raise RuntimeError("恢复临时库校验失败")
        destination.close()
        destination = None
        source.close()
        source = None

        pre_backup = None
        if target.is_file():
            pre_backup = db_backup.backup_database(
                target,
                backup_dir=target.parent / "backups",
                keep=keep,
                tag="pre-restore",
            )
            _check_target_free(target)

        os.replace(temp, target)
        _remove_sidecars(target)
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        try:
            temp.unlink()
        except FileNotFoundError:
            pass

    restored = validate_snapshot(target)
    return {
        "path": str(target),
        "snapshot": str(snapshot),
        "schema_version": restored["schema_version"],
        "pre_restore_backup": pre_backup["path"] if pre_backup else None,
        "pruned": pre_backup["pruned"] if pre_backup else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="校验并恢复数据库 v2 快照")
    subparsers = parser.add_subparsers(dest="action", required=True)

    check_parser = subparsers.add_parser("check", help="只读校验快照")
    check_parser.add_argument("snapshot")

    restore_parser = subparsers.add_parser("restore", help="恢复快照到正式库")
    restore_parser.add_argument("snapshot")
    restore_parser.add_argument("--db", default=str(DEFAULT_DB), help="正式数据库路径")
    restore_parser.add_argument("--keep", type=int, default=7, help="恢复前快照保留数量")
    restore_parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认覆盖正式数据库",
    )
    args = parser.parse_args()

    try:
        if args.action == "check":
            result = validate_snapshot(args.snapshot)
            print(f"快照：{result['path']}")
            print(
                f"schema：v{result['schema_version']}；integrity=ok；"
                f"foreign_key_issues={result['foreign_key_issues']}"
            )
            print("RESTORE CHECK: OK")
            return 0

        result = restore_database(
            args.snapshot,
            db_path=args.db,
            keep=args.keep,
            confirm=args.confirm,
        )
        print(f"已恢复：{result['path']}")
        print(f"来源快照：{result['snapshot']}")
        print(f"schema：v{result['schema_version']}；integrity=ok")
        if result["pre_restore_backup"]:
            print(f"恢复前备份：{result['pre_restore_backup']}")
        print(f"清理旧备份：{len(result['pruned'])} 份")
        print("RESTORE: OK")
        return 0
    except Exception as exc:
        print(f"RESTORE: FAILED | {str(exc).splitlines()[0][:240]}")
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
