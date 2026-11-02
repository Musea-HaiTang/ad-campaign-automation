# -*- coding: utf-8 -*-
import os
import sys
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import judging  # noqa: E402


def rows(*items):
    return [
        {
            "resource_name": name,
            "exposure": exposure,
            "click": click,
        }
        for name, exposure, click in items
    ]


class JudgingTest(unittest.TestCase):
    def test_未到门槛只继续观察(self):
        result = judging.judge_one(
            "demo-A类-1",
            {"threshold": 1000, "resources": 3},
            0.003,
            rows(("对照", 600, 3), ("实验1", 100, 0)),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["conclusion"], "继续观察")
        self.assertEqual(result["keep"], [])

    def test_达标按实际点击率计算(self):
        result = judging.judge_one(
            "demo-A类-1",
            {"threshold": 1000, "resources": 3},
            0.003,
            rows(("对照", 1000, 3)),
        )
        self.assertTrue(result["pass"])
        self.assertEqual(result["need_click"], 3)
        self.assertEqual(result["keep"], ["对照"])
        self.assertEqual(result["new_copy"], 0)

    def test_未达标时点击资源保留且零点击下线(self):
        result = judging.judge_one(
            "demo-A类-1",
            {"threshold": 1000, "resources": 3},
            0.01,
            rows(("对照", 500, 2), ("实验1", 500, 1), ("实验2", 500, 0)),
        )
        self.assertFalse(result["pass"])
        self.assertEqual(result["keep"], ["对照", "实验1"])
        self.assertEqual(result["drop"], ["实验2"])
        self.assertEqual(result["new_copy"], 1)

    def test_达标只保留点击最高的两条(self):
        result = judging.judge_one(
            "demo-A类-1",
            {"threshold": 1000, "resources": 3},
            0.003,
            rows(("对照", 500, 4), ("实验1", 500, 2), ("实验2", 500, 1)),
        )
        self.assertTrue(result["pass"])
        self.assertEqual(result["keep"], ["对照", "实验1"])
        self.assertEqual(result["drop"], ["实验2"])

    def test_点击并列时保留点击率更高的资源(self):
        result = judging.judge_one(
            "demo-A类-1",
            {"threshold": 1000, "resources": 2},
            0.003,
            rows(("对照", 1000, 1), ("实验1", 500, 1)),
        )
        self.assertEqual(result["keep"], ["实验1"])


if __name__ == "__main__":
    unittest.main()
