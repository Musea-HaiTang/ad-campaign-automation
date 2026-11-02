# -*- coding: utf-8 -*-
"""bucket_runner 的单测：假 items、假 run_one，不开浏览器。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import json
import pathlib
import shutil
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]  # automation/
sys.path.insert(0, str(ROOT / "scripts"))

import bucket_runner as br  # noqa: E402
import execution_state as es  # noqa: E402


class QuietLog:
    def __init__(self):
        self.lines = []

    def __call__(self, *parts):
        self.lines.append(" ".join(str(p) for p in parts))

    def text(self):
        return "\n".join(self.lines)


class BucketRunnerTest(unittest.TestCase):
    def setUp(self):
        # 用仓库内的 _tmp（已 gitignore）：沙箱里系统临时目录不可写、也删不掉
        self.base = ROOT / "_tmp" / "test_progress" / self._testMethodName
        self.base.mkdir(parents=True, exist_ok=True)
        self.progress_path = str(self.base / "日志" / "progress.json")
        self.log = QuietLog()

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def done_runner(self, seen):
        def run_one(item):
            seen.append(item)
            return True
        return run_one

    # ---------- 基本：跑完 / 记数 / 三态 ----------
    def test_步骤体检_全ok才算完成(self):
        self.assertIs(br.steps_status([("名称", "ok"), ("三栏", "ok")]), True)
        self.assertEqual(br.steps_status([("名称", "ok"), ("三栏", "fail")]), br.WARN)
        self.assertEqual(br.steps_status([("名称", "fail")]), br.WARN)

    def test_all_ok(self):
        seen = []
        r = br.run_buckets([1, 2, 3], self.done_runner(seen), log=self.log)
        self.assertEqual(r.status, br.OK)
        self.assertEqual(r.exit_code(), 0)
        self.assertEqual((r.total, r.attempted, r.done, r.skipped), (3, 3, 3, 0))
        self.assertFalse(r.aborted)
        self.assertEqual(seen, [1, 2, 3])

    def test_warn_is_not_ok(self):
        r = br.run_buckets(["a"], lambda it: "warn", log=self.log)
        self.assertEqual(r.status, br.HAS_WARN)
        self.assertEqual(r.exit_code(), 1)
        self.assertEqual((r.warned, r.failed), (1, 0))

    def test_return_false_counts_as_failure(self):
        r = br.run_buckets(["a"], lambda it: False, log=self.log)
        self.assertEqual(r.status, br.HAS_FAILURES)
        self.assertEqual(r.failed, 1)
        self.assertIn("失败", self.log.text())

    def test_fatal_flag_wins(self):
        r = br.RunReport()
        r.done = 1
        self.assertEqual(r.status, br.OK)
        r.fatal = True
        self.assertEqual(r.status, br.HAS_FAILURES)
        self.assertEqual(r.exit_code(), 1)

    # ---------- 止损 ----------
    def test_first_item_fail_aborts(self):
        seen = []

        def run_one(item):
            seen.append(item)
            raise RuntimeError("任务组不在下拉里")

        r = br.run_buckets([1, 2, 3], run_one, log=self.log)
        self.assertEqual(seen, [1])
        self.assertEqual(r.attempted, 1)
        self.assertTrue(r.aborted)
        self.assertEqual(r.status, br.HAS_FAILURES)
        self.assertIn("首项即失败", self.log.text())

    def test_three_streak_aborts(self):
        seen = []

        def run_one(item):
            seen.append(item)
            return item == 1   # 首项成功，之后连败

        r = br.run_buckets([1, 2, 3, 4, 5], run_one, log=self.log)
        self.assertEqual(seen, [1, 2, 3, 4])
        self.assertTrue(r.aborted)
        self.assertIn("连续 3 项失败", self.log.text())

    def test_streak_resets_after_success(self):
        seen = []

        def run_one(item):
            seen.append(item)
            return item % 2 == 1   # 偶数项失败

        # 1 成功、2 失败、3 成功、4 失败、5 成功 → 没到 3 连败，5 项全跑
        r = br.run_buckets([1, 2, 3, 4, 5], run_one, log=self.log)
        self.assertEqual(seen, [1, 2, 3, 4, 5])
        self.assertFalse(r.aborted)
        self.assertEqual(r.failed, 2)

    def test_first_item_fail_aborts_even_without_streak_limit(self):
        r = br.run_buckets([1, 2], lambda it: "fail", abort_after=0, log=self.log)
        self.assertEqual(r.attempted, 1)
        self.assertTrue(r.aborted)

    # ---------- 断点 ----------
    def test_submitted_is_always_skipped(self):
        seen = []
        p = br.Progress(self.progress_path)
        p.set("a", br.SUBMITTED)
        for dry_run in (True, False):
            r = br.run_buckets(["a", "b"], self.done_runner(seen),
                               key_of=lambda it: it, progress=p, dry_run=dry_run, log=self.log)
            self.assertEqual(r.skipped, 1)
        self.assertEqual(seen, ["b", "b"])   # a 两次都没跑
        self.assertIn("SKIP a（已创建:submitted）", self.log.text())

    def test_done_skips_only_in_dry_run(self):
        seen = []
        p = br.Progress(self.progress_path)
        p.set("a", br.DONE)

        r = br.run_buckets(["a"], self.done_runner(seen), key_of=lambda it: it,
                           progress=p, dry_run=True, log=self.log)
        self.assertEqual((r.skipped, seen), (1, []))
        self.assertIn("SKIP a（彩排已校验:done）", self.log.text())

        # 正式跑：彩排打过的卡不算数，要重跑并真正创建
        r = br.run_buckets(["a"], self.done_runner(seen), key_of=lambda it: it,
                           progress=p, dry_run=False, log=self.log)
        self.assertEqual((r.skipped, seen), (0, ["a"]))

    def test_outcome_is_written_and_reloaded(self):
        p = br.Progress(self.progress_path)
        br.run_buckets(["a", "b"], lambda it: "submitted" if it == "a" else "fail",
                       key_of=lambda it: "tg|" + it, progress=p, log=self.log)
        on_disk = json.loads(pathlib.Path(self.progress_path).read_text(encoding="utf-8"))
        self.assertEqual(on_disk, {"tg|a": "submitted", "tg|b": "fail"})
        self.assertEqual(br.Progress(self.progress_path).get("tg|a"), "submitted")

    def test_broken_progress_file_starts_empty(self):
        path = pathlib.Path(self.progress_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ 这不是 json", encoding="utf-8")
        seen = []
        r = br.run_buckets(["a"], self.done_runner(seen), key_of=lambda it: it,
                           progress=br.Progress(self.progress_path), log=self.log)
        self.assertEqual((r.done, seen), (1, ["a"]))

    def test_strict_progress_file_rejects_broken_file(self):
        path = pathlib.Path(self.progress_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ 这不是 json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "进度账本无法读取"):
            br.Progress(self.progress_path, strict=True)

    def test_strict_progress_missing_file_still_starts_empty(self):
        self.assertEqual(br.Progress(self.progress_path, strict=True).data, {})

    def test_progress_write_replaces_file_without_leaving_temp(self):
        p = br.Progress(self.progress_path)
        p.set("a", br.DONE)
        p.set("b", br.SUBMITTED)

        path = pathlib.Path(self.progress_path)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"a": br.DONE, "b": br.SUBMITTED})
        self.assertEqual(list(path.parent.glob("progress.json.*.tmp")), [])

    def test_submitting_record_keeps_payload_hash_and_can_be_reconciled(self):
        p = br.Progress(self.progress_path, strict=True)
        p.start("a", "payload-1")
        self.assertEqual(p.get("a"), br.SUBMITTING)
        self.assertEqual(p.record("a")["payload_hash"], "payload-1")
        p.finish("a", br.SUBMITTED, remote_id="99")
        restored = br.Progress(self.progress_path, strict=True)
        self.assertEqual(restored.get("a"), br.SUBMITTED)
        self.assertEqual(restored.record("a")["remote_id"], "99")
        self.assertEqual(restored.record("a")["payload_hash"], "payload-1")

    def test_progress_replace_failure_keeps_old_file_and_memory(self):
        p = br.Progress(self.progress_path)
        p.set("old", br.SUBMITTED)

        with mock.patch.object(br.os, "replace", side_effect=OSError("模拟替换失败")):
            with self.assertRaisesRegex(OSError, "模拟替换失败"):
                p.set("new", br.SUBMITTED)

        path = pathlib.Path(self.progress_path)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"old": br.SUBMITTED})
        self.assertIsNone(p.get("new"))
        self.assertEqual(list(path.parent.glob("progress.json.*.tmp")), [])

    def test_reset_progress_starts_empty(self):
        p = br.Progress(self.progress_path)
        p.set("a", br.DONE)
        seen = []
        r = br.run_buckets(["a"], self.done_runner(seen), key_of=lambda it: it,
                           progress=br.Progress(self.progress_path, reset=True),
                           dry_run=True, log=self.log)
        self.assertEqual((r.skipped, seen), (0, ["a"]))

    # ---------- 失败清场 / 日志 ----------
    def test_on_item_fail_is_called_and_its_error_is_swallowed(self):
        cleaned = []

        def boom(item):
            cleaned.append(item)
            raise RuntimeError("关弹窗也炸了")

        r = br.run_buckets([1], lambda it: False, on_item_fail=boom, log=self.log)
        self.assertEqual(cleaned, [1])
        self.assertEqual(r.failed, 1)

    def test_error_message_keeps_only_first_line(self):
        def run_one(item):
            raise RuntimeError("第一行\n第二行不该出现")

        br.run_buckets([1], run_one, log=self.log)
        self.assertIn("第一行", self.log.text())
        self.assertNotIn("第二行", self.log.text())

    # ---------- 自动重试（2026-10-15 加：治后台页面渲染抖动） ----------
    def test_retry_off_by_default(self):
        calls = []

        def run_one(item):
            calls.append(item)
            return False

        r = br.run_buckets([1], run_one, log=self.log)
        self.assertEqual(calls, [1])
        self.assertEqual(r.failed, 1)
        self.assertNotIn("↻", self.log.text())

    def test_first_fail_then_retry_succeeds(self):
        calls = []
        resets = []

        def run_one(item):
            calls.append(item)
            if len(calls) == 1:
                raise RuntimeError("下拉无此选项: 企业服务事业部 | 可见选项(0): []")
            return True

        r = br.run_buckets([1], run_one, retry=1,
                           on_item_retry=lambda it: resets.append(it), log=self.log)
        self.assertEqual(calls, [1, 1])
        self.assertEqual(resets, [1])
        self.assertEqual((r.attempted, r.done, r.failed), (1, 1, 0))
        self.assertIn("↻", self.log.text())
        self.assertEqual(r.status, br.OK)

    def test_should_retry_false_blocks_retry(self):
        calls = []

        def run_one(item):
            calls.append(item)
            return False

        r = br.run_buckets([1], run_one, retry=3,
                           should_retry=lambda it, e: False, log=self.log)
        self.assertEqual(calls, [1])
        self.assertEqual(r.failed, 1)
        self.assertNotIn("↻", self.log.text())

    def test_on_retry拿到异常并优先于普通重开(self):
        calls, seen, reset = [], [], []

        def run_one(item):
            calls.append(item)
            if len(calls) == 1:
                raise RuntimeError("Page.goto: Timeout 25000ms exceeded.")
            return True

        br.run_buckets(
            [1], run_one, retry=1, log=self.log,
            on_retry=lambda item, exc: seen.append((item, str(exc))),
            on_item_retry=lambda item: reset.append(item))
        self.assertEqual(calls, [1, 1])
        self.assertEqual(seen[0][0], 1)
        self.assertIn("Page.goto", seen[0][1])
        self.assertEqual(reset, [])

    def test_retry_exhausted_counts_as_one_failure(self):
        calls = []

        def run_one(item):
            calls.append(item)
            return False

        r = br.run_buckets([1], run_one, retry=2, abort_after=0, log=self.log)
        self.assertEqual(calls, [1, 1, 1])
        self.assertEqual((r.attempted, r.failed), (1, 1))
        self.assertTrue(r.aborted)

    # ---------- 模式二：丢失提交结果后定点对账 ----------
    def test_中断后定点对账发现已建则复用(self):
        seen = []
        p = br.Progress(self.progress_path, strict=True)
        p.start("a", es.payload_hash("payload-a"))

        r = br.run_buckets(
            ["a"], self.done_runner(seen), key_of=lambda it: it, progress=p,
            payload_of=lambda it: "payload-a",
            reconcile=lambda item: es.found("remote-" + item),
            dry_run=False, log=self.log)

        self.assertEqual(seen, [])
        self.assertEqual(r.skipped, 1)
        self.assertEqual(p.get("a"), br.SUBMITTED)
        self.assertEqual(p.record("a")["remote_id"], "remote-a")

    def test_中断后定点对账确认未建才重跑(self):
        seen = []
        p = br.Progress(self.progress_path, strict=True)
        p.start("a", es.payload_hash("payload-a"))

        def run_one(item):
            seen.append((item, p.get(item), p.record(item)["payload_hash"]))
            return br.SUBMITTED

        r = br.run_buckets(
            ["a"], run_one, key_of=lambda it: it, progress=p,
            payload_of=lambda it: "payload-a",
            reconcile=lambda item: es.absent(),
            dry_run=False, log=self.log)

        self.assertEqual(r.status, br.OK)
        self.assertEqual(seen, [("a", br.SUBMITTING, es.payload_hash("payload-a"))])
        self.assertEqual(p.get("a"), br.SUBMITTED)

    def test_unknown_remote_state_blocks_blind_retry(self):
        seen = []
        p = br.Progress(self.progress_path, strict=True)
        p.start("a", es.payload_hash("payload-a"))

        r = br.run_buckets(
            ["a"], self.done_runner(seen), key_of=lambda it: it, progress=p,
            payload_of=lambda it: "payload-a",
            reconcile=lambda item: es.unknown("接口超时"),
            dry_run=False, log=self.log)

        self.assertEqual(seen, [])
        self.assertEqual(r.warned, 1)
        self.assertEqual(p.get("a"), br.NEEDS_RECONCILE)

    def test_未记录过的新项不预读后台(self):
        seen = []
        p = br.Progress(self.progress_path, strict=True)

        r = br.run_buckets(
            ["a"], self.done_runner(seen), key_of=lambda it: it, progress=p,
            payload_of=lambda it: "payload-a",
            reconcile=lambda item: self.fail("新建项不应触发预读"),
            dry_run=False, log=self.log)

        self.assertEqual(seen, ["a"])
        self.assertEqual(r.status, br.OK)

    def test_payload_hash_mismatch_against_existing_remote_is_conflict(self):
        seen = []
        p = br.Progress(self.progress_path, strict=True)
        p.start("a", "old-hash")
        p.set("a", br.NEEDS_RECONCILE)

        r = br.run_buckets(
            ["a"], self.done_runner(seen), key_of=lambda it: it, progress=p,
            payload_of=lambda it: "new-hash",
            reconcile=lambda item: es.found("remote-a"),
            dry_run=False, log=self.log)

        self.assertEqual(seen, [])
        self.assertEqual(r.warned, 1)
        self.assertEqual(p.get("a"), br.NEEDS_RECONCILE)
        self.assertIn("payload", self.log.text())


if __name__ == "__main__":
    unittest.main()
