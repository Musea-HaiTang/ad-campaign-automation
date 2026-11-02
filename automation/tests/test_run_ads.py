# -*- coding: utf-8 -*-
"""run_ads 提交后回读路径的回归测试（不开浏览器）。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import check_campaign  # noqa: E402
import run_ads  # noqa: E402


class VerifyCreatedResourcesTest(unittest.TestCase):
    def test_复用精确资源检查_不再使用任务组下拉回读(self):
        cfg = {"campaign": {"taskGroupName": "腾讯云产品-hang"}, "audiences": []}
        names = ["腾讯云产品-hang-TokenHub · 对照-6",
                 "腾讯云产品-hang-TokenHub · 实验1-6"]
        exact = {name: True for name in names}
        s = SimpleNamespace(page=object())

        with mock.patch.object(check_campaign, "check_resources_for_config",
                               return_value=exact) as checker, \
                mock.patch.object(run_ads.ui, "goto",
                                  side_effect=AssertionError("不应再走任务组下拉回读")):
            missing = run_ads.verify_created_resources(s, cfg, names)

        self.assertEqual(missing, [])
        checker.assert_called_once_with(s, cfg, only_names=names)

    def test_精确检查未确认时返回_None(self):
        cfg = {"campaign": {"taskGroupName": "腾讯云产品-hang"}, "audiences": []}
        name = "腾讯云产品-hang-TokenHub · 实验1-6"
        with mock.patch.object(check_campaign, "check_resources_for_config",
                               return_value={name: None}):
            missing = run_ads.verify_created_resources(
                SimpleNamespace(page=object()), cfg, [name]
            )
        self.assertIsNone(missing)

    def test_精确检查确认缺失时返回缺失名(self):
        cfg = {"campaign": {"taskGroupName": "腾讯云产品-hang"}, "audiences": []}
        name = "腾讯云产品-hang-TokenHub · 实验1-6"
        with mock.patch.object(check_campaign, "check_resources_for_config",
                               return_value={name: False}):
            missing = run_ads.verify_created_resources(
                SimpleNamespace(page=object()), cfg, [name]
            )
        self.assertEqual(missing, [name])


if __name__ == "__main__":
    unittest.main()
