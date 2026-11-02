# -*- coding: utf-8 -*-
"""数据库 v2 的自动复盘判断与运营短报。"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import judging  # noqa: E402
import workspace_repo as repo  # noqa: E402

PASS_CTR = 0.003
SLOT_LABEL = {
    "control": "对照组",
    "experiment1": "实验组1",
    "experiment2": "实验组2",
    "single": "对照组",
}


def _latest_readings(conn, batch_id):
    rows = conn.execute(
        "SELECT rr.*, c.resource_name, c.slot FROM resource_reading rr "
        "JOIN creative c ON c.id=rr.creative_id "
        "WHERE rr.batch_id=? ORDER BY rr.captured_at, rr.id",
        (batch_id,),
    ).fetchall()
    latest = {}
    for row in rows:
        latest[row["creative_id"]] = {
            "resource_name": row["resource_name"],
            "group_label": SLOT_LABEL.get(row["slot"], row["slot"]),
            "exposure": row["exposure"],
            "click": row["click"],
            "fetched_at": row["captured_at"],
        }
    return list(latest.values())


def evaluate(conn, activity_id, mark_due=False):
    activity = conn.execute(
        "SELECT * FROM activity WHERE id=?", (activity_id,)
    ).fetchone()
    if activity is None:
        raise ValueError("没有这个活动：%s" % activity_id)
    fetch = repo.last_successful_fetch(conn, activity_id)
    buckets = conn.execute(
        "SELECT * FROM bucket WHERE activity_id=? AND status='active' ORDER BY id",
        (activity_id,),
    ).fetchall()
    due, progress = [], []
    for bucket in buckets:
        batch = repo.get_current_batch(conn, bucket["id"])
        if batch is None or batch["task_state"] != "进行中":
            continue
        rows = _latest_readings(conn, batch["id"])
        specs = {
            "threshold": bucket["default_threshold_exposure"],
            "resources": max(1, conn.execute(
                "SELECT COUNT(*) FROM creative WHERE batch_id=?", (batch["id"],)
            ).fetchone()[0]),
        }
        judged = judging.judge_one(batch["task_name"] or "", specs, PASS_CTR, rows)
        existing = repo.get_review(conn, batch["id"])
        item = {
            "bucket": bucket["bucket_key"],
            "bucket_name": bucket["display_name"],
            "batch": "%s:%d" % (bucket["bucket_key"], batch["batch_no"]),
            "batch_no": batch["batch_no"],
            "task": batch["task_name"] or "",
            "exposure": judged["exposure"],
            "click": judged["click"],
            "threshold": judged["threshold"],
            "pass": judged["pass"],
            "state": judged["state"],
            "conclusion": judged["conclusion"],
        }
        progress.append(item)
        if judged["ready"] and existing is None:
            if mark_due:
                repo.ensure_review(
                    conn, batch["id"], fetch["id"] if fetch else None,
                    judged["threshold"], judged["exposure"], judged["click"],
                    triggered_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                )
            due.append(item)
    progress.sort(key=lambda x: (
        -(x["exposure"] / max(x["threshold"], 1)), x["bucket"]
    ))
    return {
        "activity": activity["display_name"],
        "activity_id": activity["activity_key"],
        "needs_review": bool(due),
        "due": due,
        "near": [x for x in progress if not x["state"].startswith("过门槛")][:3],
        "bucket_count": len(progress),
        "has_running_task": bool(progress),
        "data_at": fetch["finished_at"] if fetch else None,
    }


def format_brief(result):
    if not result["has_running_task"]:
        return "\n".join([
            "【本轮结论】当前没有任务进行",
            "【需要你处理】无",
            "",
            "【执行结果】成功 1 个活动 · 数据截止 %s" %
            (result["data_at"] or "—"),
            "",
            "【桶进度】无在跑任务",
        ])
    if result["needs_review"]:
        lines = ["【本轮结论】需要复盘：%d 个桶" % len(result["due"]),
                 "【需要你处理】"]
        for item in result["due"]:
            lines.append("· %s — %d / %d" % (
                item["bucket"], item["exposure"], item["threshold"]
            ))
    else:
        lines = ["【本轮结论】无需复盘", "【需要你处理】无"]
    lines += ["", "【执行结果】成功 1 个活动 · 数据截止 %s" %
              (result["data_at"] or "—"), "", "【桶进度】"]
    if result["due"]:
        lines.append("%d 个桶需要复盘" % len(result["due"]))
    else:
        lines.append("%d 个桶均未到门槛" % result["bucket_count"])
    if result["near"]:
        lines.append("最接近：")
        for item in result["near"]:
            pct = item["exposure"] / max(item["threshold"], 1) * 100
            lines.append("· %s %d / %d（%.0f%%）" % (
                item["bucket"], item["exposure"], item["threshold"], pct
            ))
    return "\n".join(lines)
