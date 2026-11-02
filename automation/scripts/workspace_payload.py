# -*- coding: utf-8 -*-
"""数据库 v2 → 现有看板 payload。"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import judging  # noqa: E402
import workspace_repo as repo  # noqa: E402

PASS_CTR = 0.003
CTR_LINE = 0.10
CLICK_FLOOR = 30
GROUP_ORDER = ["对照组", "实验组1", "实验组2"]
BUCKET_COLORS = ["#1E40AF", "#3B82F6", "#60A5FA", "#D97706", "#0F766E", "#7C3AED", "#0891B2"]
GROUP_BY_SLOT = {
    "control": "对照组",
    "experiment1": "实验组1",
    "experiment2": "实验组2",
    "single": "对照组",
}
ZERO = (0, 0, 0, 0)


def sum_cells(cells, days=None):
    vals = list(cells.values()) if days is None else [cells.get(d, ZERO) for d in days]
    return tuple(sum(v[i] for v in vals) for i in range(4))


def active_days(cells):
    return sorted(d for d, v in cells.items() if any(v))


def _inclusive_days(start, end):
    if not start or not end or end < start:
        return 0
    return (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days + 1


def _stat_row(bucket, batch_id, label, start, cells, task_days=None,
              latest_day=None, still_running=False):
    e, c, le, lc = sum_cells(cells)
    live = active_days(cells)
    task_days = sorted(task_days or [])
    run_first = task_days[0] if task_days else (live[0] if live else None)
    run_last = latest_day if still_running and run_first else (
        task_days[-1] if task_days else (live[-1] if live else None)
    )
    return {
        "bucket": bucket, "batch": batch_id, "label": label, "start": start,
        "e": e, "c": c, "le": le, "lc": lc, "days": len(live),
        "activeDays": len(live), "runDays": _inclusive_days(run_first, run_last),
        "first": live[0] if live else None, "last": live[-1] if live else None,
    }


def _payload_batch_id(bucket_key, batch_no):
    return "%s:%d" % (bucket_key, batch_no)


def _activity(conn, activity_id):
    row = conn.execute("SELECT * FROM activity WHERE id=?", (activity_id,)).fetchone()
    if row is None:
        raise ValueError("没有这个活动：%s" % activity_id)
    return dict(row)


def _batch_rows(conn, activity_id):
    return [dict(row) for row in conn.execute(
        "SELECT bb.*, b.bucket_key, b.display_name AS bucket_name, b.topic, "
        "b.default_threshold_exposure FROM bucket_batch bb "
        "JOIN bucket b ON b.id=bb.bucket_id "
        "WHERE b.activity_id=? ORDER BY bb.started_on, bb.batch_no",
        (activity_id,),
    ).fetchall()]


def _creative_map(conn, activity_id):
    rows = conn.execute(
        "SELECT c.*, bb.bucket_id FROM creative c "
        "JOIN bucket_batch bb ON bb.id=c.batch_id "
        "JOIN bucket b ON b.id=bb.bucket_id WHERE b.activity_id=? ORDER BY c.id",
        (activity_id,),
    ).fetchall()
    out = {}
    for row in rows:
        out.setdefault(row["batch_id"], []).append(dict(row))
    return out


def _latest_readings(conn, activity_id):
    rows = conn.execute(
        "SELECT rr.*, c.resource_name, c.slot FROM resource_reading rr "
        "JOIN creative c ON c.id=rr.creative_id "
        "JOIN bucket_batch bb ON bb.id=rr.batch_id "
        "JOIN bucket b ON b.id=bb.bucket_id "
        "WHERE b.activity_id=? ORDER BY rr.batch_id, rr.creative_id, rr.captured_at, rr.id",
        (activity_id,),
    ).fetchall()
    latest = {}
    for row in rows:
        latest[(row["batch_id"], row["creative_id"])] = dict(row)
    return list(latest.values())


def _reviews(conn, activity_id):
    reviews = {}
    for row in conn.execute(
        "SELECT r.* FROM review r "
        "JOIN bucket_batch bb ON bb.id=r.batch_id "
        "JOIN bucket b ON b.id=bb.bucket_id WHERE b.activity_id=?",
        (activity_id,),
    ):
        reviews[row["batch_id"]] = dict(row)
    resources = {}
    for row in conn.execute(
        "SELECT rr.*, c.resource_name, c.slot FROM review_resource rr "
        "JOIN review r ON r.id=rr.review_id "
        "JOIN creative c ON c.id=rr.creative_id "
        "JOIN bucket_batch bb ON bb.id=r.batch_id "
        "JOIN bucket b ON b.id=bb.bucket_id WHERE b.activity_id=?",
        (activity_id,),
    ):
        resources.setdefault(row["review_id"], []).append(dict(row))
    return reviews, resources


def _review_action(review, review_resources):
    if not review or review["status"] != "done":
        return None
    keep = [r["resource_name"] for r in review_resources if r["action"] == "keep"]
    drop = [r["resource_name"] for r in review_resources if r["action"] == "drop"]
    readings = {}
    for row in review_resources:
        readings[GROUP_BY_SLOT.get(row["slot"], row["slot"])] = [row["exposure"], row["click"]]
    return {
        "keep": keep,
        "drop": drop,
        "new": review["new_copy_count"],
        "note": review["report_text"],
        "at": review["triggered_at"] or "",
        "readings": readings,
    }


def build_payload(conn, activity_id, today=None):
    """按现有看板结构从 v2 装配数据。"""
    today = today or datetime.date.today().isoformat()
    activity = _activity(conn, activity_id)
    buckets = [dict(row) for row in conn.execute(
        "SELECT * FROM bucket WHERE activity_id=? ORDER BY id", (activity_id,)
    )]
    if not buckets:
        raise ValueError("活动没有桶：%s" % activity_id)
    colors = {
        bucket["bucket_key"]: BUCKET_COLORS[i % len(BUCKET_COLORS)]
        for i, bucket in enumerate(buckets)
    }
    bucket_by_id = {bucket["id"]: bucket for bucket in buckets}
    batch_rows = _batch_rows(conn, activity_id)
    batch_by_id = {batch["id"]: batch for batch in batch_rows}
    creatives = _creative_map(conn, activity_id)
    readings = _latest_readings(conn, activity_id)
    reviews, review_resources = _reviews(conn, activity_id)

    metrics_by_batch = {}
    all_days = set()
    for row in conn.execute(
        "SELECT d.* FROM daily_metric d "
        "JOIN bucket_batch bb ON bb.id=d.batch_id "
        "JOIN bucket b ON b.id=bb.bucket_id WHERE b.activity_id=? "
        "ORDER BY d.metric_date",
        (activity_id,),
    ):
        item = {
            "e": row["exposure"], "c": row["click"],
            "le": row["login_exposure"], "lc": row["login_click"],
        }
        metrics_by_batch.setdefault(row["batch_id"], {})[row["metric_date"]] = item
        all_days.add(row["metric_date"])
    days = sorted(all_days)

    orders, order_cells, stats = [], {}, []
    cells_by_bucket = {bucket["id"]: {} for bucket in buckets}
    for batch in batch_rows:
        bucket = bucket_by_id[batch["bucket_id"]]
        payload_batch = _payload_batch_id(bucket["bucket_key"], batch["batch_no"])
        series = {
            day: [item["e"], item["c"], item["le"], item["lc"]]
            for day, item in (metrics_by_batch.get(batch["id"]) or {}).items()
        }
        for day in days:
            cells_by_bucket[bucket["id"]].setdefault(day, [0, 0, 0, 0])
        active = active_days(series)
        e, c, le, lc = sum_cells(series)
        state = batch["task_state"] or ""
        task_name = batch["task_name"] or ""
        investing = state == "进行中"
        order = {
            "id": batch["task_id"] or str(batch["id"]),
            "name": task_name,
            "bucket": bucket["bucket_key"],
            "status": state,
            "state_at": batch["started_on"] or "",
            "investing": investing,
            "batch": payload_batch,
            "first": active[0] if active else None,
            "last": active[-1] if active else None,
            "active_days": len(active),
            "e": e, "c": c, "le": le, "lc": lc,
        }
        orders.append(order)
        if task_name:
            order_cells[task_name] = series
        row = _stat_row(
            bucket["bucket_key"], payload_batch,
            batch["change_reason"] or "第 %d 批" % batch["batch_no"],
            batch["started_on"], series, task_days=series.keys(),
            latest_day=today, still_running=investing,
        )
        stats.append(row)

    current_by_bucket = {}
    for bucket in buckets:
        current = conn.execute(
            "SELECT * FROM v_bucket_current WHERE bucket_id=?", (bucket["id"],)
        ).fetchone()
        ref = next((batch for batch in reversed(batch_rows)
                    if batch["bucket_id"] == bucket["id"]
                    and sum(x["e"] for x in (metrics_by_batch.get(batch["id"]) or {}).values()) > 0),
                   None)
        current_by_bucket[bucket["id"]] = (current, ref)

    bucket_cells, bucket_days = {}, {}
    for bucket in buckets:
        key = bucket["bucket_key"]
        bucket_cells[key], bucket_days[key] = {}, {}
        current = current_by_bucket[bucket["id"]][0]
        scoped = {
            "all": [b for b in batch_rows if b["bucket_id"] == bucket["id"]],
            "investing": [b for b in batch_rows if b["bucket_id"] == bucket["id"]
                          and b["task_state"] == "进行中"],
            "batch": [b for b in batch_rows if current and b["id"] == current["id"]],
        }
        for scope, batches_scope in scoped.items():
            cells = {}
            for day in days:
                values = [metrics_by_batch.get(b["id"], {}).get(day) for b in batches_scope]
                cells[day] = tuple(sum(v[k] for v in values if v) for k in ("e", "c", "le", "lc"))
            bucket_cells[key][scope] = cells
            bucket_days[key][scope] = active_days(cells)

    resources = {}
    copy = {}
    for row in readings:
        batch = batch_by_id[row["batch_id"]]
        bucket = bucket_by_id[batch["bucket_id"]]
        task = batch["task_name"] or ""
        item = resources.setdefault(task, {
            "task": task, "bucket": bucket["bucket_key"], "groups": [],
            "at": row["captured_at"] or "",
        })
        label = GROUP_BY_SLOT.get(row["slot"], row["slot"])
        item["groups"].append({
            "label": label, "res": row["resource_name"] or "",
            "e": row["exposure"], "c": row["click"],
        })
        item["at"] = max(item["at"], row["captured_at"] or "")
    for item in resources.values():
        item["groups"].sort(key=lambda g: (
            GROUP_ORDER.index(g["label"])
            if g["label"] in GROUP_ORDER else 9
        ))
    for batch_id, rows in creatives.items():
        for row in rows:
            copy.setdefault(row["resource_name"], {
                "title": row["title"], "summary": row["summary"],
                "bucket": batch_by_id[batch_id]["bucket_key"],
                "role": row["slot"],
                "batch": batch_by_id[batch_id]["change_reason"],
            })

    batch_judge = {}
    readings_by_batch = {}
    for row in readings:
        readings_by_batch.setdefault(row["batch_id"], []).append({
            "resource_name": row["resource_name"],
            "group_label": GROUP_BY_SLOT.get(row["slot"], row["slot"]),
            "exposure": row["exposure"], "click": row["click"],
            "fetched_at": row["captured_at"], "captured_at": row["captured_at"],
        })
    for batch in batch_rows:
        bucket = bucket_by_id[batch["bucket_id"]]
        payload_batch = _payload_batch_id(bucket["bucket_key"], batch["batch_no"])
        rs = readings_by_batch.get(batch["id"], [])
        spec = {
            "threshold": bucket["default_threshold_exposure"],
            "resources": max(1, len(creatives.get(batch["id"]) or [])),
        }
        j = judging.judge_one(batch["task_name"] or "", spec, PASS_CTR, rs)
        review = reviews.get(batch["id"])
        action = _review_action(review, review_resources.get(review["id"], [])) if review else None
        row = {
            "bucket": bucket["bucket_key"], "task": batch["task_name"] or "",
            "batch": payload_batch, "state": j["state"], "conclusion": j["conclusion"],
            "threshold": j["threshold"], "needClick": j["need_click"],
            "slots": j["slots"], "ready": j["ready"], "pass": j["pass"],
            "exposure": j["exposure"], "click": j["click"],
            "keep": j["keep"], "drop": j["drop"], "newCopy": j["new_copy"],
            "groups": [], "at": max((x["captured_at"] for x in rs), default=""),
        }
        for reading in sorted(rs, key=lambda x: (
            GROUP_ORDER.index(x["group_label"])
            if x["group_label"] in GROUP_ORDER else 9
        )):
            cp = copy.get(reading["resource_name"], {})
            row["groups"].append({
                "label": reading["group_label"], "res": reading["resource_name"],
                "e": reading["exposure"], "c": reading["click"],
                "keep": reading["resource_name"] in j["keep"],
                "title": cp.get("title") or "", "summary": cp.get("summary") or "",
            })
        if action:
            row["action"] = action
            row["keep"] = action["keep"]
            row["drop"] = action["drop"]
            row["newCopy"] = action["new"]
            for group in row["groups"]:
                group["keep"] = group["res"] in action["keep"]
        batch_judge[payload_batch] = [row]

    buckets_out = []
    for bucket in buckets:
        current, ref = current_by_bucket[bucket["id"]]
        current_id = (_payload_batch_id(bucket["bucket_key"], current["batch_no"])
                      if current else None)
        ref_id = (_payload_batch_id(bucket["bucket_key"], ref["batch_no"]) if ref else None)
        threshold_item = current if current else ref
        threshold_rows = []
        if threshold_item:
            threshold_rows = [x for x in readings if x["batch_id"] == threshold_item["id"]]
        buckets_out.append({
            "id": bucket["bucket_key"], "name": bucket["name"] if "name" in bucket else bucket["display_name"],
            "color": colors[bucket["bucket_key"]], "topic": bucket["topic"],
            "threshold": bucket["default_threshold_exposure"],
            "currentBatch": current_id, "refBatch": ref_id,
            "thresholdReading": ({
                "batch": threshold_item["batch_no"],
                "label": threshold_item["change_reason"] or "第 %d 批" % threshold_item["batch_no"],
                "exposure": sum(x["exposure"] for x in threshold_rows),
                "click": sum(x["click"] for x in threshold_rows),
            } if threshold_item else None),
            "batches": [
                dict(row, batch=_payload_batch_id(bucket["bucket_key"], next(
                    b["batch_no"] for b in batch_rows if b["id"] == row["id"]
                )))
                for row in []  # filled below
            ],
        })
        buckets_out[-1]["batches"] = [
            dict(batch_judge[_payload_batch_id(bucket["bucket_key"], batch["batch_no"])][0],
                 batch=_payload_batch_id(bucket["bucket_key"], batch["batch_no"]),
                 label=batch["change_reason"] or "第 %d 批" % batch["batch_no"],
                 start=batch["started_on"])
            for batch in batch_rows if batch["bucket_id"] == bucket["id"]
        ]

    current_all = max(batch_rows, key=lambda b: (b["started_on"], b["batch_no"]), default=None)
    return {
        "label": activity["display_name"],
        "activityId": activity["activity_key"],
        "source": "数据库v2",
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "partialDays": [day for day in days if day >= today],
        "ctrLine": CTR_LINE,
        "clickFloor": CLICK_FLOOR,
        "buckets": buckets_out,
        "days": days,
        "orders": orders,
        "orderCells": order_cells,
        "bucketCells": bucket_cells,
        "bucketDays": bucket_days,
        "orderDays": {name: active_days(series)
                      for name, series in order_cells.items()},
        "resources": sorted(resources.values(), key=lambda x: (x["bucket"], x["task"])),
        "batches": [{
            "id": _payload_batch_id(bucket_by_id[b["bucket_id"]]["bucket_key"], b["batch_no"]),
            "label": b["change_reason"] or "第 %d 批" % b["batch_no"],
            "suffix": "", "start": b["started_on"], "end": b["ended_on"] or "",
            "yaml": "", "orders": {bucket_by_id[b["bucket_id"]]["bucket_key"]: b["task_name"] or ""},
            "copy": {},
        } for b in batch_rows],
        "currentBatch": (_payload_batch_id(
            bucket_by_id[current_all["bucket_id"]]["bucket_key"], current_all["batch_no"]
        ) if current_all else None),
        "copy": copy,
        "thresholds": {
            "passCtr": PASS_CTR,
            "buckets": {
                bucket["bucket_key"]: {
                    "threshold": bucket["default_threshold_exposure"],
                    "resources": max(1, len([c for c in (creatives.get(b["id"]) or [])]))
                    if (b := next((x for x in reversed(batch_rows)
                                   if x["bucket_id"] == bucket["id"]), None)) else 1,
                }
                for bucket in buckets
            },
        },
        "batchJudge": batch_judge,
        "batchStats": stats,
    }


def todo_rows(conn, activity_id):
    """指定活动里 `review.status=due` 的运营待办。"""
    rows = conn.execute(
        "SELECT * FROM v_review_due WHERE activity_id=? ORDER BY triggered_at",
        (activity_id,),
    ).fetchall()
    out = []
    for row in rows:
        passed = bool(row["total_exposure"] and
                      row["total_click"] / row["total_exposure"] >= PASS_CTR)
        batch = _payload_batch_id(row["bucket_key"], row["batch_no"])
        out.append({
            "activity": row["activity_name"],
            "activityId": row["activity_key"],
            "batch": batch,
            "batchLabel": "第 %d 批" % row["batch_no"],
            "start": row["started_on"] or "",
            "bucket": row["bucket_key"],
            "task": row["task"] or "",
            "exposure": row["total_exposure"],
            "click": row["total_click"],
            "threshold": row["threshold_exposure"],
            "pass": passed,
            "state": "过门槛 · 达标" if passed else "过门槛 · 未达标",
            "conclusion": row["conclusion"] or "等待复盘",
        })
    return out
