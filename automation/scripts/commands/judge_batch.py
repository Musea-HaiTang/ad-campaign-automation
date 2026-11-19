# -*- coding: utf-8 -*-
"""从投放数据库判定当前批，并把到期复盘写入队列。"""
import argparse
import sys

from automation.scripts.data import workspace_repo
from automation.scripts.data import workspace_review


sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description="判定投放数据库中各活动的当前批")
    parser.add_argument("--db", default=workspace_repo.DB_PATH, help="投放数据库路径")
    parser.add_argument(
        "--activity",
        action="append",
        default=None,
        help="只处理指定 activity_key；可重复",
    )
    parser.add_argument(
        "--mark",
        action="store_true",
        help="把到门槛且未复盘的当前批写入 review",
    )
    parser.add_argument(
        "--brief",
        action="store_true",
        help="输出面向运营的短报",
    )
    args = parser.parse_args()

    conn = workspace_repo.connect(args.db)
    try:
        rows = workspace_repo.list_activities(conn)
        wanted = set(args.activity or [])
        if wanted:
            rows = [row for row in rows if row["activity_key"] in wanted]
        else:
            rows = [row for row in rows if row["status"] != "ended"]
        if not rows:
            print("【本轮结论】无需复盘\n【需要你处理】无\n\n【执行结果】没有进行中的活动")
            return 0
        for row in rows:
            result = workspace_review.evaluate(conn, row["id"], mark_due=args.mark)
            print(
                workspace_review.format_brief(result)
                if args.brief
                else "%s：%d 个待复盘" % (result["activity"], len(result["due"]))
            )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
