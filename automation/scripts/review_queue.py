# -*- coding: utf-8 -*-
"""数据库 v2 复盘队列：列出待复盘 review，并回写 AI 对话 ID。"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import workspace_repo

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def list_due(conn, activity_key=None):
    sql = (
        "SELECT r.id, r.thread_id, r.triggered_at, r.threshold_exposure, "
        "r.total_exposure, r.total_click, a.activity_key, a.display_name, "
        "b.bucket_key, b.display_name AS bucket_name, bb.batch_no, bb.task_name "
        "FROM review r JOIN bucket_batch bb ON bb.id=r.batch_id "
        "JOIN bucket b ON b.id=bb.bucket_id JOIN activity a ON a.id=b.activity_id "
        "WHERE r.status='due'"
    )
    args = []
    if activity_key:
        sql += " AND a.activity_key=?"
        args.append(activity_key)
    sql += " ORDER BY a.activity_key,b.id,bb.batch_no"
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


def main():
    ap = argparse.ArgumentParser(description="数据库 v2 复盘队列")
    ap.add_argument("--db", required=True)
    ap.add_argument("--activity", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    assign = sub.add_parser("assign")
    assign.add_argument("review_id", type=int)
    assign.add_argument("thread_id")
    args = ap.parse_args()
    conn = workspace_repo.connect(args.db)
    try:
        if args.cmd == "list":
            print(json.dumps(list_due(conn, args.activity), ensure_ascii=False))
        else:
            row = workspace_repo.assign_review_thread(
                conn, args.review_id, args.thread_id, status="drafting"
            )
            print("REVIEW_ASSIGNED %s %s" % (row["id"], row["thread_id"]))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
