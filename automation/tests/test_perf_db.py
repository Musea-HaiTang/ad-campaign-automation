# -*- coding: utf-8 -*-
"""perf_db（SQLite 台账）的测试（假柜台：不连后台，库里全是手写的假数据）。

盯住三条不能坏的性质：
  - **今天可反复覆盖、历史不被抹掉**（"窄区间取数顶掉真相"那类事故的根因就在这）；
  - **重拉幂等**（同一天重取两次，数字不会翻倍）；
  - **资源读数是时间序列**（每次取数追加一条，最新那条才是"整段累计"）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import perf_db as db  # noqa: E402

TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_tmp")
ACT = "火山引擎MediaKit-hang"
T1 = "1111492"
T2 = "1111567"


def _conn(name):
    os.makedirs(TMP_ROOT, exist_ok=True)
    path = os.path.join(TMP_ROOT, "test_perfdb_%d_%s.db" % (os.getpid(), name))
    if os.path.exists(path):
        os.remove(path)
    conn = db.connect(path)
    db.upsert_activity(conn, ACT, "火山引擎MediaKit", "火山引擎MediaKit-hang-5类")
    # 真实取数里工单维度先落、按天事实后落（daily 靠 task 表按活动归属），这里照做
    db.upsert_tasks(conn, ACT, [{"id": T1, "name": "B类-2", "state": "进行中"},
                               {"id": T2, "name": "B类-3", "state": "进行中"}], "2026-09-20 09:39:00")
    return conn, path


def _daily(task_id, day, e, c=0, le=0, lc=0, at="2026-09-20 09:39:00"):
    return (task_id, day, e, c, le, lc, at)


def _drop(conn, path):
    """先关连接再删文件（Windows 下开着句柄删不掉）。"""
    conn.close()
    if os.path.exists(path):
        os.remove(path)


class TestDailyUpsert(unittest.TestCase):
    def setUp(self):
        self.conn, self.path = _conn("daily")
        self.addCleanup(_drop, self.conn, self.path)

    def test_empty_db_has_no_last_day(self):
        self.assertIsNone(db.last_day(self.conn, ACT))   # 取数靠它判断"要不要全量回填"

    def test_history_kept_and_today_overwritten(self):
        db.upsert_daily(self.conn, [_daily(T1, "2026-09-19", 113, le=37)])
        db.upsert_daily(self.conn, [_daily(T1, "2026-09-20", 63, le=29, at="2026-09-20 13:00:00")])
        db.upsert_daily(self.conn, [_daily(T1, "2026-09-20", 88, le=41, at="2026-09-20 15:00:00")])
        self.assertEqual(db.days(self.conn, ACT), ["2026-09-19", "2026-09-20"])
        cells = db.order_cells(self.conn, ACT)[T1]
        self.assertEqual(cells["2026-09-19"], [113, 0, 37, 0])     # 历史没被抹
        self.assertEqual(cells["2026-09-20"], [88, 0, 41, 0])      # 今天=最新一次刷新

    def test_repeat_fetch_is_idempotent(self):
        rows = [_daily(T1, "2026-09-19", 113), _daily(T2, "2026-09-19", 0)]
        db.upsert_daily(self.conn, rows)
        db.upsert_daily(self.conn, rows)
        self.assertEqual(db.order_cells(self.conn, ACT)[T1]["2026-09-19"][0], 113)

    def test_narrow_refetch_does_not_drop_other_days(self):
        """只补 3 天的那种窄区间取数，不许影响库里其它天（今天事故的回归测试）。"""
        db.upsert_daily(self.conn, [_daily(T1, d, 100) for d in
                                    ("2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17")])
        db.upsert_daily(self.conn, [_daily(T1, "2026-09-16", 150)])
        self.assertEqual(db.days(self.conn, ACT),
                         ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17"])
        self.assertEqual(db.order_cells(self.conn, ACT)[T1]["2026-09-16"][0], 150)

    def test_last_day_drives_incremental_start(self):
        db.upsert_daily(self.conn, [_daily(T1, "2026-09-19", 113)])
        self.assertEqual(db.last_day(self.conn, ACT), "2026-09-19")


class TestTasksAndReadings(unittest.TestCase):
    def setUp(self):
        self.conn, self.path = _conn("readings")
        self.addCleanup(_drop, self.conn, self.path)

    def test_task_state_is_updated_by_later_fetch(self):
        db.upsert_tasks(self.conn, ACT, [{"id": T1, "name": "B类-2", "state": "下线"}], "2026-09-20 15:00:00")
        row = {t["task_id"]: t for t in db.tasks(self.conn, ACT)}[T1]
        self.assertEqual((row["state"], row["state_at"]), ("下线", "2026-09-20 15:00:00"))

    def test_latest_reading_per_resource_wins(self):
        db.add_resource_readings(self.conn, [
            (T1, "9", "2026-09-20 09:39:00", ACT, "B类-2", "对照组", "对照-2", 107, 0),
            (T1, "9", "2026-09-20 15:00:00", ACT, "B类-2", "对照组", "对照-2", 151, 1),
        ])
        got = db.latest_resource_readings(self.conn, ACT)
        self.assertEqual(len(got), 1)                       # 同一资源只留最新一条
        self.assertEqual((got[0]["exposure"], got[0]["click"]), (151, 1))

    def test_rewriting_same_reading_does_not_duplicate(self):
        row = (T1, "9", "2026-09-20 09:39:00", ACT, "B类-2", "对照组", "对照-2", 107, 0)
        db.add_resource_readings(self.conn, [row])
        db.add_resource_readings(self.conn, [row])
        self.assertEqual(len(db.latest_resource_readings(self.conn, ACT)), 1)

    def test_activities_are_isolated(self):
        OTHER = "另一个活动-博客T0"
        db.upsert_activity(self.conn, OTHER, "另一个活动", "另一个活动")
        db.upsert_daily(self.conn, [_daily(T1, "2026-09-19", 113)])
        self.assertEqual(db.days(self.conn, OTHER), [])   # 跨活动不串

        # 另一个活动自己的工单 + 读数，也不能串进本活动（多活动看板改造的底线，2026-09-28）
        db.upsert_tasks(self.conn, OTHER,
                        [{"id": "9001", "name": "另一个活动-A类", "state": "进行中"}],
                        "2026-09-20 09:39:00")
        db.upsert_daily(self.conn, [_daily("9001", "2026-09-19", 500)])
        db.add_resource_readings(self.conn, [("9001", "9", "2026-09-20 09:39:00", OTHER,
                                             "另一个活动-A类", "对照组", "对照-A", 500, 3)])
        self.assertEqual(db.days(self.conn, OTHER), ["2026-09-19"])
        self.assertEqual(db.days(self.conn, ACT), ["2026-09-19"])
        self.assertEqual(list(db.order_cells(self.conn, ACT)), [T1])
        self.assertEqual([t["task_name"] for t in db.tasks(self.conn, ACT)], ["B类-2", "B类-3"])
        self.assertEqual(db.latest_resource_readings(self.conn, ACT), [])
        self.assertEqual([r["resource_id"] for r in db.latest_resource_readings(self.conn, OTHER)],
                         ["9"])


if __name__ == "__main__":
    unittest.main()
