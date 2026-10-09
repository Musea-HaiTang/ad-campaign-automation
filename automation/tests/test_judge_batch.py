# -*- coding: utf-8 -*-
"""judge_batch（判定清单）的测试（假柜台：手写读数，不开库、不连后台、不开浏览器）。

盯住 2026-09-24 起的新口径（用户与领导定的那一套）：
  - 门槛按**工单级累计曝光**触发；没到门槛只有一个结论——继续观察，别动任何东西；
  - 达标线 = **实际点击率 ≥ 千三**（A 2250 曝光 7 击 = 0.311% → 达标）；**曝光超过门槛后按实际曝光折算**
    （用户 2026-09-30 定：`need_click = 曝光 × 千三`，不是"门槛 × 千三"的固定击数）；
    **达标 = 该桶停测试**，只留点击集中的条作长期单、**不补新文案**；
  - 未达标 = 有击留、无击下，幸存上限「3 资源桶 2 条 / 2 资源桶 1 条」，空位用新文案补满；
  - 只认**每个桶自己当前批**的工单（2026-10-08 桶独立；以前是全局"本批次后缀"）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import judge_batch as jb  # noqa: E402

TASK_A = "火山引擎MediaKit-hang-A类 · AI 编程 / Agent 工具-6"
TASK_D = "火山引擎MediaKit-hang-D类 · 短视频 / 内容生产-6"

TH = {
    "passCtr": 0.003,
    "buckets": {
        "A": {"threshold": 2250, "resources": 3},
        "D": {"threshold": 1000, "resources": 2},
    },
    # 桶独立（2026-10-08）：当前批由 _cur 指定，工单名从 _batches 里取，不再靠后缀筛
    "_cur": {"A": "b6", "D": "b6"},
    "_batches": {"b6": {"id": "b6", "label": "六批", "suffix": "-6", "start": "2026-09-24",
                        "orders": {"A": TASK_A, "D": TASK_D}}},
}


def readings(task_name, pairs):
    """pairs = [(槽位, 曝光, 点击)] → 判定脚本吃的那种资源读数行。"""
    return [{"task_id": "t1", "task_name": task_name, "resource_id": slot, "group_label": "",
             "resource_name": slot, "exposure": exp, "click": clk, "fetched_at": "2026-09-24 16:00"}
            for slot, exp, clk in pairs]


def row_for(lines, bucket):
    for ln in lines:
        if ln.startswith("| %s |" % bucket):
            return ln
    raise AssertionError("判定表里没有 %s 桶那一行：\n%s" % (bucket, "\n".join(lines)))


class TestJudge(unittest.TestCase):
    def judge(self, rows):
        return jb.judge(None, TH, rows)

    def test_below_threshold_only_observes(self):
        lines, actions, need = self.judge(
            readings(TASK_A, [("对照-4", 800, 3), ("实验1-6", 200, 0), ("实验2-4", 100, 0)]))
        self.assertIn("未到门槛", row_for(lines, "A"))
        self.assertIn("继续观察", row_for(lines, "A"))
        self.assertEqual(actions, [])
        self.assertEqual(need, 0)

    def test_not_pass_keeps_clicked_and_cuts_zero_click(self):
        # A：2250 曝光 3 击（< 7）→ 两个有点击的留下（上限 2），零点击的下，空位补 1 条
        lines, actions, need = self.judge(
            readings(TASK_A, [("对照-4", 750, 2), ("实验1-6", 750, 1), ("实验2-4", 750, 0)]))
        blob = "\n".join(actions)
        self.assertIn("过门槛 · 未达标", row_for(lines, "A"))
        self.assertIn("对照-4 ｜ 750 曝光 / 2 击 → 保留", blob)
        self.assertIn("实验2-4 ｜ 750 曝光 / 0 击 → **下**", blob)
        self.assertIn("下一轮（-7）＝ 2 条幸存 + **1 条新文案**", blob)
        self.assertEqual(need, 1)

    def test_pass_keeps_clicked_ones_up_to_cap_and_asks_no_new_copy(self):
        # A：2250 曝光 7 击 = 千三 → 停测试；**留几条看点击的实际情况**（2026-09-28 用户定）：
        # 有点击的按点击排序取前 2 条（3 资源桶上限 2）——不是死板地只留 1 条
        lines, actions, need = self.judge(
            readings(TASK_A, [("对照-4", 750, 4), ("实验1-6", 750, 2), ("实验2-4", 750, 1)]))
        blob = "\n".join(actions)
        self.assertIn("**达标**", row_for(lines, "A"))
        self.assertIn("对照-4 ｜ 750 曝光 / 4 击 → 保留", blob)
        self.assertIn("实验1-6 ｜ 750 曝光 / 2 击 → 保留", blob)
        self.assertIn("实验2-4 ｜ 750 曝光 / 1 击 → **下**", blob)
        self.assertIn("长期单", blob)
        self.assertNotIn("下一轮", blob)
        self.assertEqual(need, 0)

    def test_pass_with_only_one_clicked_keeps_only_that_one(self):
        # 达标但只有一条有点击 → 就只留它（"看点击的实际情况"的另一个方向）
        lines, actions, need = self.judge(
            readings(TASK_A, [("对照-4", 750, 7), ("实验1-6", 750, 0), ("实验2-4", 750, 0)]))
        blob = "\n".join(actions)
        self.assertIn("对照-4 ｜ 750 曝光 / 7 击 → 保留", blob)
        self.assertIn("实验1-6 ｜ 750 曝光 / 0 击 → **下**", blob)
        self.assertIn("只留上面标「保留」的那 1 条", blob)
        self.assertEqual(need, 0)

    def test_点击并列时留点击率高的那条(self):
        """用户 2026-10-09 定：点击**打平**时按点击率（再按曝光）排，不再让读数顺序替人做决定。

        真事（火山 A 桶九批）：对照 1,350 曝光 / 1 击 = 0.07%、实验1 1,306 曝光 / 1 击 = 0.08%，
        点击打平；改之前按读数顺序留下了对照（点击率更低的那条），现在留实验1。
        """
        lines, actions, need = self.judge(
            readings(TASK_A, [("对照-4", 1350, 1), ("实验1-6", 1306, 1), ("实验2-4", 1297, 2)]))
        blob = "\n".join(actions)
        self.assertIn("实验2-4 ｜ 1297 曝光 / 2 击 → 保留", blob)      # 点击最多 → 先留
        self.assertIn("实验1-6 ｜ 1306 曝光 / 1 击 → 保留", blob)      # 并列里点击率高 → 留
        self.assertIn("对照-4 ｜ 1350 曝光 / 1 击 → **下**", blob)     # 并列里点击率低 → 下
        self.assertEqual(need, 1)

    def test_达标看实际点击率_不是门槛折算的固定击数(self):
        """用户 2026-09-30 定：达标线 = **实际 CTR ≥ 千三**。

        曝光跑过门槛之后，"门槛 × 千三"那个固定击数就跟千三脱钩了。拿真事做锚：
        KIRO 一批 E 桶 **9,039 曝光 / 9 击 = 0.10%**——按固定击数（3,000 × 千三 = 9）会被判"达标"，
        按实际点击率是**未达标**（9,039 曝光要 28 击才到千三）。
        """
        lines, actions, need = self.judge(
            readings(TASK_A, [("对照", 3013, 3), ("实验1", 3013, 3), ("实验2", 3013, 3)]))   # 9,039 / 9 击
        self.assertIn("过门槛 · 未达标", row_for(lines, "A"))
        self.assertIn("下一轮（-7）", "\n".join(actions))
        self.assertEqual(need, 1)                       # 有点击的留 2 条（上限 2），空位补 1 条

    def test_d_bucket_zero_click_replaces_whole_batch(self):
        lines, actions, need = self.judge(readings(TASK_D, [("对照-6", 500, 0), ("实验1-6", 500, 0)]))
        blob = "\n".join(actions)
        self.assertIn("过门槛 · 未达标", row_for(lines, "D"))
        self.assertIn("下一轮（-7）＝ 0 条幸存 + **2 条新文案**", blob)
        self.assertEqual(need, 2)

    def test_d_bucket_keeps_at_most_one(self):
        # D 只有 2 个槽位：两条都有点击也只留 1 条（上限 1），另一个位子补新文案
        lines, actions, need = self.judge(readings(TASK_D, [("对照-6", 500, 1), ("实验1-6", 500, 1)]))
        self.assertIn("下一轮（-7）＝ 1 条幸存 + **1 条新文案**", "\n".join(actions))
        self.assertEqual(need, 1)

    def test_other_batch_rows_ignored(self):
        lines, actions, need = self.judge(readings(TASK_A.replace("-6", "-5"), [("对照-4", 9999, 9)]))
        self.assertIn("无在跑工单", row_for(lines, "A"))
        self.assertEqual(actions, [])
        self.assertEqual(need, 0)


class TestTodoAndStatus(unittest.TestCase):
    """待办 / 状态行由**脚本**生成（2026-09-28）：定时任务原样抄 STATUS，不再自己编。"""

    def test_没到门槛时待办写无(self):
        rows = readings(TASK_A, [("对照-4", 800, 3), ("实验1-6", 200, 0)])
        text = jb.todo_text(TH, rows)
        self.assertIn("各桶独立 ｜ 巡检 ", text)
        self.assertIn("- A：曝光 1000 / 门槛 2250 · 点击 3 · 未到门槛（差 1250） · 继续观察", text)
        self.assertIn("无（各桶都没到门槛）", text)
        self.assertNotIn("可判：", text)

    def test_到门槛时待办列出留谁(self):
        rows = readings(TASK_A, [("对照-4", 750, 2), ("实验1-6", 750, 1), ("实验2-4", 750, 0)])
        text = jb.todo_text(TH, rows)
        self.assertIn("可判：", text)
        self.assertIn("留 2 条（对照-4、实验1-6）；下一轮补 1 条新文案", text)
        self.assertNotIn("无（各桶都没到门槛）", text)

    def test_状态行是机器生成的一行(self):
        rows = readings(TASK_A, [("对照-4", 750, 2), ("实验1-6", 750, 1), ("实验2-4", 750, 0)])
        line = jb.status_line(TH, rows)
        self.assertTrue(line.startswith("巡检 "))
        self.assertIn("各桶独立", line)
        self.assertIn("A 2250/3", line)
        self.assertIn("D —", line)              # D 桶本批没有在跑工单
        self.assertIn("可判：A（过门槛 · 未达标 → 有击留、无击下，补新文案）", line)
        self.assertNotIn("\n", line)

    def test_状态行没到门槛时写无(self):
        line = jb.status_line(TH, readings(TASK_A, [("对照-4", 100, 0)]))
        self.assertIn("可判：无", line)


class TestHelpers(unittest.TestCase):
    def test_bucket_of(self):
        self.assertEqual(jb.bucket_of(TASK_A), "A")
        self.assertEqual(jb.bucket_of("没有桶名的工单"), "")

    def test_next_batch(self):
        self.assertEqual(jb.next_batch("-6"), "-7")
        self.assertEqual(jb.next_batch("-9"), "-10")    # 批次号绝对值 +1（-9 比 -8 新），不是整数 +1
        self.assertEqual(jb.next_batch("abc"), "?")


if __name__ == "__main__":
    unittest.main()
