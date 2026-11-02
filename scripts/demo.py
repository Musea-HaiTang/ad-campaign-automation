# -*- coding: utf-8 -*-
"""为空数据库写入脱敏示例活动和三天的离线指标。"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import sys


sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "automation" / "scripts"))

import campaign  # noqa: E402
import workspace_payload  # noqa: E402
import workspace_repo  # noqa: E402
import workspace_sync  # noqa: E402


SAMPLE_CONFIG = REPO / "activities" / "_示例活动" / "配置" / "示例活动-hang.yaml"
DEFAULT_DB = REPO / "activities" / "_db" / "投放数据.db"
OPERATOR_CONFIG = REPO / ".local" / "operator.json"


def load_owner() -> str:
    if OPERATOR_CONFIG.is_file():
        data = json.loads(OPERATOR_CONFIG.read_text(encoding="utf-8"))
        owner = str(data.get("owner") or "").strip()
        if owner:
            return owner
    return "hang"


def seed_demo(db_path: Path | str = DEFAULT_DB, today: datetime.date | None = None) -> dict:
    today = today or datetime.date.today()
    db_path = Path(db_path)

    conn = workspace_repo.connect(str(db_path))
    try:
        existing = workspace_repo.list_activities(conn)
        if existing:
            return {
                "status": "skipped",
                "reason": "数据库已有活动，不写入示例",
                "activities": [row["activity_key"] for row in existing],
            }
    finally:
        conn.close()

    owner = load_owner()
    cfg = campaign.load(SAMPLE_CONFIG)
    cfg["label"] = f"示例活动-{owner}-3类"
    cfg["campaign"]["owner"] = owner
    cfg["campaign"]["namePrefix"] = f"示例活动-{owner}"
    cfg["campaign"]["taskGroupName"] = f"示例活动-{owner}"
    cfg["campaign"]["status"] = "ended"
    cfg["campaign"]["endedAt"] = (today - datetime.timedelta(days=1)).isoformat()

    started_on = (today - datetime.timedelta(days=3)).isoformat()
    result = workspace_sync.sync_config_batch(
        str(db_path),
        cfg,
        cfg["audiences"],
        started_on,
        change_reason="首次离线示例",
        status="closed",
        created_by="operator",
    )

    conn = workspace_repo.connect(str(db_path))
    try:
        activity = workspace_repo.get_activity(conn, cfg["campaign"]["taskGroupName"])
        fetch = workspace_repo.start_fetch_run(
            conn,
            activity["id"],
            "full",
            "system",
            started_on,
            today.isoformat(),
        )
        total_exposure = 0
        total_click = 0
        for batch_id in result["batch_ids"]:
            for offset, (exposure, click) in enumerate(((1200, 4), (2400, 8), (3600, 12))):
                metric_date = (today - datetime.timedelta(days=3 - offset)).isoformat()
                workspace_repo.upsert_daily_metric(
                    conn,
                    batch_id,
                    metric_date,
                    exposure,
                    click,
                    exposure // 3,
                    max(1, click // 3),
                    fetch["id"],
                )
                total_exposure += exposure
                total_click += click

            creatives = conn.execute(
                "SELECT id FROM creative WHERE batch_id=? ORDER BY id",
                (batch_id,),
            ).fetchall()
            captured_at = (today - datetime.timedelta(days=1)).isoformat() + " 18:00:00"
            for index, creative in enumerate(creatives):
                workspace_repo.add_resource_reading(
                    conn,
                    batch_id,
                    creative["id"],
                    fetch["id"],
                    captured_at,
                    max(100, 400 - index * 80),
                    max(1, 3 - index),
                )

        workspace_repo.finish_fetch_run(
            conn,
            fetch["id"],
            "ok",
            returned_days=3,
            total_exposure=total_exposure,
            total_click=total_click,
        )
        payload = workspace_payload.build_payload(conn, activity["id"], today=today.isoformat())
        return {
            "status": "created",
            "activity": payload["activityId"],
            "display_name": payload["label"],
            "buckets": [bucket["id"] for bucket in payload["buckets"]],
            "days": payload["days"],
            "orders": len(payload["orders"]),
            "resources": len(payload["resources"]),
            "exposure": total_exposure,
            "click": total_click,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="写入脱敏示例活动")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="数据库路径")
    args = parser.parse_args()
    result = seed_demo(Path(args.db))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
