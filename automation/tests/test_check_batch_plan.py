# -*- coding: utf-8 -*-
"""批次 YAML 自检的测试（纯离线，不连后台）。

盯住 2026-10-08 真踩过的两条（都在 2 资源桶上）：
  ① 权重必须按资源数算（2 条 = 50/50，3 条 = 34/33/33，合计 100）；
  ② AB 行位次不能跳（只能是 对照组 / 实验组1 / 实验组2 的前 N 个），
     以及配套的「资源名角色段 ↔ 槽位」「新建资源必须被引用」。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import check_batch_plan as cbp  # noqa: E402

CAMP = {"namePrefix": "测试活动-hang"}


def aud(bid="D", n=2, labels=None, weights=None, names=None):
    labels = labels or cbp.LABELS[:n]
    weights = weights or cbp.WEIGHTS[n]
    names = names or ["测试活动-hang-%s类 · %s-9" % (bid, cbp.ROLE_OF_LABEL[l]) for l in labels]
    return {"id": bid, "taskName": "测试活动-hang-%s类" % bid, "nameSuffix": "-9",
            "resources": [{"role": {"对照": "control", "实验1": "experiment1", "实验2": "experiment2"}[
                cbp.ROLE_OF_LABEL[l]], "name": names[i]} for i, l in enumerate(labels)],
            "abGroups": [{"label": l, "resource": names[i], "weightPct": weights[i]}
                         for i, l in enumerate(labels)]}


class CheckBatchPlanTest(unittest.TestCase):
    def test_两资源桶必须5050(self):
        errs = cbp.check_audience(aud(weights=[34, 33]), CAMP)
        self.assertTrue(any("50/50" in e for e in errs), errs)          # 就是后台拒的那条

    def test_三资源桶3420三三(self):
        self.assertEqual(cbp.check_audience(aud(n=3), CAMP), [])

    def test_位次不能跳(self):
        errs = cbp.check_audience(aud(labels=["对照组", "实验组2"], weights=[50, 50]), CAMP)
        self.assertTrue(any("位次" in e for e in errs), errs)           # 「实验组1资源ID不能为空」的根因

    def test_名字角色段要和槽位一致(self):
        a = aud(labels=["对照组", "实验组1"])
        a["abGroups"][1]["resource"] = "测试活动-hang-D类 · 实验2-9"
        a["resources"][1]["name"] = "测试活动-hang-D类 · 实验2-9"
        errs = cbp.check_audience(a, CAMP)
        self.assertTrue(any("角色" in e for e in errs), errs)

    def test_新建资源必须被引用(self):
        a = aud()
        a["resources"].append({"role": "experiment2", "name": "测试活动-hang-D类 · 实验2-9"})
        errs = cbp.check_audience(a, CAMP)
        self.assertTrue(any("孤儿" in e for e in errs), errs)

    def test_缺后缀要报(self):
        a = aud()
        a.pop("nameSuffix")
        self.assertTrue(any("nameSuffix" in e for e in cbp.check_audience(a, CAMP)))

    def test_工单字段(self):
        self.assertTrue(cbp.check_task_order({}))                        # 什么都没有 → 报错
        self.assertEqual(cbp.check_task_order({
            "price": 30, "taskGroup": "T", "deliveryDate": {
                "start": "2026-10-08", "end": "2026-10-12", "timeStart": 8, "timeEnd": 23}}), [])

    def test_真实批次文件全过(self):
        """仓库里这两批（2026-10-08）当时跑过一次后台，必须是干净的。"""
        import io
        import yaml
        repo = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        for rel in (r"activities\火山引擎MediaKit\调整\2026-10-08-九批.yaml",
                    r"activities\KIRO鬼点子计划\调整\2026-10-08-四批.yaml"):
            path = os.path.join(repo, rel)
            if not os.path.exists(path):
                continue
            with io.open(path, encoding="utf-8") as f:
                self.assertEqual(cbp.check_doc(yaml.safe_load(f)), [], rel)


if __name__ == "__main__":
    unittest.main()
