# -*- coding: utf-8 -*-
"""精确列表查询的三态行为。"""
import pathlib
import sys
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import execution_state as es  # noqa: E402
import remote_lookup  # noqa: E402


class FakeListPage:
    def __init__(self, *, signature_changes=True, row=None, query_lands=True):
        self.page = SimpleNamespace(wait_for_timeout=lambda _ms: None)
        self.signature = "before"
        self.signature_changes = signature_changes
        self.query_lands = query_lands
        self.row = row
        self.filter_value = None

    def table_text(self):
        return self.signature

    def filter(self, values):
        self.filter_value = next(iter(values.values()))
        return []

    def query(self, wait_ms=0, wait_rows=True):
        if self.signature_changes:
            self.signature = "after"
        return self.query_lands

    def row_by_name(self, name, timeout=8):
        return self.row


class EmptyLocator:
    def __init__(self):
        self.first = self
        self.last = self

    def count(self):
        return 0


class ManyPage:
    def __init__(self, rows):
        self.page = SimpleNamespace(
            locator=lambda _sel: EmptyLocator(),
            wait_for_timeout=lambda _ms: None,
        )
        self.rows_data = rows
        self.signature = "before"
        self.filter_value = None

    def table_text(self):
        return self.signature

    def filter(self, values):
        self.filter_value = next(iter(values.values()))
        return []

    def query(self, wait_ms=0, wait_rows=True):
        self.signature = "after"
        return True

    def rows(self):
        return self.rows_data


class RemoteLookupTest(unittest.TestCase):
    def test_exact_row_is_found(self):
        lp = FakeListPage(row=SimpleNamespace(
            id="208508", text=lambda: "208508 测试名单",
            cells=["208508", "测试名单"]))
        state = remote_lookup.exact(lp, "测试名单", "名单名称")
        self.assertEqual(state.kind, es.FOUND)
        self.assertEqual(state.object_id, "208508")
        self.assertEqual(lp.filter_value, "测试名单")

    def test_refreshed_empty_result_is_absent(self):
        state = remote_lookup.exact(
            FakeListPage(row=None), "不存在", "名单名称")
        self.assertEqual(state.kind, es.ABSENT)

    def test_unchanged_table_is_unknown(self):
        state = remote_lookup.exact(
            FakeListPage(signature_changes=False, row=None, query_lands=False),
            "未知", "名单名称",
            timeout=0.01)
        self.assertEqual(state.kind, es.UNKNOWN)

    def test_query_landed_with_empty_table_is_absent(self):
        state = remote_lookup.exact(
            FakeListPage(signature_changes=False, row=None, query_lands=True),
            "不存在", "名单名称", timeout=0.01)
        self.assertEqual(state.kind, es.ABSENT)

    def test_batch_lookup_matches_exact_cells_and_marks_rest_absent(self):
        found = SimpleNamespace(
            id="1", cells=["1", "甲"], text=lambda: "1 甲")
        lp = ManyPage([found])
        states = remote_lookup.exact_many(
            lp, {"a": "甲", "b": "乙"}, "名称", "共同前缀")
        self.assertEqual(states["a"].kind, es.FOUND)
        self.assertEqual(states["b"].kind, es.ABSENT)


if __name__ == "__main__":
    unittest.main()
