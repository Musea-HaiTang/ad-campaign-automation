# -*- coding: utf-8 -*-
"""想法池自检的测试（纯离线，不读仓库、不连后台）。

盯住 2026-10-16 真踩到的两条：
  ① 标着「在跑」但这条文案从没建过（假在跑：KIRO `D2-b/D4-b`、TokenHub `T-11-b/T-05-b`）；
  ② 建过却没删（池子只放"还没上过的"）。
另加一条回归：**说明文字里的"在跑"两个字不算在跑**，只有加粗 `**在跑**` 才算
（第一次跑就是被"实际在跑的是直给版"这句话误报的）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import check_pool as cp  # noqa: E402

TABLE = """# 池子

| # | 桶 | 一句话假设 | 正式文案 | 两字段 | 怎么算验过 |
|---|---|---|---|---|---|
| D2-b | D | 作品＝简历项目（同角度 **仿写诗词**风格 · **未上过**；D 桶实际在跑的是直给版 `对照-6`） | 标题：`作品一篇入简历`<br>摘要：`…` | 入简历 · 收益绑身份 · 细则 §2 | 抬过 0.140% |
| D5-b | D | 官方背书（**在跑** · 同角度 **热梗**风格） | 标题：`主办方是亚马逊云科技，含金量拉满`<br>摘要：`…` | 拉满 · 独有资源 · 细则 §2 | 跑到 2,000+ 曝光 |
| B7 | B | 拆自评门槛 | 标题：`第一回参赛也不吃亏`<br>摘要：`…` | 脑洞 · 拆自评门槛 · 细则 §2 | 同上 |
"""


class TestParse(unittest.TestCase):
    def test_解析出三行与在跑标记(self):
        rows = cp.parse_rows(TABLE)
        self.assertEqual(["D2-b", "D5-b", "B7"], [r["id"] for r in rows])
        self.assertEqual(["D", "D", "B"], [r["bucket"] for r in rows])
        self.assertEqual([False, True, False], [r["running"] for r in rows])
        self.assertEqual("作品一篇入简历", rows[0]["title"])

    def test_说明文字里的在跑不算在跑(self):
        # D2-b 那格的说明写了"实际在跑的是直给版" → 只有 **在跑** 才算
        self.assertFalse(cp.parse_rows(TABLE)[0]["running"])

    def test_没有桶列时用文件名兜底(self):
        text = TABLE.replace("| D2-b | D |", "| T-11-b |").replace(
            "| # | 桶 | 一句话假设 |", "| # | 一句话假设 |")
        rows = cp.parse_rows(text, default_bucket="TokenHub")
        self.assertEqual("TokenHub", rows[0]["bucket"])


class TestCheck(unittest.TestCase):
    def test_假在跑与该删没删都能报出来(self):
        rows = cp.parse_rows(TABLE)
        rows.append({"id": "B-01", "bucket": "B", "title": "该删的那条", "running": False})
        # D5-b 标着在跑、库里却没有 → ①；B-01 已经建过、还在池子里 → ②；
        # D2-b / B7 既没标在跑、也没建过 → 不该报
        built = {"该删的那条": "…B类 · 对照-9"}
        issues = cp.check(rows, built)
        self.assertEqual(2, len(issues))
        self.assertIn("① 假在跑", issues[0])
        self.assertIn("② 该删没删", issues[1])

    def test_一致时没有告警(self):
        rows = cp.parse_rows(TABLE)
        built = {"主办方是亚马逊云科技，含金量拉满": "…D类 · 实验2-6"}
        self.assertEqual([], cp.check(rows, built))

    def test_存量只数还没上过的(self):
        self.assertEqual({"D": 1, "B": 1}, cp.stock(cp.parse_rows(TABLE)))


VALID_ROLE_TABLE = """# 池子

### ANG-X-01｜角度一
| 文案 ID | 一句话假设 / 写法 | 正式文案 |
|---|---|---|
| X-01 | **首测** · 最强钩子 | 标题：`首测标题`<br>摘要：`…` |
| X-02 | **补验** · **对仗 7+7** | 标题：`补验标题`<br>摘要：`…` |
| X-03 | **备选** · **化用** | 标题：`备选标题`<br>摘要：`…` |
"""


class TestStructure(unittest.TestCase):
    def test_合法验证位结构(self):
        rows = cp.parse_rows(VALID_ROLE_TABLE)
        self.assertEqual(["首测", "补验", "备选"], [r["role"] for r in rows])
        self.assertEqual("对仗", rows[1]["style"])
        self.assertEqual([], cp.structure_issues(rows))

    def test_补验必须是风格(self):
        text = VALID_ROLE_TABLE.replace("**补验** · **对仗 7+7**", "**补验** · 常规")
        issues = cp.structure_issues(cp.parse_rows(text))
        self.assertTrue(any("不是风格文案" in x for x in issues))

    def test_缺少补验会报错(self):
        text = VALID_ROLE_TABLE.replace(
            "| X-02 | **补验** · **对仗 7+7** | 标题：`补验标题`<br>摘要：`…` |\n", "")
        issues = cp.structure_issues(cp.parse_rows(text))
        self.assertTrue(any("必须有且只有 1 条「补验」" in x for x in issues))

    def test_首测是风格时补验不能再同风格(self):
        text = VALID_ROLE_TABLE.replace("**首测** · 最强钩子", "**首测** · **对仗 7+7**")
        issues = cp.structure_issues(cp.parse_rows(text))
        self.assertTrue(any("首测与补验用了同一风格" in x for x in issues))

    def test_旧池没有标记时兼容跳过(self):
        self.assertEqual([], cp.structure_issues(cp.parse_rows(TABLE)))

    def test_一条已投后允许单条残组(self):
        text = VALID_ROLE_TABLE.replace(
            "| X-01 | **首测** · 最强钩子 | 标题：`首测标题`<br>摘要：`…` |\n",
            "",
        ).replace(
            "| X-03 | **备选** · **化用** | 标题：`备选标题`<br>摘要：`…` |\n",
            "",
        )
        self.assertEqual([], cp.structure_issues(cp.parse_rows(text)))


if __name__ == "__main__":
    unittest.main()
