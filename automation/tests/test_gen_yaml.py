# -*- coding: utf-8 -*-
"""gen_yaml 的单测：**首投的 AB 三组必须由 copies 派生**，不能是手写的第二份名字。

背景（2026-10-12 真踩到）：`abGroups[].resource` 以前手写在活动定义里，和 `resources`（naming 算的）
是两个出处；命名规则改成「产品名不加类」那天手写的那份没跟着改，生成出「新建资源没被任何 AB 行引用」。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import json
from copy import deepcopy
import sys
import unittest
from unittest import mock

import yaml

from _temp import temp_workdir

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "ad_output" / "工具"))

import gen_yaml  # noqa: E402

TEST_USERNAME = "sample-user"


def fake_def(n_copies=3, abgroups=None):
    """最小可用的活动定义：一个桶 × n 份文案。"""
    bucket = {
        "id": "WorkBuddy企业版",
        "name": "WorkBuddy 企业版",
        "audience": "企业里的研发团队",
        "topic": "WorkBuddy 企业版（腾讯企业智能体）",
        "keywords": "CodeBuddy,WorkBuddy",
        "reviewThresholdExposure": 3000,
        "kwNote": "测试",
        "copies": [
            {"role": "control", "label": "对照", "title": "标题A", "summary": "摘要A",
             "angleKey": "A-1", "presentationType": "direct_marketing",
             "styleKey": "regular", "validationSlot": "first_test"},
            {"role": "experiment1", "label": "实验1", "title": "标题B", "summary": "摘要B",
             "angleKey": "A-2", "presentationType": "disguised_post",
             "styleKey": "adaptation", "validationSlot": "first_test"},
            {"role": "experiment2", "label": "实验2", "title": "标题C", "summary": "摘要C",
             "angleKey": "A-3", "presentationType": "direct_marketing",
             "styleKey": "antithesis", "validationSlot": "first_test"},
        ][:n_copies],
    }
    if abgroups is not None:
        bucket["abGroups"] = abgroups
    return {
        "activity": {"title": "标题", "subtitle": "副标题", "ruleText": ""},
        "campaign": {"brand": "腾讯云产品", "owner": "hang", "namePrefix": "腾讯云产品-hang",
                     "taskGroupName": "腾讯云产品-hang",
                     "activityLink": "https://example.com/invite"},
        "buckets": [bucket],
        "subBusinessLine": "训练营与大赛",
        "taskOrder": {
            "businessLine": "企业服务事业部", "taskGroup": "腾讯云产品-hang",
            "channel": "PC博客详情页-新模版-T0", "price": 30,
            "channelSizeId": "后台点渠道自动带上",
            "deliveryDate": {"mode": "set_time", "start": "2026-10-12", "end": "2026-10-31",
                             "timeStart": 8, "timeEnd": 23},
            "exposureCaps": {"daily": 100000, "weekly": 500000, "total": 500000},
        },
    }


def build(d, username=TEST_USERNAME):
    """跑一遍生成器的装配（`gen_yaml.build` 直接返回 dict，不落盘、不碰后台）。"""
    return gen_yaml.build(d, username=username)


class DeriveAbGroupsTest(unittest.TestCase):
    def test_三条资源_派生对照组三分之一(self):
        res = [{"role": "control", "name": "N · 对照", "title": "t", "summary": "s"},
               {"role": "experiment1", "name": "N · 实验1", "title": "t", "summary": "s"},
               {"role": "experiment2", "name": "N · 实验2", "title": "t", "summary": "s"}]
        self.assertEqual(gen_yaml.derive_ab_groups(res), [
            {"label": "对照组", "resource": "N · 对照", "weightPct": 34},
            {"label": "实验组1", "resource": "N · 实验1", "weightPct": 33},
            {"label": "实验组2", "resource": "N · 实验2", "weightPct": 33},
        ])

    def test_两条资源_五五开(self):
        res = [{"role": "control", "name": "N · 对照", "title": "t", "summary": "s"},
               {"role": "experiment1", "name": "N · 实验1", "title": "t", "summary": "s"}]
        self.assertEqual([g["weightPct"] for g in gen_yaml.derive_ab_groups(res)], [50, 50])

    def test_认不出的组合不猜(self):
        one = [{"role": "control", "name": "N · 对照", "title": "t", "summary": "s"}]
        self.assertEqual(gen_yaml.derive_ab_groups(one), [])
        self.assertEqual(gen_yaml.derive_ab_groups([]), [])

    def test_单资源模式_一条资源自动派生对照组(self):
        d = fake_def(1)
        d["taskOrder"]["abTest"] = False
        y = build(d)
        groups = y["audiences"][0]["abGroups"]
        self.assertEqual(groups, [{
            "label": "对照组",
            "resource": y["audiences"][0]["resources"][0]["name"],
        }])
        self.assertNotIn("weightPct", groups[0])
        self.assertEqual(gen_yaml.campaign.validate(y), [])

    def test_单资源模式_多条资源且未手写分组时拒绝生成(self):
        d = fake_def(2)
        d["taskOrder"]["abTest"] = False
        with self.assertRaisesRegex(SystemExit, "copies 不是正好 1 份"):
            build(d)

    def test_首投生成的_abGroups_名字必须等于_resources_名字(self):
        y = build(fake_def(3))
        aud = y["audiences"][0]
        self.assertEqual(aud["reviewThresholdExposure"], 3000)
        self.assertEqual([r["name"] for r in aud["resources"]],
                         [g["resource"] for g in aud["abGroups"]])
        self.assertEqual([g["weightPct"] for g in aud["abGroups"]], [34, 33, 33])
        self.assertEqual(aud["resources"][0]["angleKey"], "A-1")
        self.assertEqual(aud["resources"][0]["presentationType"], "direct_marketing")
        self.assertEqual(aud["resources"][0]["styleKey"], "regular")
        self.assertEqual(aud["resources"][0]["validationSlot"], "first_test")

    def test_桶里手写了_abGroups_就用它_重投复用老资源(self):
        hand = [{"label": "对照组", "resource": "老资源 · 对照", "weightPct": 34},
                {"label": "实验组1", "resource": "老资源 · 实验1", "weightPct": 33},
                {"label": "实验组2", "resource": "老资源 · 实验2", "weightPct": 33}]
        y = build(fake_def(0, abgroups=hand))
        self.assertEqual(y["audiences"][0]["abGroups"], hand)

    def test_单资源开关原样带入执行YAML(self):
        hand = [{"label": "对照组", "resource": "老资源 · 对照"}]
        d = fake_def(1, abgroups=hand)
        d["taskOrder"]["abTest"] = False
        y = build(d)
        self.assertIs(y["taskOrder"]["abTest"], False)
        self.assertEqual(gen_yaml.campaign.validate(y), [])

    def test_混合资源桶逐桶推导AB模式(self):
        d = fake_def(3)
        single = deepcopy(d["buckets"][0])
        single["id"] = "B"
        single["name"] = "B 桶"
        single["audience"] = "单资源人群"
        single["topic"] = "单资源主题"
        single["copies"] = single["copies"][:1]
        d["buckets"].append(single)

        y = build(d)
        multi, one = y["audiences"]
        self.assertIs(multi["abTest"], True)
        self.assertEqual(len(multi["abGroups"]), 3)
        self.assertIs(one["abTest"], False)
        self.assertEqual(one["abGroups"], [{
            "label": "对照组",
            "resource": one["resources"][0]["name"],
        }])
        self.assertEqual(gen_yaml.campaign.validate(y), [])

    def test_新文案缺分类字段时拒绝生成(self):
        d = fake_def(2)
        del d["buckets"][0]["copies"][0]["styleKey"]
        with self.assertRaisesRegex(SystemExit, "styleKey"):
            build(d)

    def test_生成器使用动态广告新控件(self):
        y = build(fake_def(3))
        controls = y["controls"]
        self.assertEqual(controls["materialPath"], ["动态广告", "其它"])
        self.assertEqual(controls["username"], TEST_USERNAME)
        self.assertEqual(controls["fields"], {
            "link": {"placeholder": "请输入URL解析"},
            "title": {"placeholder": "解析自动生成标题"},
            "username": {"placeholder": "解析自动生成用户名"},
            "summary": {"placeholder": "解析自动生成描述", "type": "textarea"},
        })

    def test_用户名可由接手人覆盖(self):
        y = build(fake_def(3), username="another-user")
        self.assertEqual(y["controls"]["username"], "another-user")

    def test_省略参数时读取操作者配置的用户名(self):
        with temp_workdir("gen-yaml-default-") as tmp:
            config = pathlib.Path(tmp) / "operator.json"
            config.write_text(json.dumps({"owner": "ops", "ad_username": "login-user"}), encoding="utf-8")
            with mock.patch.object(gen_yaml, "OPERATOR_CONFIG", config):
                self.assertEqual(gen_yaml.resolve_username(), "login-user")

    def test_命令行用户名优先于操作者配置(self):
        with temp_workdir("gen-yaml-explicit-") as tmp:
            config = pathlib.Path(tmp) / "operator.json"
            config.write_text(json.dumps({"owner": "ops", "ad_username": "login-user"}), encoding="utf-8")
            with mock.patch.object(gen_yaml, "OPERATOR_CONFIG", config):
                self.assertEqual(gen_yaml.resolve_username("explicit-user"), "explicit-user")

    def test_缺少登录用户名时拒绝生成(self):
        with temp_workdir("gen-yaml-missing-") as tmp:
            config = pathlib.Path(tmp) / "operator.json"
            config.write_text(json.dumps({"owner": "ops", "ad_username": None}), encoding="utf-8")
            with mock.patch.object(gen_yaml, "OPERATOR_CONFIG", config):
                with self.assertRaisesRegex(SystemExit, "ad_username"):
                    gen_yaml.resolve_username()


if __name__ == "__main__":
    unittest.main()
