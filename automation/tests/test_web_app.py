# -*- coding: utf-8 -*-
"""看板服务的数据库 v2 单库行为测试。

不启 HTTP 服务、不起浏览器：只验证取数串行、每日配额、收尾窗口、自动刷新、
待复盘接口和服务层路由。
"""
import datetime
import itertools
import os
import pathlib
import shutil
import sys
import unittest
from urllib.parse import quote

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
TMP_ROOT = ROOT / "_tmp"
sys.path.insert(0, str(REPO / "web"))
sys.path.insert(0, str(ROOT / "scripts"))

import app as webapp  # noqa: E402
import workspace_repo as repo  # noqa: E402

_seq = itertools.count(1)


def _tmp_dir(prefix):
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TMP_ROOT / ("%s_%d_%d" % (prefix, os.getpid(), next(_seq)))
    path.mkdir(parents=True)
    return path


def _seed_activity(db_path, key, *, threshold=1000, exposure=0, click=0,
                   due=False, ended=False):
    conn = repo.connect(str(db_path))
    try:
        activity = repo.save_activity(conn, {
            "activity_key": key,
            "display_name": key + "-5类",
            "brand": key,
            "owner": "hang",
            "name_prefix": key,
            "task_group_name": key,
            "activity_link": "https://example.com",
            "status": "ended" if ended else "active",
            "started_on": "2026-09-01",
            "ended_on": "2026-10-01" if ended else None,
        })
        bucket = repo.save_bucket(conn, activity["id"], {
            "bucket_key": "A",
            "display_name": key + "-A类",
            "topic": "",
            "target": "",
            "keywords_text": "",
            "default_threshold_exposure": threshold,
            "status": "active",
        })
        batch = repo.create_bucket_batch(
            conn, bucket["id"], "2026-09-01", status="running")
        conn.execute(
            "UPDATE bucket_batch SET task_id=?, task_name=?, task_state='进行中' WHERE id=?",
            (str(activity["id"]), key + "-A类", batch["id"]),
        )
        repo.add_creative(
            conn, batch["id"], "r1", key + "-A类 · 对照", "r1",
            "标题", "摘要", "", "", "control", 100, "running",
        )
        if exposure or click:
            fetch = repo.start_fetch_run(
                conn, activity["id"], "full", "manual",
                "2026-09-01", "2026-09-01")
            repo.finish_fetch_run(
                conn, fetch["id"], "ok", returned_days=1,
                total_exposure=exposure, total_click=click)
            repo.upsert_daily_metric(
                conn, batch["id"], "2026-09-01", exposure, click, 0, 0, fetch["id"])
            if due:
                repo.ensure_review(
                    conn, batch["id"], fetch["id"], threshold, exposure, click,
                    triggered_at="2026-09-01T10:00:00+08:00")
        return {
            "id": key, "db_id": activity["id"], "label": activity["display_name"],
            "cfg": {}, "cfg_path": "", "activity_dir": "", "data_root": None,
            "ended": ended, "endedDay": activity["ended_on"],
        }
    finally:
        conn.close()


def _mark_fetched_today(db_path, item):
    today = datetime.date.today().isoformat()
    conn = repo.connect(str(db_path))
    try:
        run = repo.start_fetch_run(conn, item["db_id"], "full", "manual", today, today)
        repo.finish_fetch_run(conn, run["id"], "ok")
    finally:
        conn.close()


class WebV2Base(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp_dir("web-v2")
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.db = self.tmp / "投放数据.db"
        self.saved = (webapp.ACTIVITIES, webapp.DEFAULT_ID, webapp.FETCH,
                      webapp.DB_PATH, webapp.BATCH, webapp.AUTO)
        self.addCleanup(self._restore)
        webapp.DB_PATH = str(self.db)
        webapp.AUTO.update({"minutes": 30, "at": {}})
        webapp.BATCH.update({"mode": None, "at": None, "ids": [], "skipped": []})
        while not webapp.JOBS.empty():
            webapp.JOBS.get()

    def _restore(self):
        (webapp.ACTIVITIES, webapp.DEFAULT_ID, webapp.FETCH,
         webapp.DB_PATH, webapp.BATCH, webapp.AUTO) = self.saved

    def _two_activities(self, **b_overrides):
        a = _seed_activity(self.db, "A活动-hang")
        b = _seed_activity(self.db, "B活动-hang", **b_overrides)
        webapp.ACTIVITIES = {"A活动-hang": a, "B活动-hang": b}
        webapp.DEFAULT_ID = "A活动-hang"
        webapp.FETCH = {key: webapp.new_fetch_state() for key in webapp.ACTIVITIES}
        self.addCleanup(lambda: [st.update({"running": False})
                                 for st in webapp.FETCH.values()])
        return a, b


class FetchGateTest(WebV2Base):
    def test_两个活动各有一份今日取数配额(self):
        a, _ = self._two_activities()
        _mark_fetched_today(self.db, a)
        code, obj = webapp.start_fetch("A活动-hang", "full")
        self.assertEqual(code, 409)
        self.assertTrue(obj["blocked"])
        code, _ = webapp.start_fetch("B活动-hang", "full")
        self.assertEqual(code, 202)

    def test_一个活动在取数时另一个被挡(self):
        self._two_activities()
        webapp.FETCH["B活动-hang"]["running"] = True
        code, obj = webapp.start_fetch("A活动-hang", "full")
        self.assertEqual(code, 409)
        self.assertIn("B活动-hang", obj["error"])
        state = webapp.fetch_state(webapp.ACTIVITIES["A活动-hang"])
        self.assertTrue(state["busy"])
        self.assertEqual(state["busyWith"], "B活动-hang")

    def test_正在取数的活动自己也不能再点(self):
        self._two_activities()
        webapp.FETCH["A活动-hang"]["running"] = True
        for mode in ("full", "today"):
            code, _ = webapp.start_fetch("A活动-hang", mode)
            self.assertEqual(code, 409, mode)

    def test_不认识的活动(self):
        self._two_activities()
        code, obj = webapp.start_fetch("不存在-hang", "full")
        self.assertEqual(code, 404)
        self.assertIn("不存在-hang", obj["error"])

    def test_活动登记表带库内数据现状(self):
        self._two_activities()
        got = webapp.activities_payload()
        self.assertEqual(got["default"], "A活动-hang")
        self.assertEqual([a["db"]["days"] for a in got["activities"]], [0, 0])


class FetchAllTest(WebV2Base):
    def test_当前活动排头_其余按登记顺序(self):
        self._two_activities()
        code, obj = webapp.start_fetch_all("today", current="B活动-hang")
        self.assertEqual(code, 202)
        self.assertEqual(obj["activities"], ["B活动-hang", "A活动-hang"])
        self.assertEqual(obj["mode"], "today")
        self.assertEqual(
            [webapp.JOBS.get()[0] for _ in range(webapp.JOBS.qsize())],
            ["B活动-hang", "A活动-hang"],
        )

    def test_已经取过的活动被跳过(self):
        a, _ = self._two_activities()
        _mark_fetched_today(self.db, a)
        code, obj = webapp.start_fetch_all("full", current="A活动-hang")
        self.assertEqual(code, 202)
        self.assertEqual(obj["activities"], ["B活动-hang"])
        self.assertEqual(obj["skipped"], ["A活动-hang"])

    def test_全部活动都取过数就不起(self):
        a, b = self._two_activities()
        _mark_fetched_today(self.db, a)
        _mark_fetched_today(self.db, b)
        code, obj = webapp.start_fetch_all("full", current="A活动-hang")
        self.assertEqual(code, 409)
        self.assertIn("所有活动", obj["error"])

    def test_收尾活动不进整批_但可以单独取(self):
        a = _seed_activity(self.db, "A活动-hang")
        b = _seed_activity(self.db, "B活动-hang", ended=True)
        webapp.ACTIVITIES = {"A活动-hang": a, "B活动-hang": b}
        webapp.DEFAULT_ID = "A活动-hang"
        webapp.FETCH = {key: webapp.new_fetch_state() for key in webapp.ACTIVITIES}
        code, obj = webapp.start_fetch_all("today")
        self.assertEqual(code, 202)
        self.assertEqual(obj["activities"], ["A活动-hang"])
        self.assertEqual(obj["skipped"], ["B活动-hang"])
        webapp.FETCH["A活动-hang"]["running"] = False
        while not webapp.JOBS.empty():
            webapp.JOBS.get()
        code, _ = webapp.start_fetch("B活动-hang", "today")
        self.assertEqual(code, 202)

    def test_批次进度按活动现读状态(self):
        self._two_activities()
        webapp.start_fetch_all("today", current="A活动-hang")
        webapp.FETCH["A活动-hang"].update({"running": False, "ok": True})
        state = webapp.batch_state()
        self.assertEqual([item["state"] for item in state["items"]], ["ok", "running"])
        self.assertEqual((state["okCount"], state["done"], state["total"]), (1, 1, 2))

    def test_取数失败提示只在登录态问题时提重登(self):
        self.assertIn(
            "wait_login",
            webapp.fetch_error(RuntimeError("返回不是 JSON，可能是登录态失效")),
        )
        self.assertNotIn(
            "wait_login",
            webapp.fetch_error(RuntimeError("结束日早于起始日")),
        )

    @staticmethod
    def _handler(path):
        class Fake:
            def __init__(self):
                self.path = path
                self.sent = []

            def _json(self, code, obj):
                self.sent.append((code, obj))

            def _send(self, code, body, ctype=""):
                self.sent.append((code, body))

        Fake.do_GET = webapp.Handler.do_GET
        Fake.do_POST = webapp.Handler.do_POST
        return Fake()

    def test_接口_all参数下POST跑全部活动(self):
        self._two_activities()
        fake = self._handler(
            "/api/fetch?all=1&today=1&activity=" + quote("B活动-hang"))
        fake.do_POST()
        code, obj = fake.sent[0]
        self.assertEqual(code, 202)
        self.assertEqual(obj["activities"], ["B活动-hang", "A活动-hang"])


class AutoRefreshTest(WebV2Base):
    def test_今天没取过数就先取数(self):
        item = _seed_activity(self.db, "A活动-hang")
        self.assertEqual(webapp.auto_action(item), "full")

    def test_取过数之后按间隔刷今天(self):
        item = _seed_activity(self.db, "A活动-hang")
        _mark_fetched_today(self.db, item)
        self.assertEqual(webapp.auto_action(item), "today")
        webapp.AUTO["at"][item["id"]] = datetime.datetime.now()
        self.assertIsNone(webapp.auto_action(item))
        webapp.AUTO["at"][item["id"]] = (
            datetime.datetime.now() - datetime.timedelta(minutes=31))
        self.assertEqual(webapp.auto_action(item), "today")

    def test_间隔给0就关掉(self):
        item = _seed_activity(self.db, "A活动-hang")
        webapp.AUTO["minutes"] = 0
        self.assertIsNone(webapp.auto_action(item))

    def test_收尾活动不自动刷新(self):
        item = _seed_activity(self.db, "A活动-hang", ended=True)
        item["endedDay"] = "2026-09-01"
        self.assertIsNone(webapp.auto_action(item))


class V2PayloadAndTodoTest(WebV2Base):
    def test_数据库启停无需重启服务(self):
        a = _seed_activity(self.db, "A活动-hang")
        webapp.ACTIVITIES = {"A活动-hang": a}
        webapp.DEFAULT_ID = "A活动-hang"
        conn = repo.connect(str(self.db))
        repo.set_activity_status(conn, "A活动-hang", "ended", "2026-10-28")
        conn.close()
        webapp.refresh_activity_statuses()
        self.assertTrue(a["ended"])
        self.assertEqual(a["endedDay"], "2026-10-28")

    def test_活动状态与取数凭据来自数据库(self):
        a = _seed_activity(
            self.db, "A活动-hang", exposure=1200, click=4, due=True)
        webapp.ACTIVITIES = {"A活动-hang": a}
        webapp.DEFAULT_ID = "A活动-hang"
        webapp.FETCH = {"A活动-hang": webapp.new_fetch_state()}
        state = webapp.fetch_state(a)
        self.assertEqual(state["db"]["last"], "2026-09-01")
        self.assertFalse(state["running"])
        self.assertEqual(len(webapp.snapshot_names(a)), 1)
        self.assertEqual(webapp.todo_payload()["count"], 1)

    def test_收尾活动不进待复盘(self):
        a = _seed_activity(
            self.db, "A活动-hang", exposure=1200, click=4, due=True, ended=True)
        webapp.ACTIVITIES = {"A活动-hang": a}
        webapp.DEFAULT_ID = "A活动-hang"
        webapp.FETCH = {"A活动-hang": webapp.new_fetch_state()}
        self.assertEqual(webapp.todo_payload()["count"], 0)


if __name__ == "__main__":
    unittest.main()
