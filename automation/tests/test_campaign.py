# -*- coding: utf-8 -*-
"""campaign（整活动 YAML 装载/校验/默认值）的单测：不开浏览器、不碰活动数据。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import itertools
import os
import shutil
import sys
import types
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
REPO = ROOT.parent
TMP_ROOT = ROOT / "_tmp"                             # 临时树放这（.gitignore 里，别污染仓库根）
_tmp_seq = itertools.count(1)
sys.path.insert(0, str(ROOT / "scripts"))

import campaign  # noqa: E402


def good():
    """一份最小的合格整活动 YAML（真实活动就是它的放大版）。"""
    return {
        "version": 1,
        "adType": "blog-page-t0",
        "label": "测试hang-2类",
        "controls": {
            "channelType": "页面类",
            "channel": "PC-博客-详情页-相关推荐T0",
            "materialPath": ["静态广告", "信息流", "文本"],
            "defaults": {"businessLine": "企业服务事业部", "isPopup": False},
            "fields": {
                "title": {"placeholder": "请输入广告标题"},
                "summary": {"placeholder": "请输入广告摘要", "type": "textarea"},
                "link": {"placeholder": "请输入点击链接"},
            },
        },
        "campaign": {
            "brand": "测试",
            "owner": "hang",
            "namePrefix": "测试hang",
            "taskGroupName": "测试hang",
            "activityLink": "https://example.com/act",
        },
        "audiences": [{
            "id": "A",
            "topic": "主题A",
            "taskName": "测试hang-A类",
            "subBusinessLine": "训练营与大赛",
            "keywordGroup": {"keywords": "关键词1,关键词2"},
            "resources": [{"role": "control", "name": "测试hang-A类 · 对照",
                           "title": "标题", "summary": "摘要"}],
        }],
        "taskOrder": {
            "businessLine": "企业服务事业部",
            "taskGroup": "测试hang",
            "taskName": "测试hang-A类 · 主题A",
            "channel": "PC-博客-详情页-相关推荐T0",
            "abGroups": [{"label": "对照组", "resource": "测试hang-A类 · 对照", "weightPct": 34}],
            "price": 25,
            "deliveryDate": {"start": "2026-09-09", "end": "2026-09-11"},
        },
    }


class CampaignTest(unittest.TestCase):
    def setUp(self):
        self.base = ROOT / "_tmp" / "test_campaign"
        self.base.mkdir(parents=True, exist_ok=True)

    def write(self, data, name="c.yaml"):
        p = self.base / name
        p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return p

    def test_合格数据能装载并补默认值(self):
        d = campaign.load(self.write(good()))
        self.assertEqual(d["taskOrder"]["price"], 25)          # 价格是必填、按写的值来
        self.assertEqual(d["taskOrder"]["exposureCaps"],
                         {"daily": 100000, "weekly": 500000, "total": 500000})
        self.assertEqual(d["taskOrder"]["deliveryDate"]["mode"], "set_time")
        self.assertEqual((d["taskOrder"]["deliveryDate"]["timeStart"],
                          d["taskOrder"]["deliveryDate"]["timeEnd"]), (8, 23))

    def test_计费价格必填_不许静默补默认值(self):
        """2026-09-22 用户定：计费价格不再固定 → YAML 里不写就报错，
        绝不允许静默套用历史价（20 / 30），也不许生成器替用户选一个。"""
        d0 = good()
        del d0["taskOrder"]["price"]
        errs = campaign.validate(d0)
        self.assertTrue(any("taskOrder.price" in x for x in errs), errs)
        with self.assertRaises(ValueError):
            campaign.load(self.write(d0, name="no-price.yaml"))

    def test_写过的值不被默认值覆盖(self):
        d0 = good()
        d0["taskOrder"]["price"] = 35
        d0["taskOrder"]["exposureCaps"] = {"daily": 1, "weekly": 2, "total": 3}
        d = campaign.load(self.write(d0))
        self.assertEqual(d["taskOrder"]["price"], 35)
        self.assertEqual(d["taskOrder"]["exposureCaps"]["daily"], 1)

    def test_缺必填_一次列全所有问题(self):
        d0 = good()
        del d0["taskOrder"]["taskGroup"]
        del d0["audiences"][0]["subBusinessLine"]
        errs = campaign.validate(d0)
        self.assertEqual(len(errs), 2, errs)
        self.assertTrue(any("taskOrder.taskGroup" in e for e in errs), errs)
        self.assertTrue(any("audiences[0].subBusinessLine" in e for e in errs), errs)

    def test_投放日期是必填_不再硬编码默认日期(self):
        d0 = good()
        del d0["taskOrder"]["deliveryDate"]["end"]
        errs = campaign.validate(d0)
        self.assertTrue(any("deliveryDate.end" in e for e in errs), errs)

    def test_abGroups_必填且非空(self):
        d0 = good()
        d0["taskOrder"]["abGroups"] = []
        errs = campaign.validate(d0)
        self.assertTrue(any("abGroups" in e for e in errs), errs)

    def test_桶自带abGroups时_全局兜底可以不写(self):
        d0 = good()
        del d0["taskOrder"]["abGroups"]
        d0["audiences"][0]["abGroups"] = [{"label": "对照组", "resource": "借来的资源A", "weightPct": 34}]
        self.assertEqual(campaign.validate(d0), [])

    def test_桶abGroups字段名打错要报错(self):
        d0 = good()
        d0["audiences"][0]["abGroups"] = [{"label": "对照组", "recource": "借来的资源A", "weightPct": 34}]
        errs = campaign.validate(d0)
        self.assertTrue(any("未知字段" in x and "audiences[0].abGroups[0].recource" in x for x in errs), errs)

    def test_桶的distributionList在白名单里(self):
        d0 = good()
        d0["audiences"][0]["distributionList"] = "某测试名单"
        self.assertEqual(campaign.validate(d0), [])

    def test_没有命名来源要报错(self):
        d0 = good()
        del d0["campaign"]["namePrefix"]
        del d0["audiences"][0]["taskName"]
        errs = campaign.validate(d0)
        self.assertTrue(any("命名来源" in e for e in errs), errs)

    def test_资源缺字段要报错(self):
        d0 = good()
        del d0["audiences"][0]["resources"][0]["title"]
        errs = campaign.validate(d0)
        self.assertTrue(any("resources[0].title" in e for e in errs), errs)

    def test_桶的resources可以是空列表(self):
        # 空列表 = 本桶本轮没有新建资源、全部复用现有资源（2026-09-29 起，
        # 首个实例是 -7 批的 E 桶「3 条全留、0 条新写」）
        d0 = good()
        d0["audiences"][0]["resources"] = []
        self.assertEqual(campaign.validate(d0), [])

    def test_桶的resources不是列表要报错(self):
        d0 = good()
        d0["audiences"][0]["resources"] = None
        errs = campaign.validate(d0)
        self.assertTrue(any("audiences[0].resources" in e for e in errs), errs)

    def test_字段名打错_报未知字段并提示相近名(self):
        d0 = good()
        d0["taskOrder"]["exposureCap"] = {"daily": 1}      # 少写个 s
        errs = campaign.validate(d0)
        self.assertTrue(any("未知字段" in e and "exposureCap" in e for e in errs), errs)
        self.assertTrue(any("exposureCaps" in e for e in errs), errs)   # 提示正确写法

    def test_顶层段名打错也能看出来(self):
        d0 = good()
        d0["audiance"] = d0.pop("audiences")
        errs = campaign.validate(d0)
        self.assertTrue(any("audiance" in e for e in errs), errs)
        self.assertTrue(any("audiences" in e for e in errs), errs)

    def test_装载失败时报错信息带文件名和全部问题(self):
        d0 = good()
        d0["taskOrder"]["channel"] = ""
        p = self.write(d0, "bad.yaml")
        with self.assertRaises(ValueError) as cm:
            campaign.load(p)
        msg = str(cm.exception)
        self.assertIn("bad.yaml", msg)
        self.assertIn("taskOrder.channel", msg)

    def test_两个真实活动_YAML_都合格(self):
        for rel in ("activities/sensenova/SenseNova征文hang.yaml",
                    "activities/华为云码道/华为云码道hang.yaml"):
            p = REPO / rel
            if not p.exists():
                self.skipTest("活动数据不在：%s" % rel)
            d = campaign.load(p)
            self.assertTrue(d["audiences"], rel)
            self.assertTrue(d["taskOrder"]["abGroups"], rel)

    def test_thresholds_读写往返(self):
        cfg = self.base / "a.yaml"
        # 上一轮留下的文件会干扰「一开始是空的」这条断言，先清掉
        pathlib.Path(campaign.thresholds_path(str(cfg))).unlink(missing_ok=True)
        cfg.write_text("{}", encoding="utf-8")
        self.assertEqual(campaign.load_thresholds(str(cfg)), {})
        campaign.save_thresholds(str(cfg), {"A": {"click": 0, "exposure": 2, "count": 25393,
                                                  "status": "ok", "base": 64269}})
        self.assertEqual(campaign.load_thresholds(str(cfg))["A"]["exposure"], 2)
        self.assertTrue(str(campaign.thresholds_path(str(cfg))).endswith("a.thresholds.yaml"))


class ThresholdRecordTest(unittest.TestCase):
    """调优落点的形状只有一处：对象 / 字典都变成同一份记录（2026-09-23 收口）。

    原先两条写回路径各自拼一遍栏位、取值方式还不同（一处 `r["click"]`、一处 `r.click`），
    加一栏要改三处、漏一处还不报错。
    """

    def test_对象和字典产出同一份记录(self):
        obj = types.SimpleNamespace(click=3, exposure=1, count=262923, status="ok", base=13869)
        d = {"click": 3, "exposure": 1, "count": 262923, "status": "ok", "base": 13869}
        self.assertEqual(campaign.threshold_record(obj), campaign.threshold_record(d))
        self.assertEqual(campaign.threshold_record(obj), d)

    def test_缺栏补None_不静默丢栏(self):
        want = {"click": 1, "exposure": None, "count": None, "status": None, "base": None}
        self.assertEqual(campaign.threshold_record({"click": 1}), want)
        self.assertEqual(campaign.threshold_record(types.SimpleNamespace(click=1)), want)

    def test_栏位清单只此一处(self):
        self.assertEqual(campaign.THRESHOLD_FIELDS,
                         ("click", "exposure", "count", "status", "base"))


class TestActivityDir(unittest.TestCase):
    """活动目录解析：整活动 YAML 放在 活动/ 、活动/配置/ 、活动/调整/ 下，都要落到活动目录。

    2026-09-17 起 yaml 归到 `配置/`（当前配置）与 `调整/`（重投的那份），而 数据/ 日志/ 仍挂活动目录——
    脚本一律走这个函数，别再各自 dirname(config)。
    """

    def test_flat_yaml(self):
        cfg = REPO / "activities" / "某活动" / "某前缀.yaml"
        self.assertEqual(campaign.activity_dir(str(cfg)), str(REPO / "activities" / "某活动"))

    def test_config_folder(self):
        cfg = REPO / "activities" / "某活动" / "配置" / "某前缀.yaml"
        self.assertEqual(campaign.activity_dir(str(cfg)), str(REPO / "activities" / "某活动"))

    def test_adjust_folder(self):
        cfg = REPO / "activities" / "某活动" / "调整" / "2026-09-17-D桶换词重投.yaml"
        self.assertEqual(campaign.activity_dir(str(cfg)), str(REPO / "activities" / "某活动"))


class BatchIndexTest(unittest.TestCase):
    """批次索引（2026-09-28）：一批 = 一份整活动 YAML；工单名按 naming 算，名字后缀不是批次身份。"""

    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.act = TMP_ROOT / ("batches_%d_%d" % (os.getpid(), next(_tmp_seq)))
        (self.act / "配置").mkdir(parents=True)
        (self.act / "调整").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.act), True)
        self.cfg = self.act / "配置" / "测试-hang.yaml"
        self._write(self.cfg, self._batch("", "2026-09-09"))
        self._write(self.act / "调整" / "2026-09-24-六批.yaml", self._batch("-6", "2026-09-24"))
        self._write(self.act / "调整" / "2026-09-29-七批.yaml", self._batch("-7", "2026-09-29"))
        self._write(self.act / "配置" / "活动定义.yaml", {"a": 1})      # 生成器输入，不是批次

    @staticmethod
    def _write(p, data):
        p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    @staticmethod
    def _batch(suffix, start):
        """good() 改造成"某一批"：带名字后缀 = 本轮新写的资源。"""
        d = good()
        if suffix:
            d["audiences"][0]["nameSuffix"] = suffix
            d["audiences"][0]["resources"] = [
                {"role": "experiment1", "name": "测试hang-A类 · 实验1" + suffix,
                 "title": "标题" + suffix, "summary": "摘要" + suffix, "highlight": "飘红词"}]
        d["taskOrder"]["deliveryDate"] = {"start": start, "end": "2026-10-12"}
        return d

    def test_按起投日排序_首批在最前(self):
        got = campaign.load_batches(str(self.cfg))
        self.assertEqual([b["label"] for b in got], ["首批", "09-24 六批", "09-29 七批"])
        self.assertEqual([b["suffix"] for b in got], ["", "-6", "-7"])
        self.assertEqual(got[1]["yaml"], "调整/2026-09-24-六批.yaml")
        self.assertEqual(got[2]["start"], "2026-09-29")

    def test_每批给出工单名与本轮文案原文(self):
        got = campaign.load_batches(str(self.cfg))
        self.assertEqual(got[1]["orders"]["A"], "测试hang-A类 · 主题A-6")
        one = got[1]["copy"]["测试hang-A类 · 实验1-6"]
        self.assertEqual((one["title"], one["summary"], one["highlight"]),
                         ("标题-6", "摘要-6", "飘红词"))
        self.assertEqual(one["batch"], "09-24 六批")

    def test_文案索引跨批次合并_同名取最早那批(self):
        idx = campaign.copy_index(campaign.load_batches(str(self.cfg)))
        self.assertEqual(idx["测试hang-A类 · 对照"]["batch"], "首批")   # 「对照」是首批写的那条

    def test_装不上的文件被跳过并报出来(self):
        lines = []
        got = campaign.load_batches(str(self.cfg), log=lines.append)
        self.assertEqual(len(got), 3)
        self.assertTrue(any("活动定义.yaml" in s for s in lines), lines)

    def test_当前批次看判定门槛_没有就取最后一批(self):
        p = self.act / "配置" / "判定门槛.yaml"
        p.write_text(yaml.safe_dump({"batch": "-6", "buckets": {}}), encoding="utf-8")
        batches = campaign.load_batches(str(self.cfg))
        self.assertEqual(campaign.current_batch(batches, str(self.cfg)), "2026-09-24-六批")
        p.unlink()
        self.assertEqual(campaign.current_batch(batches, str(self.cfg)), "2026-09-29-七批")


class DiscoverTest(unittest.TestCase):
    """discover()：扫活动目录 → 能过契约的整活动 YAML 清单（2026-09-28 多活动看板用）。

    测试不碰真实活动目录——临时树里自己摆，免得别人加个活动就把这里弄红。
    """

    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        # 目录一律用 mkdir 建：`tempfile.mkdtemp` 建出来的目录在沙箱里不可写（子目录 mkdir 直接 WinError 5）
        self.root = TMP_ROOT / ("discover_%d_%d" % (os.getpid(), next(_tmp_seq)))
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.root), True)

    def _write(self, rel, cfg):
        """按 `{活动}/配置/x.yaml` 落一份 YAML（活动名随便起）。"""
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return p

    def _cfg(self, task_group, label=None):
        """good() 换个任务组名/标签 —— 就是"另一个活动"。"""
        d0 = good()
        d0["campaign"]["brand"] = task_group
        d0["campaign"]["namePrefix"] = task_group
        d0["campaign"]["taskGroupName"] = task_group
        d0["label"] = label or task_group
        return d0

    def _ids(self, **kw):
        return [a["id"] for a in campaign.discover(str(self.root), **kw)]

    def test_扫出所有能过契约的活动(self):
        self._write("A活动/配置/a.yaml", self._cfg("A活动-hang"))
        self._write("B活动/配置/b.yaml", self._cfg("B活动-hang"))
        self.assertEqual(self._ids(), ["A活动-hang", "B活动-hang"])

    def test_下划线开头的目录不入册(self):
        """示例 / 彩排 / 工具目录（`_` 开头）不混进看板的活动下拉（2026-10-08）。"""
        self._write("_示例活动/配置/x.yaml", self._cfg("示例活动-hang"))
        self._write("A活动/配置/a.yaml", self._cfg("A活动-hang"))
        self.assertEqual(self._ids(), ["A活动-hang"])

    def test_调整目录里的批次yaml不纳管(self):
        self._write("A活动/配置/a.yaml", self._cfg("A活动-hang"))
        self._write("A活动/调整/2026-09-29-七批.yaml", self._cfg("A活动-hang"))
        self.assertEqual(self._ids(), ["A活动-hang"])       # 同一个活动只出现一次

    def test_装不上的yaml被跳过并报出来(self):
        self._write("A活动/配置/a.yaml", self._cfg("A活动-hang"))
        self._write("A活动/配置/活动定义.yaml", {"a": 1})     # 生成器输入，永远过不了契约
        lines = []
        self.assertEqual(self._ids(log=lines.append), ["A活动-hang"])
        self.assertTrue(lines and "活动定义.yaml" in lines[0], lines)

    def test_同任务组撞车要报错(self):
        self._write("A活动/配置/a.yaml", self._cfg("同一个任务组"))
        self._write("B活动/配置/b.yaml", self._cfg("同一个任务组"))
        with self.assertRaises(ValueError):
            self._ids()

    def test_only指定装不上要报错(self):
        p = self._write("A活动/配置/活动定义.yaml", {"a": 1})
        with self.assertRaises(ValueError):
            campaign.discover(str(self.root), only=str(p))

    def test_返回活动根目录而不是配置子目录(self):
        self._write("A活动/配置/a.yaml", self._cfg("A活动-hang"))
        got = campaign.discover(str(self.root))
        self.assertEqual(got[0]["activity_dir"], str(self.root / "A活动"))
        self.assertEqual(got[0]["cfg_path"], str(self.root / "A活动" / "配置" / "a.yaml"))


class AfterActionsTest(unittest.TestCase):
    """复盘动作（**人定的调整**，2026-09-30 用户定）：有记录 = 页面写「调整动作」，没记录 = 回落规则「建议动作」。

    键是**被判过的那一批**的批次 id（2026-10-08 起；旧的后缀键 `''` / `-2` 仍能兜底读，2026-10-12 定下
    "记录挂在你判的那一批"这条口径）。
    """

    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.act = TMP_ROOT / ("after_%d_%d" % (os.getpid(), next(_tmp_seq)))
        (self.act / "配置").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, str(self.act), True)
        self.cfg = self.act / "配置" / "测试-hang.yaml"
        self.cfg.write_text(yaml.safe_dump(good(), allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.human = self.act / "配置" / "复盘动作.yaml"

    def _write(self, data):
        self.human.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def test_没有这份文件就返回空(self):
        self.assertEqual(campaign.load_after_actions(str(self.cfg)), {})

    def test_按批次后缀读人定动作(self):
        self._write({"batches": {"": {"A": {"keep": ["实验组1"], "drop": ["对照组", "实验组2"],
                                          "new": 2, "note": "用户定：只留实验1"}},
                                "-2": {"A": {"keep": ["实验组2"], "drop": [], "new": 0, "note": ""}}}})
        got = campaign.load_after_actions(str(self.cfg))
        self.assertEqual(got[""]["A"]["keep"], ["实验组1"])
        self.assertEqual(got[""]["A"]["new"], 2)
        self.assertEqual(got["-2"]["A"]["keep"], ["实验组2"])

    def test_判定时间与当时读数一起读出来(self):
        """`at` + `readings` 是 2026-10-12 加的：看板靠它们分「刚判的」和「几天前判的」。"""
        self._write({"buckets": {"2026-10-08-四批": {"A": {
            "keep": ["实验组2"], "drop": [], "new": 1, "at": "2026-10-09 10:24",
            "readings": {"实验组1": [1764, 0], "实验组2": [1632, 2]}, "note": "判定"}}}})
        got = campaign.load_after_actions(str(self.cfg))
        self.assertEqual(got["2026-10-08-四批"]["A"]["at"], "2026-10-09 10:24")
        self.assertEqual(got["2026-10-08-四批"]["A"]["readings"],
                         {"实验组1": [1764, 0], "实验组2": [1632, 2]})

    def test_文件坏了当成没有_不炸页面(self):
        self.human.write_text("batches: {A: [", encoding="utf-8")
        self.assertEqual(campaign.load_after_actions(str(self.cfg)), {})


if __name__ == "__main__":
    unittest.main()
