# -*- coding: utf-8 -*-
"""fetch_perf 的纯函数测试（假柜台：不联网、不开浏览器、不碰后台）。

盯住两件最容易悄悄坏掉的事：
  - 日期区间：少一天/多一天都会让快照和后台对不上
  - CSV 落盘：必须是 utf-8 带 BOM（不然 Excel 双击打开中文乱码）
"""
import datetime
import os
import shutil
import sys
import unittest
from unittest import mock

from _temp import make_temp_workdir

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import campaign  # noqa: E402
import fetch_perf as fp  # noqa: E402
import workspace_repo as repo  # noqa: E402

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
        self.assertEqual(fp.status_text("0"), "未审核")
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

    def test_campaign_starting_today_取当天(self):
        # 2026-10-12 修：**开投第一天**（起始日 = 今天）也要能取——昨天还不存在，
        # 原来的「起始日 ~ 昨天」是反区间，会抛"日期填反了"（腾讯云产品当天就是）
        self.assertEqual(fp.plan_days(None, None, None, "2026-09-20", "2026-09-20"),
                         ("2026-09-20", "2026-09-20", "首次回填（开投首日）"))

    def test_future_campaign_start_says_not_started(self):
        # 还没开投 → 说清楚"还没开始"，别去查一段未来的空区间、也别报"日期填反了"
        with self.assertRaises(RuntimeError):
            fp.plan_days(None, None, None, "2026-09-25", "2026-09-20")


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

    def test_单资源长期单回落用工单级累计(self):
        # 2026-10-13：AB测试=否 的长期单，资源级接口按"实验组"给 → 真机返回 {"total":0,"list":[]}；
        # 这种工单改从**任务组全量查询**（不给日期 = 累计值）补一条单槽位读数，别让它在看板上消失
        calls = []

        def fake_call(api, method, path, payload=None):
            calls.append(path)
            if "creativeDataByTaskId" in path:
                return {"total": 0, "list": []}
            if "taskPageList" in path:
                return {"total": 2, "list": [
                    {"id": 1112351, "taskName": "D类-长投", "workStatus": "1",
                     "exposure": 2363, "click": 1},
                    {"id": 1112342, "taskName": "A类-7", "workStatus": "1",
                     "exposure": 4141, "click": 6}]}
            raise AssertionError("没见过的请求：%s" % path)

        real_call, fp.call = fp.call, fake_call
        self.addCleanup(lambda: setattr(fp, "call", real_call))
        rows = fp.fetch_resource_rows(object(),
                                      [{"id": 1112351, "name": "D类-长投", "state": "进行中"}],
                                      task_group="KIRO鬼点子计划-hang")
        self.assertEqual(rows, [["1112351", "D类-长投", "", "对照组", "D类-长投", "2363", "1"]])
        # 兜底那次全量查询只打一次（多个长期单也只一次）
        self.assertEqual(len([c for c in calls if "taskPageList" in c]), 1)

    def test_单资源长期单的读数写YAML里那条资源名(self):
        # 2026-10-13：看板「三套文案」按**资源名**索引文案原文；写成工单名就只剩名字、看不到标题摘要
        def fake_call(api, method, path, payload=None):
            if "creativeDataByTaskId" in path:
                return {"total": 0, "list": []}
            return {"total": 1, "list": [{"id": 1112351, "taskName": "D类-长投",
                                          "workStatus": "1", "exposure": 2363, "click": 1}]}

        real_call, fp.call = fp.call, fake_call
        self.addCleanup(lambda: setattr(fp, "call", real_call))
        rows = fp.fetch_resource_rows(
            object(), [{"id": 1112351, "name": "D类-长投", "state": "进行中"}],
            task_group="KIRO鬼点子计划-hang",
            single_res={"D类-长投": "D类 · 对照-5"})
        self.assertEqual(rows, [["1112351", "D类-长投", "", "对照组", "D类 · 对照-5", "2363", "1"]])

    def test_单资源映射从数据库批次读取(self):
        tmp = make_temp_workdir("single-map-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "v2.db")
        conn = repo.connect(path)
        activity = repo.save_activity(conn, {
            "activity_key": "demo-hang", "display_name": "示例",
            "brand": "示例", "owner": "hang", "name_prefix": "demo-hang",
            "task_group_name": "demo-hang", "activity_link": "https://example.com",
            "status": "active", "started_on": "2026-10-01", "ended_on": None,
        })
        bucket = repo.save_bucket(conn, activity["id"], {
            "bucket_key": "D", "display_name": "demo-hang-D类",
            "topic": "", "target": "", "keywords_text": "",
            "default_threshold_exposure": 1000, "status": "active",
        })
        batch = repo.create_bucket_batch(conn, bucket["id"], "2026-10-01")
        conn.execute("UPDATE bucket_batch SET task_name=? WHERE id=?",
                     ("D类-长投", batch["id"]))
        repo.add_creative(conn, batch["id"], "r1", "D类 · 对照-5", "r1",
                          "", "", "", "", "single", 100)
        conn.close()
        self.assertEqual(fp.single_resource_map(path, "demo-hang"),
                         {"D类-长投": "D类 · 对照-5"})

    def test_没给任务组名就不回落(self):
        # 命令行拿不到任务组名时保持原样（宁可这条没有读数，也别猜）
        def fake_call(api, method, path, payload=None):
            return {"total": 0, "list": []}

        real_call, fp.call = fp.call, fake_call
        self.addCleanup(lambda: setattr(fp, "call", real_call))
        self.assertEqual(fp.fetch_resource_rows(
            object(), [{"id": 1112351, "name": "D类-长投", "state": "进行中"}]), [])


class TestGroupTasks(unittest.TestCase):
    def test_任务组没有任务属于永久错误(self):
        with mock.patch.object(fp, "query_tasks", return_value=[]):
            with self.assertRaises(fp.PermanentFetchError):
                fp.group_tasks(object(), "示例活动-xue")


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


class TestSyncV2(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_workdir("fetch-v2-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.config = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..",
            "activities", "_示例活动", "配置", "示例活动-hang.yaml",
        )
        self.cfg = campaign.load(self.config)
        self.tasks = [{"id": "1001", "name": "示例活动-hang-A类 · 示例人群 A / 写作辅助工具",
                       "state": "进行中"}]

    def _seed(self, path):
        conn = repo.connect(path)
        activity = repo.save_activity(conn, {
            "activity_key": "示例活动-hang", "display_name": "示例活动",
            "brand": "示例活动", "owner": "hang", "name_prefix": "示例活动-hang",
            "task_group_name": "示例活动-hang",
            "activity_link": "https://example.com/activity",
            "status": "active", "started_on": "2026-01-05", "ended_on": None,
        })
        repo.save_bucket(conn, activity["id"], {
            "bucket_key": "A", "display_name": "示例活动-hang-A类",
            "topic": "", "target": "", "keywords_text": "",
            "default_threshold_exposure": 3000, "status": "active",
        })
        conn.close()

    def test_sync_creates_v2_activity_batch_metrics_and_readings(self):
        v2_path = os.path.join(self.tmp, "v2.db")
        self._seed(v2_path)
        task_name = self.tasks[0]["name"]
        report = fp.sync_v2(
            v2_path, "示例活动-hang", self.tasks,
            [["2026-01-05", "1001", task_name, "进行中", 120, 1, 80, 1]],
            [["1001", task_name, "r1", "对照组",
              "示例活动-hang-A类 · 对照", "120", "1"]],
            "2026-01-05", "2026-01-05", "指定区间", "2026-01-05 10:00:00",
        )
        self.assertEqual(report["daily_metrics"], 1)
        self.assertEqual(report["resource_readings"], 1)
        conn = repo.connect(v2_path)
        self.addCleanup(conn.close)
        activity = repo.get_activity(conn, "示例活动-hang")
        self.assertIsNotNone(activity)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM bucket_batch WHERE task_id='1001'").fetchone()[0],
            1,
        )
        self.assertEqual(repo.last_successful_fetch(conn, activity["id"])["scope"], "full")

    def test_persist_writes_v2_only(self):
        v2_path = os.path.join(self.tmp, "v2.db")
        self._seed(v2_path)
        task_name = self.tasks[0]["name"]
        fp.persist(
            v2_path, "示例活动-hang", self.tasks,
            [["2026-01-05", "1001", task_name, "进行中", 120, 1, 80, 1]],
            [["1001", task_name, "r1", "对照组",
              "示例活动-hang-A类 · 对照", "120", "1"]],
            "2026-01-05", "2026-01-05", mode="指定区间",
            note=lambda *_: None,
        )
        v2 = repo.connect(v2_path)
        self.addCleanup(v2.close)
        self.assertEqual(v2.execute("SELECT COUNT(*) FROM daily_metric").fetchone()[0], 1)

    def test_single_day_today_is_recorded_as_refresh(self):
        day = datetime.date.today().isoformat()
        v2_path = os.path.join(self.tmp, "v2-today.db")
        self._seed(v2_path)
        task_name = self.tasks[0]["name"]
        fp.sync_v2(
            v2_path, "示例活动-hang", self.tasks,
            [[day, "1001", task_name, "进行中", 10, 0, 5, 0]],
            [["1001", task_name, "r1", "对照组",
              "示例活动-hang-A类 · 对照", "10", "0"]],
            day, day, "指定区间", day + " 10:00:00",
        )
        conn = repo.connect(v2_path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT scope FROM fetch_run").fetchone()[0], "today")


if __name__ == "__main__":
    unittest.main()
