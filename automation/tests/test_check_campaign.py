# -*- coding: utf-8 -*-
"""check_campaign 的名字解析单测（纯函数，不起浏览器）。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
sys.path.insert(0, str(ROOT / "scripts"))

import check_campaign  # noqa: E402
import naming  # noqa: E402

CAMP = {"namePrefix": "火山引擎MediaKit-hang"}


class ExpectedUserObjectNameTest(unittest.TestCase):
    """客群名 / 分发名单名：`distributionList` 优先，没有才按命名规则算。"""

    def test_重投复用旧名单时按_distributionList_核对(self):
        """B 桶 2026-09-18 重投：名单是旧的（不带 -2），按命名规则算会误报缺失。"""
        aud = {"id": "B", "topic": "FFmpeg / 命令行音视频", "nameSuffix": "-2",
               "distributionList": "火山引擎MediaKit-hang-B类 · FFmpeg / 命令行音视频"}
        self.assertEqual(check_campaign.expected_user_object_name(CAMP, aud),
                         "火山引擎MediaKit-hang-B类 · FFmpeg / 命令行音视频")

    def test_没写_distributionList_才按命名规则带后缀(self):
        aud = {"id": "D", "topic": "短视频 / 内容生产", "nameSuffix": "-2"}
        self.assertEqual(check_campaign.expected_user_object_name(CAMP, aud),
                         "火山引擎MediaKit-hang-D类 · 短视频 / 内容生产-2")

    def test_普通轮次不带后缀(self):
        aud = {"id": "A", "topic": "AI 编程 / Agent 工具"}
        self.assertEqual(check_campaign.expected_user_object_name(CAMP, aud),
                         "火山引擎MediaKit-hang-A类 · AI 编程 / Agent 工具")

    def test_工单名不受_distributionList_影响(self):
        """复用旧名单 ≠ 复用旧工单：重投建的仍是新工单，名字带 -2。"""
        aud = {"id": "B", "topic": "FFmpeg / 命令行音视频", "nameSuffix": "-2",
               "distributionList": "火山引擎MediaKit-hang-B类 · FFmpeg / 命令行音视频"}
        self.assertEqual(naming.order_task_name(CAMP, aud),
                         "火山引擎MediaKit-hang-B类 · FFmpeg / 命令行音视频-2")


class DeletedAudienceTest(unittest.TestCase):
    """客群已删、分发名单还在 → 降级成提示、不算缺失（用户 2026-09-23 口径）。

    真事（2026-09-23 火山引擎MediaKit D 桶）：圈选任务被删掉，分发名单还在——
    工单认的是名单，投放不受影响，但体检一直报"缺失 1 项"、退出码 1，把门禁拉红了。
    """

    NAME = "火山引擎MediaKit-hang-D类 · 短视频 / 内容生产-2"

    def test_名单还在_降级成提示不算缺失(self):
        notes, real = check_campaign.split_deleted_audiences(
            [self.NAME], "别的名单\n%s\n还有一行" % self.NAME)
        self.assertEqual(real, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("分发名单还在", notes[0])
        self.assertIn(self.NAME, notes[0])

    def test_名单也没了_仍算缺失(self):
        notes, real = check_campaign.split_deleted_audiences([self.NAME], "全是别人的名单")
        self.assertEqual(notes, [])
        self.assertEqual(real, [self.NAME])

    def test_只降级名单在的那些_其余照算缺失(self):
        gone = "SenseNova征文hang-B类 · 模型部署"
        notes, real = check_campaign.split_deleted_audiences([self.NAME, gone], self.NAME)
        self.assertEqual(real, [gone])
        self.assertEqual(len(notes), 1)


class ResourceSearchTest(unittest.TestCase):
    def test_前缀搜索后按完整名称精确匹配(self):
        expected = ["prefix · 对照", "prefix · 实验1", "prefix · 实验2"]
        actual = set(expected + ["prefix · 对照-2"])
        self.assertEqual(
            {n: True for n in expected},
            check_campaign.classify_resource_names(expected, actual, True),
        )

    def test_查询不完整时不能把没找到报成确认缺失(self):
        got = check_campaign.classify_resource_names(
            ["prefix · 对照", "prefix · 实验1"],
            {"prefix · 对照"},
            verified=False,
        )
        self.assertTrue(got["prefix · 对照"])
        self.assertIsNone(got["prefix · 实验1"])

    def test_资源结果跨页合并(self):
        class FakeListPage:
            def __init__(self):
                self.index = 0
                self.pages = [
                    [SimpleNamespace(id="1", cells=["1", "prefix · 对照"])],
                    [SimpleNamespace(id="2", cells=["2", "prefix · 实验1"])],
                ]

            def rows(self):
                return self.pages[self.index]

            def table_text(self):
                return str(self.index)

        lp = FakeListPage()
        def fake_next(page, current, timeout=8):
            lp.index += 1
            return (True, True) if lp.index == 1 else (False, True)

        with mock.patch.object(
            check_campaign, "_click_next_resource_page", side_effect=fake_next
        ):
            rows, complete = check_campaign.collect_resource_rows(object(), lp)
        self.assertTrue(complete)
        self.assertEqual(["1", "2"], [row.id for row in rows])

    def test_资源身份必须完整名称全等(self):
        self.assertTrue(check_campaign.resource_name_matches(
            "prefix · 实验2-5", "prefix · 实验2-5"
        ))
        self.assertFalse(check_campaign.resource_name_matches(
            "prefix · 实验2", "prefix · 实验2-5"
        ))
        self.assertFalse(check_campaign.resource_name_matches(
            "prefix · 对照", "prefix · 对照-2"
        ))


if __name__ == "__main__":
    unittest.main()
