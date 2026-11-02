# -*- coding: utf-8 -*-
"""创建并轮转数据库 v2 的一致性备份。"""
from __future__ import annotations

import argparse
import datetime
import os
from pathlib import Path
import re
import sqlite3
import sys


REPO = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO / "activities" / "_db" / "投放数据.db"
BACKUP_GLOB = "投放数据-backup-*.db"


def _safe_tag(tag: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", str(tag or "")).strip("-")
    return value or "manual"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def prune_backups(backup_dir: Path | str, keep: int) -> list[Path]:
    """只清理本工具生成的快照，返回被删除的文件。"""
    if keep < 1:
        raise ValueError("keep 必须大于等于 1")
    backup_dir = Path(backup_dir)
    files = sorted(
        (path for path in backup_dir.glob(BACKUP_GLOB) if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    removed = files[int(keep):]
    for path in removed:
        path.unlink()
    return removed


def backup_database(
    db_path: Path | str = DEFAULT_DB,
    backup_dir: Path | str | None = None,
    keep: int = 7,
    tag: str = "manual",
    now: datetime.datetime | None = None,
) -> dict:
    """用 SQLite backup API 生成快照，校验成功后再纳入轮转。"""
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{db_path}")
    if keep < 1:
        raise ValueError("keep 必须大于等于 1")

    backup_dir = Path(backup_dir) if backup_dir else db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    target = _unique_path(
        backup_dir / f"投放数据-backup-{stamp}-{_safe_tag(tag)}.db"
    )
    temp = target.with_name(target.name + ".tmp")

    source = None
    destination = None
    try:
        source = sqlite3.connect(
            db_path.as_uri() + "?mode=ro",
            uri=True,
            timeout=10,
        )
        source.execute("PRAGMA busy_timeout=5000")
        destination = sqlite3.connect(temp)
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"备份完整性检查失败：{result[0] if result else '无结果'}")
        destination.close()
        destination = None
        source.close()
        source = None
        os.replace(temp, target)
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        try:
            temp.unlink()
        except FileNotFoundError:
            pass

    removed = prune_backups(backup_dir, keep)
    return {
        "path": str(target),
        "pruned": [str(path) for path in removed],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="备份数据库 v2")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="数据库路径")
    parser.add_argument("--backup-dir", default="", help="备份目录，默认数据库旁的 backups")
    parser.add_argument("--keep", type=int, default=7, help="保留最近几份本工具备份")
    parser.add_argument("--tag", default="manual", help="备份标签，例如 manual")
    args = parser.parse_args()

    try:
        result = backup_database(
            args.db,
            args.backup_dir or None,
            keep=args.keep,
            tag=args.tag,
        )
    except Exception as exc:
        print(f"BACKUP: FAILED | {str(exc).splitlines()[0][:240]}")
        return 1

    print(f"备份：{result['path']}")
    print(f"校验：integrity=ok；清理旧备份 {len(result['pruned'])} 份")
    print("BACKUP: OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
