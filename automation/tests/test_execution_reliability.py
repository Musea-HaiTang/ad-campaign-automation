# -*- coding: utf-8 -*-
"""执行层可靠性回归：浏览器失活、回读三态、跨批账本键、运行日志。"""
import os
import pathlib
import shutil
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import csdn_ui  # noqa: E402
import bucket_runner  # noqa: E402
import check_campaign  # noqa: E402
import execution_state  # noqa: E402
import run_ads  # noqa: E402
import run_taskorder  # noqa: E402
from fakes import FakePage  # noqa: E402


class BrowserRecoveryTest(unittest.TestCase):
    def test_page_goto_timeout_is_browser_failure(self):
        exc = RuntimeError("Page.goto: Timeout 25000ms exceeded.")
        self.assertTrue(csdn_ui.is_browser_failure(exc))

    def test_locator_timeout_is_not_browser_failure(self):
        exc = RuntimeError("Locator.click: Timeout 8000ms exceeded waiting for item")
        self.assertFalse(csdn_ui.is_browser_failure(exc))

    def test_打开会话时失活就重启一次(self):
        dead = csdn_ui.BrowserUnresponsive("Page.set_content: Timeout 4000ms exceeded")
        with mock.patch.object(csdn_ui, "_open_checked_page", side_effect=[dead, "page"]), \
                mock.patch.object(csdn_ui.broker, "stop", return_value=1) as stopped:
            self.assertEqual(csdn_ui.open_healthy_page("pw", headed=False), "page")
        stopped.assert_called_once()


class ResourceVerifyTest(unittest.TestCase):
    def test_精确检查未确认时回读返回无法确认(self):
        s = csdn_ui.Session(FakePage())
        cfg = {"campaign": {"taskGroupName": "测试任务组"}, "audiences": []}
        with mock.patch.object(check_campaign, "check_resources_for_config",
                               return_value={"资源-A": None}):
            got = run_ads.verify_created_resources(s, cfg, ["资源-A"])
        self.assertIsNone(got)


class TaskorderProgressKeyTest(unittest.TestCase):
    def test_账本键必须跟批次任务名走(self):
        cfg = {"campaign": {"namePrefix": "测试-hang", "taskGroupName": "测试-hang"}}
        aud3 = {"id": "A", "topic": "主题", "nameSuffix": "-3"}
        aud4 = {"id": "A", "topic": "主题", "nameSuffix": "-4"}
        self.assertNotEqual(run_taskorder.progress_key(cfg, aud3),
                            run_taskorder.progress_key(cfg, aud4))
        self.assertIn("-3", run_taskorder.progress_key(cfg, aud3))

    def test_提交前字段失败会抛出可重试异常(self):
        exc = bucket_runner.pre_submit_error([
            ("业务线", "ok"),
            ("AB[对照组]", "fail"),
        ])
        self.assertIsInstance(exc, bucket_runner.PreSubmitValidationError)
        self.assertIn("AB[对照组]", str(exc))

    def test_提交前字段全通过不抛异常(self):
        self.assertIsNone(bucket_runner.pre_submit_error([
            ("业务线", "ok"),
            ("AB[对照组]", "ok"),
        ]))

    def test_提交前失败会走整桶重试并最终成功(self):
        calls = []

        def run_one(item):
            calls.append(item)
            if len(calls) == 1:
                raise bucket_runner.pre_submit_error([("AB[对照组]", "fail")])
            return bucket_runner.SUBMITTED

        report = bucket_runner.run_buckets(
            [1], run_one, retry=1, log=lambda *_: None,
        )
        self.assertEqual(calls, [1, 1])
        self.assertEqual(report.status, bucket_runner.OK)
        self.assertEqual(report.done, 1)

    def test_工单对账页面与接口都确认无才判缺失(self):
        with mock.patch.object(run_taskorder.remote_lookup, "open", return_value=object()), \
                mock.patch.object(run_taskorder.remote_lookup, "exact",
                                  return_value=execution_state.absent()), \
                mock.patch.object(run_taskorder, "_task_api_state",
                                  return_value=execution_state.absent()):
            state = run_taskorder.lookup_task(object(), "工单-A")
        self.assertEqual(state.kind, execution_state.ABSENT)

    def test_工单对账一边未确认不能判缺失(self):
        with mock.patch.object(run_taskorder.remote_lookup, "open", return_value=object()), \
                mock.patch.object(run_taskorder.remote_lookup, "exact",
                                  return_value=execution_state.absent()), \
                mock.patch.object(run_taskorder, "_task_api_state",
                                  return_value=execution_state.unknown("接口超时")):
            state = run_taskorder.lookup_task(object(), "工单-A")
        self.assertEqual(state.kind, execution_state.UNKNOWN)


class RunLogTest(unittest.TestCase):
    def test_运行日志落盘(self):
        td = ROOT / "_tmp" / ("runlog-test-%d" % os.getpid())
        shutil.rmtree(td, ignore_errors=True)
        td.mkdir(parents=True)
        try:
            shot_dir = pathlib.Path(td) / "logs" / "shots"
            with csdn_ui.run_log(shot_dir, script="测试脚本") as path:
                csdn_ui.log("第一条", 2)
            text = pathlib.Path(path).read_text(encoding="utf-8")
        finally:
            shutil.rmtree(td, ignore_errors=True)
        self.assertIn("测试脚本", text)
        self.assertIn("第一条 2", text)


if __name__ == "__main__":
    unittest.main()
