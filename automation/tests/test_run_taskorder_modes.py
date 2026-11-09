# -*- coding: utf-8 -*-
"""任务工单的 AB 指纹必须按桶解析，不能沿用全局开关。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import run_taskorder  # noqa: E402


def make_cfg(ab_test):
    return {
        "campaign": {
            "namePrefix": "测试-hang",
            "taskGroupName": "测试-hang",
        },
        "taskOrder": {
            "businessLine": "事业部",
            "taskGroup": "测试-hang",
            "channel": "PC博客详情页-新模版-T0",
            "price": 30,
            "deliveryDate": {
                "start": "2026-10-12",
                "end": "2026-10-20",
                "timeStart": 8,
                "timeEnd": 23,
            },
            "exposureCaps": {"daily": 100000, "weekly": 500000, "total": 500000},
            "abTest": ab_test,
        },
    }


class RunTaskOrderModesTest(unittest.TestCase):
    def test_payload_for_uses_single_resource_mode_per_audience(self):
        cfg = make_cfg(True)
        aud = {
            "id": "A",
            "topic": "主题",
            "subBusinessLine": "业务线",
            "abTest": False,
            "abGroups": [{"label": "对照组", "resource": "A · 对照"}],
        }
        payload = run_taskorder.payload_for(cfg, aud)
        self.assertFalse(payload["abTest"])
        self.assertEqual(payload["abGroups"], aud["abGroups"])

    def test_payload_for_uses_ab_mode_per_audience(self):
        cfg = make_cfg(False)
        aud = {
            "id": "B",
            "topic": "主题",
            "subBusinessLine": "业务线",
            "abTest": True,
            "abGroups": [
                {"label": "对照组", "resource": "B · 对照", "weightPct": 50},
                {"label": "实验组1", "resource": "B · 实验1", "weightPct": 50},
            ],
        }
        payload = run_taskorder.payload_for(cfg, aud)
        self.assertTrue(payload["abTest"])
        self.assertEqual([g["weightPct"] for g in payload["abGroups"]], [50, 50])


if __name__ == "__main__":
    unittest.main()
