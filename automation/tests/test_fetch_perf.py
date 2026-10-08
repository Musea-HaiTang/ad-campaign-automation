# -*- coding: utf-8 -*-
"""fetch_perf 的纯函数测试（假柜台：不联网、不开浏览器、不碰后台）。

盯住两件最容易悄悄坏掉的事：
  - 日期区间：少一天/多一天都会让快照和后台对不上
  - CSV 落盘：必须是 utf-8 带 BOM（不然 Excel 双击打开中文乱码）
"""
import csv
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import fetch_perf as fp  # noqa: E402

TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_tmp")


def _tmp_csv(name):
    """临时文件写在仓库 automation/_tmp 根下（.gitignore 已忽略；沙箱写不了新建的子目录）。"""
    os.makedirs(TMP_ROOT, exist_ok=True)
    return os.path.join(TMP_ROOT, "test_%d_%s" % (os.getpid(), name))


class TestDayRange(unittest.TestCase):
    def test_single_day(self):
        self.assertEqual(fp.day_range("2026-09-14", "2026-09-14"), ["2026-09-14"])

    def test_multi_day_inclusive(self):
        self.assertEqual(fp.day_range("2026-09-14", "2026-09-16"),
                         ["2026-09-14", "2026-09-15", "2026-09-16"])

    def test_cross_month(self):
        self.assertEqual(fp.day_range("2026-09-30", "2026-10-02"),
                         ["2026-09-30", "2026-10-01", "2026-10-02"])

    def test_reversed_is_empty(self):
        self.assertEqual(fp.day_range("2026-09-15", "2026-09-14"), [])


class TestStatusText(unittest.TestCase):
    def test_known(self):
        # 后台发的是字符串（真机核对：A 类 "4" = 下线，测试工单 "1" = 进行中）
        self.assertEqual(fp.status_text("4"), "下线")
        self.assertEqual(fp.status_text("1"), "进行中")
        self.assertEqual(fp.status_text(4), "下线")          # 数字也认
        self.assertEqual(fp.status_text(1), "进行中")

    def test_unknown_kept_verbatim(self):
        self.assertEqual(fp.status_text("99"), "99")
        self.assertEqual(fp.status_text(None), "None")
        self.assertEqual(fp.status_text(""), "")


class TestPlanDays(unittest.TestCase):
    """取数区间：默认补到**昨天**（今天是半截的，归页面上的「刷新」管）。"""

    def test_empty_db_backfills_from_campaign_start(self):
        self.assertEqual(fp.plan_days(None, None, None, "2026-09-14", "2026-09-20"),
                         ("2026-09-14", "2026-09-19", "首次回填"))

    def test_incremental_refetches_last_day_as_final(self):
        # 库里最后一天是昨天（当时取的是半截）→ 再取一遍拿终值
        self.assertEqual(fp.plan_days(None, None, "2026-09-19", "2026-09-14", "2026-09-20"),
                         ("2026-09-19", "2026-09-19", "增量"))

    def test_last_day_is_today_falls_back_to_yesterday(self):
        # 今天那行是「刷新」写进去的 → 取数不该把起点排到终点后面
        self.assertEqual(fp.plan_days(None, None, "2026-09-20", "2026-09-14", "2026-09-20"),
                         ("2026-09-19", "2026-09-19", "增量"))

    def test_gap_is_filled_without_holes(self):
        self.assertEqual(fp.plan_days(None, None, "2026-09-15", "2026-09-14", "2026-09-20"),
                         ("2026-09-15", "2026-09-19", "增量"))

    def test_explicit_range_wins(self):
        self.assertEqual(fp.plan_days("2026-09-14", "2026-09-15", "2026-09-19", "2026-09-14", "2026-09-20"),
                         ("2026-09-14", "2026-09-15", "指定区间"))

    def test_refresh_today_is_just_today(self):
        self.assertEqual(fp.plan_days("2026-09-20", "2026-09-20", "2026-09-19", "2026-09-14", "2026-09-20"),
                         ("2026-09-20", "2026-09-20", "指定区间"))


class TestWriteCsv(unittest.TestCase):
    def test_roundtrip_with_bom(self):
        path = _tmp_csv("day.csv")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        fp.write_csv(["曝光时间", "任务名称", "曝光"],
                     [["2026-09-14", "A类 · 对照", 544]], path)
        with open(path, "rb") as fh:
            self.assertTrue(fh.read(3) == b"\xef\xbb\xbf")       # BOM 在
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], ["曝光时间", "任务名称", "曝光"])
        self.assertEqual(rows[1], ["2026-09-14", "A类 · 对照", "544"])

    def test_empty_rows_still_writes_header(self):
        path = _tmp_csv("empty.csv")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        fp.write_csv(["a", "b"], [], path)
        with open(path, encoding="utf-8-sig", newline="") as fh:
            self.assertEqual(list(csv.reader(fh)), [["a", "b"]])


class TestFetchResourceRows(unittest.TestCase):
    """资源级读数的**工单名必须落进库里**（2026-09-24 真踩过：清单换了形状，名字被写成空字符串，
    看板「三套文案」那张卡整块挂到空名字上）。"""

    def test_task_name_comes_from_normalised_task(self):
        def fake_call(api, method, path, payload=None):
            return {"list": [{"resourceId": 7, "experimentName": "对照组", "resourceName": "对照-6",
                              "exposure": 107, "click": 0}]}

        real_call, fp.call = fp.call, fake_call
        self.addCleanup(lambda: setattr(fp, "call", real_call))
        rows = fp.fetch_resource_rows(object(), [{"id": 1111830, "name": "A类-6", "state": "进行中"}])
        self.assertEqual(rows, [["1111830", "A类-6", "7", "对照组", "对照-6", "107", "0"]])


class TestTasksFromDayRows(unittest.TestCase):
    """工单清单直接从按天数据里拿（省掉单独一次任务组查询）。"""

    def test_keeps_first_occurrence_and_all_tasks(self):
        rows = [["2026-09-24", "1111830", "A类-6", "进行中", 107, 0, 0, 0],
                ["2026-09-24", "1111183", "A类-1", "下线", 0, 0, 0, 0],
                ["2026-09-23", "1111830", "A类-6", "进行中", 99, 1, 0, 0]]
        self.assertEqual(fp.tasks_from_day_rows(rows),
                         [{"id": "1111830", "name": "A类-6", "state": "进行中"},
                          {"id": "1111183", "name": "A类-1", "state": "下线"}])

    def test_empty(self):
        self.assertEqual(fp.tasks_from_day_rows([]), [])


class TestTasksToRead(unittest.TestCase):
    """资源级读数**只查在投的**（2026-09-24 用户定）。

    用户口径：以后会有多轮上线下线，下线工单常留残留数据，所以**不看"今天有没有量"**，
    只认状态——否则等于把带残留数据的下线工单又全捞回来。
    """

    TASKS = [{"id": "1", "name": "进行中但还没量", "state": "进行中"},
             {"id": "2", "name": "今天才下线（有量）", "state": "下线"},
             {"id": "3", "name": "早就下线（没量）", "state": "下线"}]

    def test_only_investing_tasks(self):
        self.assertEqual([t["id"] for t in fp.tasks_to_read(self.TASKS)], ["1"])

    def test_today_data_does_not_bring_offline_tasks_back(self):
        # "今天才下线（有量）"这类残留数据**不该**让它被刷（用户 2026-09-24 明确否掉这条）
        self.assertNotIn("2", [t["id"] for t in fp.tasks_to_read(self.TASKS)])

    def test_unknown_state_is_not_read(self):
        self.assertEqual(fp.tasks_to_read([{"id": "9", "name": "99", "state": "99"}]), [])


if __name__ == "__main__":
    unittest.main()
