# -*- coding: utf-8 -*-
"""投放物料必须显示文案分类，且不能留下未替换占位符。"""
import pathlib
import sys
import unittest

from _temp import temp_workdir

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "ad_output" / "工具"))

import gen_material  # noqa: E402


def fake_definition(n_copies=3):
    copies = [
        {
            "role": "control",
            "label": "对照",
            "title": "标题 A",
            "summary": "摘要 A",
            "angleKey": "A-1",
            "presentationType": "direct_marketing",
            "styleKey": "regular",
            "validationSlot": "first_test",
            "hookKey": "场景",
            "hookNote": "说明 A",
        },
        {
            "role": "experiment1",
            "label": "实验1",
            "title": "标题 B",
            "summary": "摘要 B",
            "angleKey": "A-2",
            "presentationType": "disguised_post",
            "styleKey": "adaptation",
            "validationSlot": "first_test",
            "hookKey": "工作流",
            "hookNote": "说明 B",
        },
        {
            "role": "experiment2",
            "label": "实验2",
            "title": "标题 C",
            "summary": "摘要 C",
            "angleKey": "A-3",
            "presentationType": "direct_marketing",
            "styleKey": "antithesis",
            "validationSlot": "first_test",
            "hookKey": "成本",
            "hookNote": "说明 C",
        },
    ][:n_copies]
    return {
        "activity": {"title": "示例", "subtitle": "副标题", "ruleText": ""},
        "campaign": {
            "brand": "示例",
            "owner": "hang",
            "namePrefix": "示例-hang",
            "taskGroupName": "示例-hang",
        },
        "buckets": [{
            "id": "A",
            "name": "人群 A",
            "audience": "开发者",
            "topic": "主题 A",
            "keywords": "关键词1,关键词2",
            "kwNote": "测试",
            "copies": copies,
        }],
    }


class GenMaterialTest(unittest.TestCase):
    def test_物料显示文案分类且无残留占位符(self):
        with temp_workdir("gen-material-") as tmp:
            out = pathlib.Path(tmp) / "material.html"
            gen_material.build(fake_definition(), out)
            html = out.read_text(encoding="utf-8")

        self.assertIn("分类：纯营销 · 常规 · 首测 · 角度 A-1", html)
        self.assertNotIn("{{META_", html)

    def test_两资源桶只生成两本文案(self):
        with temp_workdir("gen-material-two-") as tmp:
            out = pathlib.Path(tmp) / "material.html"
            gen_material.build(fake_definition(2), out)
            html = out.read_text(encoding="utf-8")

        self.assertIn("分类：伪装博文 · 化用 · 首测 · 角度 A-2", html)
        self.assertNotIn("分类：纯营销 · 对仗", html)
        self.assertNotIn("{{", html)

    def test_新文案缺分类字段时拒绝生成(self):
        d = fake_definition(2)
        del d["buckets"][0]["copies"][0]["presentationType"]
        with temp_workdir("gen-material-missing-meta-") as tmp:
            with self.assertRaisesRegex(SystemExit, "presentationType"):
                gen_material.build(d, pathlib.Path(tmp) / "material.html")


if __name__ == "__main__":
    unittest.main()
