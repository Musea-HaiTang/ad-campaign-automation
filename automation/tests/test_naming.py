# -*- coding: utf-8 -*-
"""naming 的单测：纯函数，毫秒级；外加一条「生成器输出 = 命名规则」的回归锚点。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import pathlib
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "scripts"))

import naming  # noqa: E402


class NamingTest(unittest.TestCase):
    def test_前缀取_namePrefix_并去掉尾部横杠(self):
        self.assertEqual(naming.prefix({"namePrefix": "SenseNova征文hang"}), "SenseNova征文hang")
        self.assertEqual(naming.prefix({"namePrefix": "  华为云码道hang-  "}), "华为云码道hang")
        self.assertEqual(naming.prefix({}), "")

    def test_生成器缺前缀要直接报错(self):
        with self.assertRaises(ValueError) as cm:
            naming.require_prefix({})
        self.assertIn("namePrefix", str(cm.exception))
        self.assertEqual(naming.require_prefix({"namePrefix": "X"}), "X")

    def test_桶名(self):
        camp = {"namePrefix": "SenseNova征文hang"}
        self.assertEqual(naming.bucket_name(camp, {"id": "A"}), "SenseNova征文hang-A类")
        self.assertEqual(naming.bucket_name(camp, {"id": "G"}), "SenseNova征文hang-G类")

    def test_没有前缀时退回首写的_taskName(self):
        camp = {}
        self.assertEqual(naming.bucket_name(camp, {"id": "A", "taskName": "整活节-A类"}),
                         "整活节-A类")
        self.assertEqual(naming.audience_task_name(camp, {"id": "A", "taskName": "整活节-A类",
                                                          "topic": "AI 编程"}),
                         "整活节-A类 · AI 编程")

    def test_客群名_工单名_资源名(self):
        camp = {"namePrefix": "SenseNova征文hang"}
        aud = {"id": "A", "topic": "模型部署 / GPU 基础设施"}
        self.assertEqual(naming.audience_task_name(camp, aud),
                         "SenseNova征文hang-A类 · 模型部署 / GPU 基础设施")
        # 工单名 = 客群名（同一个字符串）
        self.assertEqual(naming.order_task_name(camp, aud), naming.audience_task_name(camp, aud))
        self.assertEqual(naming.resource_name(camp, aud, "对照"), "SenseNova征文hang-A类 · 对照")
        self.assertEqual(naming.resource_name(camp, aud, "实验1"), "SenseNova征文hang-A类 · 实验1")
        # 没写 topic 时只剩桶名
        self.assertEqual(naming.audience_task_name(camp, {"id": "B"}), "SenseNova征文hang-B类")

    def test_活动标签与物料文件名(self):
        camp = {"namePrefix": "SenseNova征文hang"}
        self.assertEqual(naming.campaign_label(camp, 7), "SenseNova征文hang-7类")
        self.assertEqual(naming.material_file_name(camp, 7), "SenseNova征文hang-7类投放物料.html")
        with self.assertRaises(ValueError):
            naming.material_file_name({}, 5)

    def test_对不上时的提醒_只提醒不阻断(self):
        camp = {"namePrefix": "SenseNova征文hang"}
        ok = {"id": "A", "taskName": "SenseNova征文hang-A类"}
        self.assertIsNone(naming.name_warning(camp, ok))
        bad = {"id": "A", "taskName": "华为云码道-博客T0-A类"}
        msg = naming.name_warning(camp, bad)
        self.assertIn("不一致", msg)
        self.assertIn("SenseNova征文hang-A类", msg)
        # 判断不了就闭嘴：没前缀、或 YAML 里根本没写 taskName
        self.assertIsNone(naming.name_warning({}, bad))
        self.assertIsNone(naming.name_warning(camp, {"id": "A"}))

    # ---------- 回归锚点：生成器写出来的名字必须等于命名规则算出来的 ----------
    def test_生成器输出与命名规则一致(self):
        def_path = REPO / "activities/sensenova/活动定义.yaml"
        yml_path = REPO / "activities/sensenova/SenseNova征文hang.yaml"
        if not def_path.exists() or not yml_path.exists():
            self.skipTest("示例活动数据不在，跳过")
        act = yaml.safe_load(def_path.read_text(encoding="utf-8"))
        yml = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
        camp_def, camp_out = act["campaign"], yml["campaign"]
        by_id = {a["id"]: a for a in yml["audiences"]}

        self.assertEqual(len(by_id), len(act["buckets"]))
        for b in act["buckets"]:
            aud = by_id[b["id"]]
            self.assertEqual(naming.bucket_name(camp_out, aud), naming.bucket_name(camp_def, b))
            self.assertEqual([naming.resource_name(camp_def, b, c["label"]) for c in b["copies"]],
                             [r["name"] for r in aud["resources"]])
            self.assertEqual(naming.audience_task_name(camp_out, aud),
                             naming.audience_task_name(camp_def, b))
            self.assertIsNone(naming.name_warning(camp_out, aud))

        self.assertEqual(yml["taskOrder"]["taskName"],
                         naming.audience_task_name(camp_out, yml["audiences"][0]))
        self.assertEqual(yml["label"], naming.campaign_label(camp_out, len(yml["audiences"])))


if __name__ == "__main__":
    unittest.main()
