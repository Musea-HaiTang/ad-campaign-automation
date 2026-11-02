# -*- coding: utf-8 -*-
"""远端三态与 payload 指纹的纯函数测试。"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import execution_state as es  # noqa: E402


class RemoteStateTest(unittest.TestCase):
    def test_bool_and_none_are_normalized(self):
        self.assertEqual(es.normalize(True).kind, es.FOUND)
        self.assertEqual(es.normalize(False).kind, es.ABSENT)
        self.assertEqual(es.normalize(None).kind, es.UNKNOWN)

    def test_found_carries_remote_identity(self):
        state = es.found("208508", reason="精确名称命中")
        self.assertTrue(state.is_found)
        self.assertEqual(state.object_id, "208508")
        self.assertEqual(state.reason, "精确名称命中")

    def test_payload_hash_is_stable_and_order_independent(self):
        a = es.payload_hash({"title": "标题", "summary": "摘要"})
        b = es.payload_hash({"summary": "摘要", "title": "标题"})
        c = es.payload_hash({"title": "标题", "summary": "另一份"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


if __name__ == "__main__":
    unittest.main()
