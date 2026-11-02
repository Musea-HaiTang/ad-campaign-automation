# -*- coding: utf-8 -*-
"""gen_yaml 的单测：**首投的 AB 三组必须由 copies 派生**，不能是手写的第二份名字。

背景（2026-10-12 真踩到）：`abGroups[].resource` 以前手写在活动定义里，和 `resources`（naming 算的）
是两个出处；命名规则改成「产品名不加类」那天手写的那份没跟着改，生成出「新建资源没被任何 AB 行引用」。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "ad_output" / "工具"))

import gen_yaml  # noqa: E402


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
            {"role": "control", "label": "对照", "title": "标题A", "summary": "摘要A"},
            {"role": "experiment1", "label": "实验1", "title": "标题B", "summary": "摘要B"},
            {"role": "experiment2", "label": "实验2", "title": "标题C", "summary": "摘要C"},
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


def build(d, username=gen_yaml.DEFAULT_USERNAME):
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

    def test_首投生成的_abGroups_名字必须等于_resources_名字(self):
        y = build(fake_def(3))
        aud = y["audiences"][0]
        self.assertEqual(aud["reviewThresholdExposure"], 3000)
        self.assertEqual([r["name"] for r in aud["resources"]],
                         [g["resource"] for g in aud["abGroups"]])
        self.assertEqual([g["weightPct"] for g in aud["abGroups"]], [34, 33, 33])

    def test_桶里手写了_abGroups_就用它_重投复用老资源(self):
        hand = [{"label": "对照组", "resource": "老资源 · 对照", "weightPct": 34},
                {"label": "实验组1", "resource": "老资源 · 实验1", "weightPct": 33},
                {"label": "实验组2", "resource": "老资源 · 实验2", "weightPct": 33}]
        y = build(fake_def(0, abgroups=hand))
        self.assertEqual(y["audiences"][0]["abGroups"], hand)

    def test_生成器使用动态广告新控件(self):
        y = build(fake_def(3))
        controls = y["controls"]
        self.assertEqual(controls["materialPath"], ["动态广告", "其它"])
        self.assertEqual(controls["username"], "lihang")
        self.assertEqual(controls["fields"], {
            "link": {"placeholder": "请输入URL解析"},
            "title": {"placeholder": "解析自动生成标题"},
            "username": {"placeholder": "解析自动生成用户名"},
            "summary": {"placeholder": "解析自动生成描述", "type": "textarea"},
        })

    def test_用户名可由接手人覆盖(self):
        y = build(fake_def(3), username="another-user")
        self.assertEqual(y["controls"]["username"], "another-user")


if __name__ == "__main__":
    unittest.main()
