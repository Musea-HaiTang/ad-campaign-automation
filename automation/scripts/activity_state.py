# -*- coding: utf-8 -*-
"""查看和切换活动生命周期。

只管数据库 `activity.status` / `ended_on`，不操作 CSDN 后台工单。
"""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workspace_repo as repo  # noqa: E402


def _show(row):
    print("%s | %s | 开始 %s | 收尾 %s" % (
        row["activity_key"],
        "进行中" if row["status"] == "active" else "已收尾",
        row["started_on"],
        row["ended_on"] or "—",
    ))


def main():
    ap = argparse.ArgumentParser(description="活动启停（只改数据库，不动后台工单）")
    ap.add_argument("--db", default=repo.V2_DB, help="数据库路径")
    sub = ap.add_subparsers(dest="action")
    sub.add_parser("list", help="列出全部活动")
    end = sub.add_parser("end", help="收尾活动")
    end.add_argument("activity", help="activity_key")
    end.add_argument("--on", required=True, help="收尾日 YYYY-MM-DD")
    start = sub.add_parser("start", help="恢复项目内跟进")
    start.add_argument("activity", help="activity_key")
    args = ap.parse_args()

    conn = repo.connect(args.db)
    try:
        if args.action in (None, "list"):
            rows = repo.list_activities(conn)
            if not rows:
                print("数据库里没有活动")
                return
            for row in rows:
                _show(row)
            return
        if args.action == "end":
            row = repo.set_activity_status(conn, args.activity, "ended", args.on)
        else:
            row = repo.set_activity_status(conn, args.activity, "active")
        _show(row)
        print("提示：项目内状态已更新；CSDN 后台工单是否下线需另行确认。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
