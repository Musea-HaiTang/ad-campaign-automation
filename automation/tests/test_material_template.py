# -*- coding: utf-8 -*-
"""物料模板的单测：模板只留一个桶块，生成器按桶数复制（4–7 类都成立）。

放在 automation/tests 是因为仓库只有这一个测试入口（`unittest discover -s automation/tests`）；
被测对象是 ad_output 的生成器。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
REPO = ROOT.parent
TPL = REPO / "ad_output" / "投放物料" / "模板" / "书卷墨色投放物料模板.html"
sys.path.insert(0, str(REPO / "ad_output" / "工具"))

import gen_material  # noqa: E402


def fake_def(n):
    """最小可用的活动定义：n 个桶 × 3 份文案。"""
    return {
        "activity": {"title": "测试活动标题", "subtitle": "副标题", "ruleText": "文案纪律"},
        "campaign": {"namePrefix": "测试hang"},
        "buckets": [{
            "id": chr(ord("A") + i),
            "name": "桶名%d" % i,
            "audience": "人群%d" % i,
            "topic": "主题%d" % i,
            "keywords": "关键词1, 关键词2",
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
            ],
        } for i in range(n)],
    }


class MaterialTemplateTest(unittest.TestCase):
    def setUp(self):
        self.base = ROOT / "_tmp" / "test_material"
        self.base.mkdir(parents=True, exist_ok=True)

    def test_模板只留一个桶块(self):
        tpl = TPL.read_text(encoding="utf-8")
        self.assertEqual(tpl.count("<!-- BUCKET:START"), 1)
        self.assertEqual(tpl.count("<!-- BUCKET:END"), 1)
        self.assertEqual(tpl.count('class="grp"'), 1)          # 不再写死 7 个桶
        self.assertEqual(re.findall(r"\{\{G\d", tpl), [])      # 块内占位符不带序号
        self.assertEqual(tpl.count("data-page-node-id"), 0)    # 设计工具残留已清掉

    def test_桶数由数据决定_4到7都成立(self):
        for n in (4, 5, 6, 7):
            out = self.base / ("m%d.html" % n)
            gen_material.build(fake_def(n), out)
            html = out.read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r'class="grp"', html)), n, "%d 桶的块数不对" % n)
            self.assertEqual(re.findall(r'id="G(\d+)"', html),
                             [str(i) for i in range(1, n + 1)])
            no_comment = re.sub(r"<!--.*?-->", "", html, flags=re.S)
            self.assertEqual(re.findall(r"\{\{[^}]+\}\}", no_comment), [], "%d 桶有残留占位符" % n)

    def test_桶内容与命名都填对了(self):
        out = self.base / "m5_content.html"
        gen_material.build(fake_def(5), out)
        html = out.read_text(encoding="utf-8")
        self.assertIn("测试hang-E类", html)      # 桶名走 naming：{前缀}-{id}类
        self.assertIn("桶名4", html)
        self.assertIn("人群4", html)
        self.assertIn("标题C", html)


if __name__ == "__main__":
    unittest.main()
