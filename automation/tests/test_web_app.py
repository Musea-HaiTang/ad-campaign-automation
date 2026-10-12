# -*- coding: utf-8 -*-
"""看板服务 `web/app.py` 的多活动部分：按活动的取数配额 + 全局串行闸。

不启 HTTP 服务、不起浏览器：只调 `start_fetch()` / `fetch_state()`；取数线程本文件里
根本不启动，所以压进队列的任务不会真的去连后台。

盯住两条（多活动最容易被悄悄弄坏的）：
  - 给 B 取数**不能吃掉 A 的「今天已取」配额**（配额按活动各算一份）；
  - 同时只跑一个（浏览器只有一只）——A 在跑时点 B、或点自己，都要被挡。
"""
import datetime
import itertools
import os
import pathlib
import shutil
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]     # automation/
REPO = ROOT.parent
TMP_ROOT = ROOT / "_tmp"                               # 临时库/流水都落这（.gitignore 里）
sys.path.insert(0, str(REPO / "web"))
sys.path.insert(0, str(ROOT / "scripts"))

import app as webapp  # noqa: E402
import perf_db  # noqa: E402

_seq = itertools.count(1)


def _item(aid, data_root):
    return {"id": aid, "label": aid + "-5类", "cfg": {}, "cfg_path": aid + ".yaml",
            "activity_dir": "", "data_root": str(data_root)}


class FetchGateTest(unittest.TestCase):
    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = TMP_ROOT / ("webapp_%d_%d" % (os.getpid(), next(_seq)))
        self.tmp.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

        webapp.DB_PATH = str(self.tmp / "投放数据.db")
        perf_db.connect(webapp.DB_PATH).close()          # 空库：两个活动都是 0 天
        webapp.ACTIVITIES = {
            "A活动-hang": _item("A活动-hang", self.tmp / "A数据"),
            "B活动-hang": _item("B活动-hang", self.tmp / "B数据"),
        }
        webapp.FETCH = {aid: webapp.new_fetch_state() for aid in webapp.ACTIVITIES}
        webapp.DEFAULT_ID = "A活动-hang"
        while not webapp.JOBS.empty():                   # 上一条测试可能压了任务，清掉
            webapp.JOBS.get()

    def _mark_fetched_today(self, aid):
        """造一份「今天取过数」的取数流水（服务靠流水文件夹名判断当天配额用没用掉）。"""
        d = pathlib.Path(webapp.ACTIVITIES[aid]["data_root"]) / (
            datetime.date.today().isoformat() + "_0939")
        d.mkdir(parents=True)
        (d / "投放数据.csv").write_text("测试用，内容无所谓", encoding="utf-8")

    def test_两个活动各有一份取数配额(self):
        self._mark_fetched_today("A活动-hang")
        code, obj = webapp.start_fetch("A活动-hang", "full")
        self.assertEqual(code, 409)                      # A 今天取过 → 挡
        self.assertTrue(obj["blocked"])
        code, _ = webapp.start_fetch("B活动-hang", "full")
        self.assertEqual(code, 202)                      # B 的配额没被 A 吃掉
        self.assertTrue(webapp.fetch_state(webapp.ACTIVITIES["B活动-hang"])["running"])
        webapp.FETCH["B活动-hang"]["running"] = False     # 收尾：别让它挂在「正在跑」

    def test_一个活动在取数时另一个被挡(self):
        webapp.FETCH["B活动-hang"]["running"] = True
        code, obj = webapp.start_fetch("A活动-hang", "full")
        self.assertEqual(code, 409)
        self.assertIn("B活动-hang", obj["error"])         # 报清楚是谁在跑
        st = webapp.fetch_state(webapp.ACTIVITIES["A活动-hang"])
        self.assertTrue(st["busy"])
        self.assertEqual(st["busyWith"], "B活动-hang")

    def test_正在取数的活动自己也不能再点(self):
        webapp.FETCH["A活动-hang"]["running"] = True
        for mode in ("full", "today"):
            code, _ = webapp.start_fetch("A活动-hang", mode)
            self.assertEqual(code, 409, mode)

    def test_不认识的活动(self):
        code, obj = webapp.start_fetch("不存在-hang", "full")
        self.assertEqual(code, 404)
        self.assertIn("不存在-hang", obj["error"])

    def test_活动登记表带库内数据现状(self):
        got = webapp.activities_payload()
        self.assertEqual(got["default"], "A活动-hang")
        self.assertEqual([a["id"] for a in got["activities"]], ["A活动-hang", "B活动-hang"])
        self.assertEqual([a["db"]["days"] for a in got["activities"]], [0, 0])   # 空库


class FetchAllTest(unittest.TestCase):
    """一次刷**全部**活动（2026-10-09 用户定）：页面的刷新 / 取数都跑登记的全部活动。

    盯住四件事：当前看的活动排头 / 取数按活动跳过分额已用的 / 全跑过就不起 /
    批次进度按活动现读 `FETCH`（不另存一份状态）。
    """

    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = TMP_ROOT / ("allfetch_%d_%d" % (os.getpid(), next(_seq)))
        self.tmp.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

        webapp.DB_PATH = str(self.tmp / "投放数据.db")
        perf_db.connect(webapp.DB_PATH).close()
        webapp.ACTIVITIES = {"A活动-hang": _item("A活动-hang", self.tmp / "A数据"),
                             "B活动-hang": _item("B活动-hang", self.tmp / "B数据")}
        webapp.FETCH = {aid: webapp.new_fetch_state() for aid in webapp.ACTIVITIES}
        webapp.DEFAULT_ID = "A活动-hang"
        while not webapp.JOBS.empty():
            webapp.JOBS.get()
        webapp.BATCH.update({"mode": None, "at": None, "ids": [], "skipped": []})
        # 测试里"跑完/在跑"是手写的，收尾必须把 running 放掉——不然会污染后面的用例
        self.addCleanup(lambda: [st.update({"running": False}) for st in webapp.FETCH.values()])
        self.addCleanup(webapp.BATCH.update, {"mode": None, "at": None, "ids": [], "skipped": []})

    def _mark_fetched_today(self, aid):
        d = pathlib.Path(webapp.ACTIVITIES[aid]["data_root"]) / (
            datetime.date.today().isoformat() + "_0939")
        d.mkdir(parents=True)
        (d / "投放数据.csv").write_text("测试用，内容无所谓", encoding="utf-8")

    def test_当前活动排头_其余按登记顺序(self):
        code, obj = webapp.start_fetch_all("today", current="B活动-hang")
        self.assertEqual(code, 202)
        self.assertEqual(obj["activities"], ["B活动-hang", "A活动-hang"])
        self.assertEqual(obj["mode"], "today")
        self.assertEqual([webapp.JOBS.get()[0] for _ in range(webapp.JOBS.qsize())],
                         ["B活动-hang", "A活动-hang"])

    def test_取数时已经取过的活动被跳过(self):
        self._mark_fetched_today("A活动-hang")
        code, obj = webapp.start_fetch_all("full", current="A活动-hang")
        self.assertEqual(code, 202)
        self.assertEqual(obj["activities"], ["B活动-hang"])          # A 今天取过 → 不重复排队
        self.assertEqual(obj["skipped"], ["A活动-hang"])
        self.assertEqual({i["activity"]: i["state"] for i in obj["batch"]["items"]},
                         {"B活动-hang": "running", "A活动-hang": "skipped"})

    def test_全部活动都取过数就不起(self):
        self._mark_fetched_today("A活动-hang")
        self._mark_fetched_today("B活动-hang")
        code, obj = webapp.start_fetch_all("full", current="A活动-hang")
        self.assertEqual(code, 409)
        self.assertTrue(obj["blocked"])
        self.assertIn("所有活动", obj["error"])

    def test_收尾的活动不算进今天已取(self):
        webapp.ACTIVITIES["B活动-hang"]["ended"] = True       # B 收尾 = 不再自动取数
        self._mark_fetched_today("A活动-hang")
        self.assertTrue(webapp.today_fetched_all())           # B 不参与，A 取过就算今天取过
        webapp.ACTIVITIES["B活动-hang"]["ended"] = False

    def _mark_ended(self, aid, day):
        webapp.ACTIVITIES[aid].update({"ended": True, "endedDay": day})

    def test_收尾的活动不进整批_但可以单独取(self):
        # 2026-10-12 用户定：整批不再带已收尾的活动（它一失败会把整批拖成"0 成功 N 失败"）
        self._mark_ended("B活动-hang", "2026-09-01")
        code, obj = webapp.start_fetch_all("today")
        self.assertEqual(code, 202)
        self.assertEqual(obj["activities"], ["A活动-hang"])
        self.assertEqual(obj["skipped"], ["B活动-hang"])
        while not webapp.JOBS.empty():                       # 测试里没人真的跑：放掉这一批
            webapp.JOBS.get()
        webapp.FETCH["A活动-hang"]["running"] = False
        code, _ = webapp.start_fetch("B活动-hang", "today")
        self.assertEqual(code, 202)                          # 单活动入口不拦：那是人明确要的

    def test_补数窗口内的收尾活动也不进整批(self):
        # 窗口内它照样自动补数（见下一条用例），但**整批**不该带上它——不然又变成"它失败整批跟着难看"
        webapp.ACTIVITIES["B活动-hang"].update(
            {"ended": True, "endedDay": datetime.date.today().isoformat()})
        self.assertFalse(webapp.fetch_stopped(webapp.ACTIVITIES["B活动-hang"]))
        code, obj = webapp.start_fetch_all("today")
        self.assertEqual(code, 202)
        self.assertEqual(obj["activities"], ["A活动-hang"])
        self.assertEqual(obj["skipped"], ["B活动-hang"])

    def test_全部活动都已收尾就不起(self):
        self._mark_ended("A活动-hang", "2026-09-01")
        self._mark_ended("B活动-hang", "2026-09-01")
        code, obj = webapp.start_fetch_all("today")
        self.assertEqual(code, 409)
        self.assertIn("已收尾", obj["error"])

    def test_收尾日之后还用两天自动补数(self):
        # 补数窗口 N=2：收尾当天 + 之后两天仍算"在跑"（数据回传有延迟），第 3 天才彻底停
        it = webapp.ACTIVITIES["B活动-hang"]
        today = datetime.date.today()
        for gap, live in ((0, True), (2, True), (3, False)):
            it.update({"ended": True,
                       "endedDay": (today - datetime.timedelta(days=gap)).isoformat()})
            self.assertEqual(webapp.fetch_stopped(it), not live, gap)
            self.assertEqual(webapp.auto_action(it) is not None, live, gap)

    def test_收尾日从已结束标记里读(self):
        d = self.tmp / "活动"
        d.mkdir()
        (d / "已结束.md").write_text(
            "# x\n\n> 规则：收尾日 + 2 天，本例 2026-10-14 是最后一天。\n\n"
            "- **收尾日**：2026-10-12（本活动投放 2026-09-14 ~ 2026-10-12）\n",
            encoding="utf-8")
        # 别抓正文里顺嘴提到的日期，也别抓成投放起始日——只认「收尾日：YYYY-MM-DD」
        self.assertEqual(webapp.ended_day(d), "2026-10-12")
        (d / "已结束.md").write_text("这份标记没写收尾日\n", encoding="utf-8")
        self.assertIsNone(webapp.ended_day(d))                # 没日期 = 立即停（保守）

    def test_取数失败提示只在登录态问题时提重登(self):
        # 2026-10-12 修：原来无条件套"登录态过期就去跑 wait_login.py"，把日期/DNS 故障指去重登
        self.assertIn("wait_login",
                      webapp.fetch_error(RuntimeError("返回不是 JSON（可能是登录态失效，跳转了登录页）")))
        self.assertNotIn("wait_login",
                         webapp.fetch_error(RuntimeError("结束日 2026-10-11 早于起始日 2026-10-12")))
        self.assertFalse(webapp.today_fetched_all())          # B 又在跑、今天没取 → 不算

    def test_批量跑着的时候再点被挡(self):
        webapp.start_fetch_all("today", current="A活动-hang")
        code, obj = webapp.start_fetch_all("today", current="A活动-hang")
        self.assertEqual(code, 409)
        self.assertIn("等这一批跑完", obj["error"])
        for st in webapp.FETCH.values():            # 两个任务中间那一瞬：没人 running、队列还排着
            st["running"] = False
        code, obj = webapp.start_fetch_all("today", current="A活动-hang")
        self.assertEqual(code, 409)
        self.assertIn("队列", obj["error"])

    def test_批次进度按活动现读状态(self):
        webapp.start_fetch_all("today", current="A活动-hang")
        webapp.FETCH["A活动-hang"].update({"running": False, "ok": True})
        st = webapp.batch_state()
        self.assertEqual([i["state"] for i in st["items"]], ["ok", "running"])
        self.assertEqual((st["okCount"], st["done"], st["total"]), (1, 1, 2))
        self.assertTrue(st["running"])
        webapp.FETCH["B活动-hang"].update({"running": False, "ok": False, "error": "登录态过期"})
        st = webapp.batch_state()
        self.assertFalse(st["running"])
        self.assertEqual((st["okCount"], st["errorCount"]), (1, 1))
        self.assertEqual([i["error"] for i in st["items"] if i["state"] == "error"], ["登录态过期"])

    @staticmethod
    def _handler(path):
        """直接调 `Handler` 的方法（不开端口、不起线程）：只验 `?all=1` 这条路走不走通。"""
        class Fake(object):
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

    def test_接口_批次进度走all参数(self):
        fake = self._handler("/api/fetch/status?all=1")
        fake.do_GET()
        code, obj = fake.sent[0]
        self.assertEqual(code, 200)
        self.assertIn("batch", obj)                 # 跨活动，不带 ?activity= 也要能问

    def test_接口_all参数下POST跑全部活动(self):
        fake = self._handler("/api/fetch?all=1&today=1&activity=B%E6%B4%BB%E5%8A%A8-hang")
        fake.do_POST()
        code, obj = fake.sent[0]
        self.assertEqual(code, 202)
        self.assertEqual(obj["activities"], ["B活动-hang", "A活动-hang"])   # 当前看的排头


class AutoRefreshTest(unittest.TestCase):
    """服务内自动刷新（2026-09-28）：每天第一次先「取数」固定昨天，之后按间隔刷今天。

    只测"该不该跑、跑哪种"这个判断；真跑取数要浏览器，归人工/真机验。
    """

    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = TMP_ROOT / ("auto_%d_%d" % (os.getpid(), next(_seq)))
        self.tmp.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.item = _item("A活动-hang", self.tmp / "数据")
        webapp.AUTO["minutes"] = 30
        webapp.AUTO["at"] = {}

    def _mark_fetched_today(self):
        """造一份今天的取数流水 = 今天已经取过数。"""
        d = self.tmp / "数据" / (datetime.date.today().isoformat() + "_0939")
        d.mkdir(parents=True)
        (d / "投放数据.csv").write_text("测试用", encoding="utf-8")

    def test_今天没取过数就先取数固定昨天(self):
        self.assertEqual(webapp.auto_action(self.item), "full")

    def test_取过数之后按间隔刷今天(self):
        self._mark_fetched_today()
        self.assertEqual(webapp.auto_action(self.item), "today")     # 自动还没跑过 → 该刷
        webapp.AUTO["at"][self.item["id"]] = datetime.datetime.now()
        self.assertIsNone(webapp.auto_action(self.item))             # 刚跑过 → 等着
        webapp.AUTO["at"][self.item["id"]] = (datetime.datetime.now() -
                                              datetime.timedelta(minutes=31))
        self.assertEqual(webapp.auto_action(self.item), "today")     # 过点了 → 再刷

    def test_手动取过数也不会让自动刷新停摆(self):
        self._mark_fetched_today()          # 手动点的"取数"，自动刷新一次都没跑过
        self.assertEqual(webapp.auto_action(self.item), "today")

    def test_间隔给0就关掉(self):
        webapp.AUTO["minutes"] = 0
        self.assertIsNone(webapp.auto_action(self.item))

    def test_收尾的活动不自动刷新(self):
        self.item["ended"] = True
        self.assertIsNone(webapp.auto_action(self.item))                     # 今天没取过也不跑
        self._mark_fetched_today()
        webapp.AUTO["at"][self.item["id"]] = (datetime.datetime.now() -
                                              datetime.timedelta(minutes=31))
        self.assertIsNone(webapp.auto_action(self.item))                     # 到点了也不跑


class TodoListTest(unittest.TestCase):
    """`/api/todo`：把**所有活动**的待复盘工单凑成一份清单（页面右上角角标 + 弹窗）。

    口径本体（在投 / 到门槛 / 没复盘）在 `test_perf_payload.Test待复盘清单` 里验；
    这里只盯"跨活动"最容易坏的四件事：哪个活动算漏了 / 算不出来的拖垮整份 / 排序 / 缓存。
    `perf_payload.build_payload` 用假的顶掉——真库真 YAML 的装配已经在别的测试里验过。
    """

    @staticmethod
    def _item(aid):
        return {"id": aid, "label": aid, "cfg": {"campaign": {"taskGroupName": aid}},
                "cfg_path": aid + ".yaml", "activity_dir": "", "data_root": ""}

    @staticmethod
    def _payload(label, task, exposure, threshold, action=False):
        """一个活动的 payload 骨架（只留 todo_rows 要看的字段）。"""
        row = {"batch": "b1", "label": "09-20 换名单", "start": "2026-09-20",
               "bucket": "B", "task": task, "exposure": exposure, "threshold": threshold,
               "click": 3, "ready": True, "pass": False, "state": "过门槛 · 未达标",
               "conclusion": "有击留、无击下，补新文案"}
        if action:
            row["action"] = {"keep": [], "drop": [], "new": 1, "note": "已处理"}
        return {"label": label, "activityId": label + "-id",
                "orders": [{"name": task, "investing": True}],
                "batches": [{"id": "b1", "label": "09-20 换名单", "suffix": "-3", "start": "2026-09-20"}],
                "batchJudge": {"b1": [row]},
                # 2026-10-08 起待办只看**每个桶自己的当前批**（桶维度），所以骨架也带上
                "buckets": [{"id": "B", "name": "B类", "color": "#000",
                             "currentBatch": "b1", "refBatch": "b1", "batches": [row]}]}

    @staticmethod
    def _payload_旧批已可判(label, task):
        """该桶当前批（b2）还没到门槛，但**上一批 b1** 早已可判——不该进清单。"""
        old = {"batch": "b1", "label": "09-20 换名单", "start": "2026-09-20", "bucket": "B",
               "task": task, "exposure": 9000, "threshold": 1500, "click": 9,
               "ready": True, "pass": True, "state": "达标", "conclusion": "停测试"}
        new = {"batch": "b2", "label": "10-08 新批", "start": "2026-10-08", "bucket": "B",
               "task": task + "-2", "exposure": 100, "threshold": 1500, "click": 0,
               "ready": False, "pass": False, "state": "未到门槛", "conclusion": "继续观察"}
        return {"label": label, "activityId": label + "-id",
                "orders": [{"name": task, "investing": True}, {"name": task + "-2", "investing": True}],
                "buckets": [{"id": "B", "name": "B类", "color": "#000",
                             "currentBatch": "b2", "refBatch": "b1", "batches": [old, new]}]}

    def test_只看每个桶自己的当前批(self):
        """上一批可判、当前批还没到门槛 → 不进清单（桶独立后的口径，2026-10-08）。"""
        self.fake_payloads["A活动-hang"] = self._payload_旧批已可判("A 活动", "A类 · x")
        self.assertEqual(webapp.todo_payload()["count"], 0)

    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = TMP_ROOT / ("todo_%d_%d" % (os.getpid(), next(_seq)))
        self.tmp.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

        webapp.DB_PATH = str(self.tmp / "投放数据.db")
        conn = perf_db.connect(webapp.DB_PATH)
        perf_db.upsert_activity(conn, "A活动-hang", "A", "A")
        perf_db.upsert_tasks(conn, "A活动-hang", [{"id": "1", "name": "A类 · x", "state": "进行中"}],
                             "2026-09-20 09:39:00")
        perf_db.upsert_daily(conn, [("1", "2026-09-19", 1, 0, 1, 0, "2026-09-20 09:39:00")])
        conn.commit()
        conn.close()

        webapp.ACTIVITIES = {"A活动-hang": self._item("A活动-hang"),
                             "B活动-hang": self._item("B活动-hang")}   # B：库里一天数据都没有
        webapp.DEFAULT_ID = "A活动-hang"
        self.calls = []

        def fake_build(cfg, conn, config_path=None):
            aid = cfg["campaign"]["taskGroupName"]
            self.calls.append(aid)
            if aid == "空活动-hang":
                raise RuntimeError("这份 YAML 坏了")
            return self.fake_payloads[aid]

        self.fake_payloads = {"A活动-hang": self._payload("A 活动", "A类 · x-3", 3000, 1500)}
        self._fake = fake_build
        self._real = webapp.pp.build_payload
        webapp.pp.build_payload = fake_build
        self.addCleanup(lambda: setattr(webapp.pp, "build_payload", self._real))
        self.addCleanup(webapp.TODO_CACHE.update, {"at": 0.0, "payload": None})
        webapp.TODO_CACHE.update({"at": 0.0, "payload": None})

    def test_清单来自所有活动_并带上活动名(self):
        out = webapp.todo_payload()
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["items"][0]["activity"], "A 活动")
        self.assertEqual(out["items"][0]["activityId"], "A 活动-id")   # 页面切活动认的是这个
        self.assertEqual(sorted(self.calls), ["A活动-hang"])        # B 库里没数据，不去装配 payload

    def test_乱了的活动被跳过_不拖垮整份清单(self):
        webapp.ACTIVITIES["空活动-hang"] = self._item("空活动-hang")
        conn = perf_db.connect(webapp.DB_PATH)                      # 库里有数据 → 真去装配 → 装配时炸
        perf_db.upsert_activity(conn, "空活动-hang", "C", "C")
        perf_db.upsert_tasks(conn, "空活动-hang", [{"id": "3", "name": "C类 · z", "state": "进行中"}],
                             "2026-09-20 09:39:00")
        perf_db.upsert_daily(conn, [("3", "2026-09-19", 1, 0, 1, 0, "2026-09-20 09:39:00")])
        conn.commit()
        conn.close()
        out = webapp.todo_payload()
        self.assertEqual(out["count"], 1)                          # C 抛异常也不影响 A 的结论
        self.assertEqual(out["items"][0]["task"], "A类 · x-3")

    def test_攒得最满的排前面(self):
        self.fake_payloads["B活动-hang"] = self._payload("B 活动", "B类 · y-3", 8000, 1500)
        # B 库里没数据 → 先用 A 的库撑一下（days() 按活动名查，所以换个活动名就够）
        conn = perf_db.connect(webapp.DB_PATH)
        perf_db.upsert_activity(conn, "B活动-hang", "B", "B")
        perf_db.upsert_tasks(conn, "B活动-hang", [{"id": "2", "name": "B类 · y", "state": "进行中"}],
                             "2026-09-20 09:39:00")
        perf_db.upsert_daily(conn, [("2", "2026-09-19", 1, 0, 1, 0, "2026-09-20 09:39:00")])
        conn.commit()
        conn.close()
        out = webapp.todo_payload()
        self.assertEqual([r["task"] for r in out["items"]], ["B类 · y-3", "A类 · x-3"])   # 8000/1500 > 3000/1500

    def test_60秒内不重算(self):
        webapp.todo_payload()
        n = len(self.calls)
        webapp.todo_payload()
        self.assertEqual(len(self.calls), n)                        # 第二次吃缓存
        webapp.TODO_CACHE["at"] = 0.0                               # 过期后重算
        webapp.todo_payload()
        self.assertGreater(len(self.calls), n)

    def test_取数正在跑的时候不吃缓存(self):
        """取数中途库是"只有一部分活动是新数"的样子 → 不吃也不写缓存（2026-10-09 修）。

        真事：2026-10-09 09:37 自动刷新跑到一半（火山已落库、KIRO 还没），页面那一下问到的是
        "1 条"、还被缓存 60 秒 —— 表格早换新了，角标还停在 1。
        """
        webapp.todo_payload()                                       # 先攒下一份缓存
        n = len(self.calls)
        webapp.FETCH["A活动-hang"]["running"] = True
        self.addCleanup(lambda: webapp.FETCH["A活动-hang"].update({"running": False}))
        out = webapp.todo_payload()
        self.assertGreater(len(self.calls), n)                      # 重算了，没吃缓存
        self.assertEqual(out["count"], 1)

    def test_新数进库后缓存作废(self):
        webapp.todo_payload()
        self.assertIsNotNone(webapp.TODO_CACHE["payload"])
        webapp.invalidate_todo()                                    # 取数线程每跑完一个活动就调它
        self.assertIsNone(webapp.TODO_CACHE["payload"])


if __name__ == "__main__":
    unittest.main()
