# -*- coding: utf-8 -*-
"""run_distribution_ids 的纯函数单测（不开浏览器）。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
sys.path.insert(0, str(ROOT / "scripts"))

import run_distribution_ids as rd  # noqa: E402


class ReadIdsTest(unittest.TestCase):
    def test_取article_id_保持顺序_utf8带BOM也能读(self):
        # 临时文件按仓库惯例放 automation/_tmp/（已 gitignore）
        d = ROOT / "_tmp" / "test_distribution_ids"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "x.csv"
        try:
            p.write_text('"article_id","title"\n3,"c"\n1,"a"\n2,"b"\n', encoding="utf-8-sig")
            self.assertEqual(rd.read_ids(str(p)), ["3", "1", "2"])
        finally:
            p.unlink(missing_ok=True)

    def test_中文表头_博文id_也认(self):
        # 2026-09-21 第一轮那份 CSV 的表头是中文别名（"博文id","title","url","点击数"）
        d = ROOT / "_tmp" / "test_distribution_ids"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "cn.csv"
        try:
            p.write_text('"博文id","title","url","点击数"\n7,"x","u",3\n', encoding="utf-8-sig")
            self.assertEqual(rd.read_ids(str(p)), ["7"])
        finally:
            p.unlink(missing_ok=True)

    def test_没有id列_启动就报错(self):
        d = ROOT / "_tmp" / "test_distribution_ids"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "bad.csv"
        try:
            p.write_text('"foo","bar"\n1,2\n', encoding="utf-8-sig")
            with self.assertRaises(SystemExit):
                rd.read_ids(str(p))
        finally:
            p.unlink(missing_ok=True)


class CountHintTest(unittest.TestCase):
    def test_读千分位(self):
        self.assertEqual(rd.parse_count_hint("提示: 已输入 51,677 个有效数据"), 51677)

    def test_读零(self):
        self.assertEqual(rd.parse_count_hint("提示: 已输入0个有效数据"), 0)

    def test_读不到返回负一(self):
        self.assertEqual(rd.parse_count_hint("新增分发名单"), -1)


class ListNameTest(unittest.TestCase):
    CAMP = {"namePrefix": "火山引擎MediaKit-hang", "taskGroupName": "火山引擎MediaKit-hang"}
    AUD = {"id": "D", "topic": "短视频 / 内容生产", "nameSuffix": "-2"}

    def test_按命名规则_带YAML后缀(self):
        self.assertEqual(rd.list_name(self.CAMP, self.AUD, "", ""),
                         "火山引擎MediaKit-hang-D类 · 短视频 / 内容生产-2")

    def test_suffix覆盖YAML后缀_不是追加(self):
        self.assertEqual(rd.list_name(self.CAMP, self.AUD, "", "-3"),
                         "火山引擎MediaKit-hang-D类 · 短视频 / 内容生产-3")

    def test_name优先(self):
        self.assertEqual(rd.list_name(self.CAMP, self.AUD, "测试名单-直接写", "-9"), "测试名单-直接写")


if __name__ == "__main__":
    unittest.main()
