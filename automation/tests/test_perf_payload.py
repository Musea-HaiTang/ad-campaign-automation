# -*- coding: utf-8 -*-
"""perf_payload 的测试（假柜台：手写一个小台账库，不连后台、不开浏览器）。

盯住 2026-09-20 起的新口径：
  - 同一桶下有多条工单（B 桶：9/14 原件已下线 + `…-2` + `…-3`），**各算各的卡片**；
  - 桶级数字支持**两个口径**：`all`（含已下线）/ `investing`（只在投）；
  - `…-3` **沿用 `…-2` 的同一批资源**（文案不变、只换分发名单）→ 两份工单里资源名称一模一样，
    聚合必须按**工单**拆开，不能被资源名合并；
  - 末尾那天还没走完（partialDays）要标出来，判定不拿它当完整日。
"""
import os
import pathlib
import shutil
import sys
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import campaign  # noqa: E402
import naming  # noqa: E402
import perf_db as db  # noqa: E402
import perf_payload as pp  # noqa: E402
from test_campaign import good  # noqa: E402

TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_tmp")
ACT = "火山引擎MediaKit-hang"

CFG = {
    "label": "火山引擎MediaKit-hang-测试",
    "campaign": {"namePrefix": "火山引擎MediaKit-hang", "taskGroupName": ACT},
    "audiences": [
        {"id": "A", "topic": "AI 编程 / Agent 工具"},
        {"id": "B", "topic": "FFmpeg / 命令行音视频"},
    ],
}

BASE_B = "火山引擎MediaKit-hang-B类 · FFmpeg / 命令行音视频"
B_OLD = BASE_B          # 9/14 原件，已下线
B_2 = BASE_B + "-2"     # 9/18 换文案，沿用旧名单
B_3 = BASE_B + "-3"     # 9/20 换名单测试，资源沿用 -2 那三条
A_1 = "火山引擎MediaKit-hang-A类 · AI 编程 / Agent 工具"
D1, D2 = "2026-09-19", "2026-09-20"


class TestPayloadFromDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(TMP_ROOT, exist_ok=True)
        cls.path = os.path.join(TMP_ROOT, "test_perfpayload_%d.db" % os.getpid())
        if os.path.exists(cls.path):
            os.remove(cls.path)
        conn = db.connect(cls.path)
        db.upsert_activity(conn, ACT, "火山引擎MediaKit", CFG["label"])
        db.upsert_tasks(conn, ACT, [
            {"id": "1111183", "name": A_1, "state": "进行中"},
            {"id": "1111184", "name": B_OLD, "state": "下线"},
            {"id": "1111492", "name": B_2, "state": "进行中"},
            {"id": "1111567", "name": B_3, "state": "进行中"},
        ], "2026-09-20 15:00:00")
        db.upsert_daily(conn, [
            ("1111183", D1, 191, 0, 88, 0, "2026-09-20 15:00:00"),
            ("1111184", D1, 0, 0, 0, 0, "2026-09-20 15:00:00"),      # 已下线：数据停在 9/14
            ("1111492", D1, 113, 0, 37, 0, "2026-09-20 15:00:00"),
            ("1111567", D1, 0, 0, 0, 0, "2026-09-20 15:00:00"),
            ("1111492", D2, 63, 0, 29, 0, "2026-09-20 15:00:00"),
            ("1111567", D2, 92, 1, 30, 1, "2026-09-20 15:00:00"),
        ])
        db.add_resource_readings(conn, [
            # -2 与 -3 挂的是同一批资源名（都叫 对照-2 / 实验1-2 / 实验2-2）
            ("1111492", "4552689", "2026-09-20 15:00:00", ACT, B_2, "对照组", "…· 对照-2", 107, 0),
            ("1111492", "4552690", "2026-09-20 15:00:00", ACT, B_2, "实验组1", "…· 实验1-2", 109, 0),
            ("1111492", "4552692", "2026-09-20 15:00:00", ACT, B_2, "实验组2", "…· 实验2-2", 100, 0),
            ("1111567", "4552689", "2026-09-20 15:00:00", ACT, B_3, "对照组", "…· 对照-2", 70, 0),
            ("1111567", "4552690", "2026-09-20 15:00:00", ACT, B_3, "实验组1", "…· 实验1-2", 60, 0),
            ("1111567", "4552692", "2026-09-20 15:00:00", ACT, B_3, "实验组2", "…· 实验2-2", 55, 0),
        ])
        conn.commit()
        cls.conn = conn
        cls.data = pp.build_payload(CFG, conn, today=D2)     # 把 D2 当成"今天"（半截）

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        if os.path.exists(cls.path):
            os.remove(cls.path)

    def test_new_order_falls_into_its_bucket(self):
        """`…-B类 · …-3` 靠桶名子串归到 B 桶（不是整串相等）。"""
        o = {x["name"]: x for x in self.data["orders"]}
        self.assertEqual(o[B_3]["bucket"], "B")
        self.assertEqual((o[B_3]["e"], o[B_3]["c"]), (92, 1))

    def test_bucket_scope_all_vs_investing(self):
        """桶级两个口径：全部含已下线原件；仅在投只算 -2 / -3。"""
        all_t = pp.totals(self.data, "B", "all")
        inv = pp.totals(self.data, "B", "investing")
        self.assertEqual((all_t["e"], len(all_t["orders"])), (268, 3))
        self.assertEqual((inv["e"], len(inv["orders"])), (268, 2))      # 原件全是 0 曝光
        self.assertNotIn(B_OLD, [o["name"] for o in inv["orders"]])

    def test_each_order_has_its_own_daily_series(self):
        """逐日明细按工单拆开——前端就是靠它算两个口径的桶级数字。"""
        cells = self.data["orderCells"]
        self.assertEqual(cells[B_2][D2][0], 63)
        self.assertEqual(cells[B_3][D2][0], 92)
        self.assertEqual(self.data["days"], [D1, D2])

    def test_shared_resource_names_stay_apart(self):
        """-3 沿用 -2 的同一批资源：资源卡片按工单分块，数字不串。"""
        by_task = {t["task"]: t for t in self.data["resources"]}
        self.assertEqual([g["e"] for g in by_task[B_2]["groups"]], [107, 109, 100])
        self.assertEqual([g["e"] for g in by_task[B_3]["groups"]], [70, 60, 55])
        self.assertEqual([g["label"] for g in by_task[B_3]["groups"]], ["对照组", "实验组1", "实验组2"])

    def test_last_day_is_marked_partial(self):
        """末尾那天（今天）标成"没走完"，前端据此不算日均、不下判定。"""
        self.assertEqual(self.data["partialDays"], [D2])

    def test_桶当天的量_与网页旧算法逐日一致(self):
        """`bucketCells` 就是"按当前口径把该桶工单逐日相加"——这段原先写在网页里（2026-09-23 搬回 Python）。

        旧算法当锚点：哪天口径改了，两边必须一起动，不然页面数字会悄悄变。
        """
        bc = self.data["bucketCells"]
        self.assertEqual(tuple(bc["B"]["all"][D1]), (113, 0, 37, 0))
        self.assertEqual(tuple(bc["B"]["all"][D2]), (155, 1, 59, 1))
        self.assertEqual(tuple(bc["A"]["all"][D1]), (191, 0, 88, 0))
        self.assertEqual(tuple(bc["A"]["all"][D2]), (0, 0, 0, 0))
        for scope in ("all", "investing"):
            for bid in ("A", "B"):
                names = [o["name"] for o in self.data["orders"]
                         if o["bucket"] == bid and (scope == "all" or o["investing"])]
                for d in self.data["days"]:
                    want = [0, 0, 0, 0]
                    for n in names:
                        v = self.data["orderCells"].get(n, {}).get(d) or [0, 0, 0, 0]
                        want = [want[i] + v[i] for i in range(4)]
                    self.assertEqual(list(bc[bid][scope][d]), want, "%s %s %s" % (bid, scope, d))

    def test_有量天数_与网页旧算法一致(self):
        """`bucketDays` / `orderDays`：四项任一非零算一天；桶级同一天只算一天（日均曝光的分母）。"""
        bd = self.data["bucketDays"]
        self.assertEqual(bd["B"]["all"], [D1, D2])
        self.assertEqual(bd["B"]["investing"], [D1, D2])
        self.assertEqual(self.data["orderDays"][B_OLD], [], "全 0 的天不算有量")
        self.assertEqual(self.data["orderDays"][B_2], [D1, D2])
        for scope in ("all", "investing"):
            for bid in ("A", "B"):
                names = [o["name"] for o in self.data["orders"]
                         if o["bucket"] == bid and (scope == "all" or o["investing"])]
                want = sorted({d for n in names
                               for d, v in (self.data["orderCells"].get(n) or {}).items() if any(v)})
                self.assertEqual(bd[bid][scope], want, "%s %s" % (bid, scope))

    def test_合计_全区间与子区间同一处实现(self):
        """`totals(days=…)` 就是页面所选区间的合计；不给 days 就是全区间（命令行摘要那条路）。"""
        allt = pp.totals(self.data, "B", "all")
        self.assertEqual((allt["e"], allt["c"]), (268, 1))
        d1 = pp.totals(self.data, "B", "all", days=[D1])
        d2 = pp.totals(self.data, "B", "all", days=[D2])
        self.assertEqual((d1["e"], d2["e"]), (113, 155))
        self.assertEqual(d1["e"] + d2["e"], allt["e"], "子区间相加 = 全区间")
        self.assertEqual(pp.totals(self.data, "B", "all", days=[])["e"], 0)
        self.assertEqual(pp.totals(self.data, "没有这个桶", "all")["e"], 0, "没这个桶也不能炸")

    def test_sum_cells_纯函数(self):
        cells = {D1: (1, 2, 3, 4), D2: (10, 20, 30, 40)}
        self.assertEqual(pp.sum_cells(cells), (11, 22, 33, 44))
        self.assertEqual(pp.sum_cells(cells, [D2]), (10, 20, 30, 40))
        self.assertEqual(pp.sum_cells(cells, ["2026-09-21"]), (0, 0, 0, 0), "没数据的天算 0")
        self.assertEqual(pp.active_days(cells), [D1, D2])


B_TOPIC = "FFmpeg / 命令行音视频"


def _batch_cfg(suffix, start):
    """good() 改造成一手工批次 YAML：任务组 = 火山引擎MediaKit-hang、桶 = B。"""
    d = good()
    d["campaign"]["namePrefix"] = ACT
    d["campaign"]["taskGroupName"] = ACT
    a = d["audiences"][0]
    a["id"], a["topic"], a["taskName"] = "B", B_TOPIC, ACT + "-B类"
    if suffix:
        a["nameSuffix"] = suffix
        a["resources"] = [{"role": "experiment1", "name": ACT + "-B类 · 实验1" + suffix,
                           "title": "标题" + suffix, "summary": "摘要" + suffix}]
    d["taskOrder"]["taskGroup"] = ACT
    d["taskOrder"]["taskName"] = ACT + "-B类 · " + B_TOPIC
    d["taskOrder"]["deliveryDate"] = {"start": start, "end": "2026-10-12"}
    return d


class TestBatchScope(unittest.TestCase):
    """`batch` 口径（2026-09-28）：当前批次按工单名归批，**不看工单状态**。

    回归场景：新批工单在后台生成任务前 `workStatus = "0"`（不是"进行中"），
    只看 `investing` 会把当前一整批漏掉——页面就"没有当前批次可看"了。
    """

    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.act = pathlib.Path(TMP_ROOT) / ("batchscope_%d" % os.getpid())
        if self.act.exists():
            shutil.rmtree(str(self.act))
        (self.act / "配置").mkdir(parents=True)
        (self.act / "调整").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.act), True)
        self.cfg_path = str(self.act / "配置" / (ACT + ".yaml"))
        self._write(self.cfg_path, _batch_cfg("", "2026-09-14"))
        self._write(str(self.act / "调整" / "2026-09-20-换名单.yaml"), _batch_cfg("-3", "2026-09-20"))
        self._write(str(self.act / "配置" / "判定门槛.yaml"),
                    {"batch": "-3", "passCtr": 0.003,
                     "buckets": {"B": {"threshold": 1500, "resources": 3}}})

        self.path = os.path.join(TMP_ROOT, "test_batchscope_%d.db" % os.getpid())
        if os.path.exists(self.path):
            os.remove(self.path)
        conn = db.connect(self.path)
        db.upsert_activity(conn, ACT, "火山引擎MediaKit", "测试")
        db.upsert_tasks(conn, ACT, [{"id": "1111567", "name": B_3, "state": "0"}],
                        "2026-09-20 09:39:00")
        db.upsert_daily(conn, [("1111567", D1, 191, 3, 88, 1, "2026-09-20 09:39:00")])
        db.add_resource_readings(conn, [
            ("1111567", "r1", "2026-09-20 09:39:00", ACT, B_3, "对照组", ACT + "-B类 · 对照-3", 750, 2),
            ("1111567", "r2", "2026-09-20 09:39:00", ACT, B_3, "实验组1", ACT + "-B类 · 实验1-3", 750, 1),
            ("1111567", "r3", "2026-09-20 09:39:00", ACT, B_3, "实验组2", ACT + "-B类 · 实验2-3", 750, 0),
        ])
        conn.commit()
        self.conn = conn
        self.addCleanup(self._drop)
        self.data = pp.build_payload(CFG, conn, today=D2, config_path=self.cfg_path)

    def _drop(self):
        self.conn.close()
        if os.path.exists(self.path):
            os.remove(self.path)

    @staticmethod
    def _write(p, data):
        with open(p, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)

    def test_工单按名字归到批次(self):
        o = [x for x in self.data["orders"] if x["name"] == B_3][0]
        self.assertEqual(o["batch"], "2026-09-20-换名单")
        self.assertFalse(o["investing"])                   # state="0"：不是"进行中"

    def test_当前批次口径不看状态(self):
        self.assertEqual(self.data["currentBatch"], "2026-09-20-换名单")
        inv = self.data["bucketCells"]["B"]["investing"]                      # 旧口径：整批消失（全 0）
        self.assertEqual(sum(v[0] for v in inv.values()), 0)
        cells = self.data["bucketCells"]["B"]["batch"]                        # 新口径：照常出数
        self.assertEqual(sum(v[0] for v in cells.values()), 191)
        self.assertEqual(self.data["bucketDays"]["B"]["batch"], [D1])
        self.assertEqual([o["name"] for o in pp.scope_orders(self.data, "B", "batch")], [B_3])

    def test_文案原文索引带上批次(self):
        one = self.data["copy"][ACT + "-B类 · 实验1-3"]
        self.assertEqual((one["title"], one["summary"]), ("标题-3", "摘要-3"))
        self.assertEqual(one["batch"], "09-20 换名单")

    def test_批次之间的数据按批次聚好(self):
        rows = [s for s in self.data["batchStats"] if s["bucket"] == "B"]
        self.assertEqual([(s["batch"], s["label"], s["e"], s["c"], s["days"]) for s in rows],
                         [("2026-09-20-换名单", "09-20 换名单", 191, 3, 1)])

    def test_不给配置路径时批次维度为空(self):
        d = pp.build_payload(CFG, self.conn, today=D2)
        self.assertEqual(d["batches"], [])
        self.assertIsNone(d["currentBatch"])
        self.assertEqual(d["copy"], {})
        self.assertEqual(d["batchJudge"], {})
        self.assertEqual(d["batchStats"], [])
        self.assertTrue(all(o["batch"] is None for o in d["orders"]))

    def test_判定三列按门槛算出来(self):
        self.assertEqual(self.data["thresholds"]["passCtr"], 0.003)
        j = self.data["batchJudge"]["2026-09-20-换名单"][0]
        self.assertEqual((j["bucket"], j["exposure"], j["click"], j["threshold"], j["needClick"]),
                         ("B", 2250, 3, 1500, 7))      # 达标击数按**实际曝光**折算：2,250 × 千三 = 7
        self.assertTrue(j["ready"])
        self.assertFalse(j["pass"])                        # 3 击 < 5 击
        self.assertEqual(j["state"], "过门槛 · 未达标")
        self.assertEqual(len(j["keep"]), 2)                # 3 资源桶：幸存上限 2
        self.assertEqual(j["newCopy"], 1)                  # 空位补 1 条新文案
        self.assertEqual(j["keep"][0], ACT + "-B类 · 对照-3")   # 点击多的排前面
        self.assertEqual([g["res"] for g in j["groups"]],
                         [ACT + "-B类 · 对照-3", ACT + "-B类 · 实验1-3", ACT + "-B类 · 实验2-3"])
        self.assertTrue(j["groups"][0]["keep"])            # 保留的打在资源上，页面直接用
        # 文案原文跟着资源名取（这批只写了「实验1-3」的文案，另两条是承接的、这里没有）
        self.assertEqual({g["res"]: g["title"] for g in j["groups"]}[ACT + "-B类 · 实验1-3"], "标题-3")

    def test_每个批次都有一份判定(self):
        first = self.data["batchJudge"][ACT]              # 首批（配置/那份）：工单还没建
        self.assertIsNone(first[0]["task"])               # 页面据此显示"—"、不给展开
        self.assertEqual(first[0]["groups"], [])
        self.assertEqual(len(self.data["batchJudge"]["2026-09-20-换名单"]), 1)

    def test_没有判定门槛文件就降级(self):
        os.remove(str(self.act / "配置" / "判定门槛.yaml"))
        d = pp.build_payload(CFG, self.conn, today=D2, config_path=self.cfg_path)
        self.assertEqual(d["thresholds"], {})
        # 降级 = **不出判定**（threshold None / keep 空），但**资源级明细照出**（2026-09-28 解耦）
        row = d["batchJudge"]["2026-09-20-换名单"][0]
        self.assertIsNone(row["threshold"])
        self.assertEqual(row["keep"], [])
        self.assertEqual(row["state"], "")
        self.assertEqual(len(row["groups"]), 3)            # 没门槛也能看到三条文案
        self.assertEqual({g["res"]: g["title"] for g in row["groups"]}[ACT + "-B类 · 实验1-3"],
                         "标题-3")
        self.assertEqual(d["currentBatch"], "2026-09-20-换名单")   # 批次信息照常

    def test_没调整过就不带调整动作_页面走建议动作(self):
        """没记录 = 还没动过 → payload 不带 action，页面显示规则算出来的**建议动作**（用户 2026-09-30 定）。"""
        self.assertNotIn("action", self.data["batchJudge"]["2026-09-20-换名单"][0])

    def test_调整过就写调整动作_并顶掉规则结果(self):
        """有记录 = 已经调整过 → payload 出 `action`，**保留/下的小标也按人定的对齐**。

        用户 2026-09-30：「没调整的时候那就是建议动作，调整过了就写调整动作，这样方便我们后续看」。
        """
        p = str(self.act / "配置" / "复盘动作.yaml")
        self._write(p, {"buckets": {"-3": {"B": {
            "keep": ["实验组2"], "drop": ["对照组", "实验组1"], "new": 2,
            "at": "2026-09-20 09:39",
            "readings": {"对照组": [700, 1], "实验组1": [750, 1], "实验组2": [750, 0]},
            "note": "用户 2026-09-30 定：只留实验2"}}}})
        self.addCleanup(os.remove, p)
        j = pp.build_payload(CFG, self.conn, today=D2,
                             config_path=self.cfg_path)["batchJudge"]["2026-09-20-换名单"][0]
        self.assertEqual(j["action"], {"keep": ["实验组2"], "drop": ["对照组", "实验组1"],
                                       "new": 2, "note": "用户 2026-09-30 定：只留实验2",
                                       "at": "2026-09-20 09:39",
                                       "readings": {"对照组": [700, 1], "实验组1": [750, 1],
                                                    "实验组2": [750, 0]},
                                       # 记录里对照是 700/1，现在是 750/2 → 这条是旧时点的结论（页面报「数据已变」）
                                       "changed": ["对照组"]})
        self.assertEqual(j["keep"], [ACT + "-B类 · 实验2-3"])         # 规则本来会留对照+实验1
        self.assertEqual(j["drop"], [ACT + "-B类 · 对照-3", ACT + "-B类 · 实验1-3"])
        self.assertEqual(j["newCopy"], 2)
        self.assertEqual({g["label"]: g["keep"] for g in j["groups"]},
                         {"对照组": False, "实验组1": False, "实验组2": True})

    def test_老记录没写判定时间和读数_照出但不报数据已变(self):
        """2026-10-12 之前写的记录只有 keep/drop/new/note：照样算「调整动作」，
        但没法判断是不是过期（没有当时读数可比），所以 `changed` 空、页面不报「数据已变」。"""
        p = str(self.act / "配置" / "复盘动作.yaml")
        self._write(p, {"buckets": {"-3": {"B": {"keep": ["实验组2"],
                                                 "drop": ["对照组", "实验组1"],
                                                 "new": 0, "note": "老记录"}}}})
        self.addCleanup(os.remove, p)
        j = pp.build_payload(CFG, self.conn, today=D2,
                             config_path=self.cfg_path)["batchJudge"]["2026-09-20-换名单"][0]
        self.assertEqual(j["action"]["at"], "")
        self.assertEqual(j["action"]["readings"], {})
        self.assertEqual(j["action"]["changed"], [])


class Test待复盘清单(unittest.TestCase):
    """`todo_rows()`（用户 2026-09-30 定：「在投 + 到门槛 + 没复盘」三条都满足才算待办）。

    这条口径是页面右上角角标 / 弹窗的唯一来源（`web/app.py` 的 `/api/todo`），
    错一条就会出现"明明该判了却没提醒"或"已经处理过还一直挂着"。
    """

    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.act = pathlib.Path(TMP_ROOT) / ("todo_%d" % os.getpid())
        if self.act.exists():
            shutil.rmtree(str(self.act))
        (self.act / "配置").mkdir(parents=True)
        (self.act / "调整").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.act), True)
        self.cfg_path = str(self.act / "配置" / (ACT + ".yaml"))
        self.th_path = str(self.act / "配置" / "判定门槛.yaml")
        self.after_path = str(self.act / "配置" / "复盘动作.yaml")
        self._write(self.cfg_path, _batch_cfg("", "2026-09-14"))
        self._write(str(self.act / "调整" / "2026-09-20-换名单.yaml"), _batch_cfg("-3", "2026-09-20"))
        self._write(self.th_path, {"batch": "-3", "passCtr": 0.003,
                                   "buckets": {"B": {"threshold": 1500, "resources": 3}}})

        self.path = os.path.join(TMP_ROOT, "test_todo_%d.db" % os.getpid())
        if os.path.exists(self.path):
            os.remove(self.path)
        conn = db.connect(self.path)
        db.upsert_activity(conn, ACT, "火山引擎MediaKit", "测试")
        db.upsert_tasks(conn, ACT, [{"id": "1111567", "name": B_3, "state": "进行中"}],
                        "2026-09-20 09:39:00")
        db.upsert_daily(conn, [("1111567", D1, 191, 3, 88, 1, "2026-09-20 09:39:00")])
        db.add_resource_readings(conn, [
            ("1111567", "r1", "2026-09-20 09:39:00", ACT, B_3, "对照组", ACT + "-B类 · 对照-3", 750, 2),
            ("1111567", "r2", "2026-09-20 09:39:00", ACT, B_3, "实验组1", ACT + "-B类 · 实验1-3", 750, 1),
            ("1111567", "r3", "2026-09-20 09:39:00", ACT, B_3, "实验组2", ACT + "-B类 · 实验2-3", 750, 0),
        ])
        conn.commit()
        self.conn = conn
        # 清理顺序（addCleanup 是后进先出）：删库文件必须在关连接**之后**，
        # 否则 Windows 上文件还被占着 → PermissionError
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.addCleanup(self.conn.close)

    @staticmethod
    def _write(p, data):
        with open(p, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)

    def _payload(self):
        return pp.build_payload(CFG, self.conn, today=D2, config_path=self.cfg_path)

    def _set_state(self, state):
        db.upsert_tasks(self.conn, ACT, [{"id": "1111567", "name": B_3, "state": state}],
                        "2026-09-20 09:39:00")
        self.conn.commit()

    def test_在投_到门槛_没复盘_就进清单(self):
        rows = pp.todo_rows(self._payload())
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["bucket"], r["task"], r["exposure"], r["threshold"], r["pass"]),
                         ("B", B_3, 2250, 1500, False))          # 3 击 < 7 击（2,250 × 千三）
        self.assertEqual(r["batch"], "2026-09-20-换名单")
        self.assertEqual(r["batchLabel"], "09-20 换名单")         # 页面直接显示，不再自己算
        self.assertEqual(r["activity"], CFG["label"])
        self.assertEqual(r["activityId"], ACT)                    # 切活动要用 id，不能拿显示名比
        self.assertIn("未达标", r["state"])                       # 判定那两句原样带出来

    def test_达标了也算待办(self):
        """达标和没达标**都要动手**（一个转长期单、一个换文案），所以都进清单。"""
        db.add_resource_readings(self.conn, [
            ("1111567", "r1", "2026-09-20 10:00:00", ACT, B_3, "对照组", ACT + "-B类 · 对照-3", 750, 9),
            ("1111567", "r2", "2026-09-20 10:00:00", ACT, B_3, "实验组1", ACT + "-B类 · 实验1-3", 750, 1),
            ("1111567", "r3", "2026-09-20 10:00:00", ACT, B_3, "实验组2", ACT + "-B类 · 实验2-3", 750, 0),
        ])
        self.conn.commit()
        r = pp.todo_rows(self._payload())[0]
        self.assertTrue(r["pass"])                                # 10 击 ≥ 7 击
        self.assertEqual(r["click"], 10)

    def test_复盘过就不进清单(self):
        """`配置/复盘动作.yaml` 有这「批次后缀 × 桶」的记录 = 已经处理过（页面在写「调整动作」）。"""
        self._write(self.after_path, {"batches": {"-3": {"B": {"keep": ["实验组2"], "drop": [],
                                                             "new": 2, "note": "只留实验2"}}}})
        self.addCleanup(os.remove, self.after_path)
        self.assertEqual(pp.todo_rows(self._payload()), [])

    def test_到门槛但已下线_不进清单(self):
        self._set_state("下线")
        self.assertEqual(pp.todo_rows(self._payload()), [])

    def test_没到门槛_不进清单(self):
        self._write(self.th_path, {"batch": "-3", "passCtr": 0.003,
                                   "buckets": {"B": {"threshold": 99999, "resources": 3}}})
        self.assertEqual(pp.todo_rows(self._payload()), [])

    def test_没门槛文件的活动_清单为空(self):        # KIRO 那种：照常出数据，但没有"到门槛"这回事
        os.remove(self.th_path)
        self.assertEqual(pp.todo_rows(self._payload()), [])


class TestBucketView(unittest.TestCase):
    """桶维度（2026-10-08 用户定）：**每个桶有自己的当前批**，不是一个全局当前批。

    假数据照抄真实形状：A 桶一路跑到第三批；E 桶在第二批只写了 audience、没挂资源（七批 E 桶那种占位），
    所以它的"最后一次建批"还是首批。
    """
    CFG = {"campaign": {"namePrefix": "X", "taskGroupName": "X-hang"},
           "audiences": [{"id": "A", "topic": "AI 编程"}, {"id": "E", "topic": "图像"}]}
    PK = [("A", "X-hang-A类"), ("E", "X-hang-E类")]
    COLORS = {"A": "#111111", "E": "#222222"}
    BATCHES = [
        {"id": "b1", "label": "首批", "start": "2026-09-14", "suffix": "",
         "orders": {"A": "tA", "E": "tE"},
         "copy": {"rA": {"bucket": "A"}, "rE": {"bucket": "E"}}},
        {"id": "b2", "label": "二批", "start": "2026-09-21", "suffix": "-2",
         "orders": {"A": "tA-2", "E": "tE-2"},
         "copy": {"rA2": {"bucket": "A"}}},                     # E 只写了 audience，没挂资源
        {"id": "b3", "label": "三批", "start": "2026-09-29", "suffix": "-3",
         "orders": {"A": "tA-3"}, "copy": {"rA3": {"bucket": "A"}}},
    ]
    JUDGE = {
        "b1": [{"bucket": "A", "task": "tA", "exposure": 100, "click": 1, "ready": False},
               {"bucket": "E", "task": "tE", "exposure": 50, "click": 0, "ready": False}],
        "b2": [{"bucket": "A", "task": "tA-2", "exposure": 3000, "click": 9, "ready": True},
               {"bucket": "E", "task": "tE-2", "exposure": 0, "click": 0, "ready": False}],
        "b3": [{"bucket": "A", "task": "tA-3", "exposure": 0, "click": 0, "ready": False}],
    }
    SPECS = {"A": {"threshold": 3000}, "E": {"threshold": 1500}}

    def setUp(self):
        self.out = pp.bucket_view(self.CFG, self.PK, self.COLORS,
                                  self.BATCHES, self.JUDGE, self.SPECS)
        self.by = {b["id"]: b for b in self.out}

    def test_每个桶有自己的当前批(self):
        """A 跑到第三批、E 停在首批——这就是"桶独立"的核心。"""
        self.assertEqual(self.by["A"]["currentBatch"], "b3")
        self.assertEqual(self.by["E"]["currentBatch"], "b1")

    def test_只写audience没挂资源的批次不算建批(self):
        """七批 E 桶那种占位：不能把 E 的当前批顶到第二批去。"""
        self.assertNotEqual(self.by["E"]["currentBatch"], "b2")

    def test_回退批次取最近一次有量(self):
        """当前批还没读数时，页面用 refBatch 显示上一批的数。"""
        self.assertEqual(self.by["A"]["refBatch"], "b2")          # b3 是 0 曝光
        self.assertEqual(self.by["E"]["refBatch"], "b1")

    def test_批次史按起投日排序(self):
        self.assertEqual([x["batch"] for x in self.by["A"]["batches"]], ["b1", "b2", "b3"])
        self.assertEqual([x["batch"] for x in self.by["E"]["batches"]], ["b1", "b2"])

    def test_带上判定与文案(self):
        b2 = [x for x in self.by["A"]["batches"] if x["batch"] == "b2"][0]
        self.assertTrue(b2["ready"])
        self.assertEqual(b2["task"], "tA-2")
        self.assertEqual(self.by["A"]["threshold"], 3000)
        self.assertEqual(self.by["A"]["topic"], "AI 编程")

    def test_所有批次都没挂资源时回落到最后一个批次(self):
        batches = [dict(self.BATCHES[0], copy={}), dict(self.BATCHES[1], copy={})]
        out = pp.bucket_view(self.CFG, self.PK, self.COLORS, batches, self.JUDGE, self.SPECS)
        self.assertEqual({b["id"]: b for b in out}["A"]["currentBatch"], "b2")


if __name__ == "__main__":
    unittest.main()
