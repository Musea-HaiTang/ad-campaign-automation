# -*- coding: utf-8 -*-
"""cli（命令外壳）的单测：不开浏览器。

盯的是 2026-09-23 架构体检 候选 2 抽出来的那五件事：`--only` 的校验与过滤、
装载（目录与账本约定）、会话参数、结果三态与退出码、循环外异常的收尾。
这些原先在 7 个 `run_*.py` 里各写一遍（`--only` 的报错文案 4 处逐字相同），
现在只有一处，就得有测试守着——不然下次分叉照样发生。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v
"""
import os
import pathlib
import sys
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
sys.path.insert(0, str(ROOT / "scripts"))

import bucket_runner  # noqa: E402
import cli  # noqa: E402

AUDS = [{"id": "A"}, {"id": "B"}, {"id": "C"}]


def mkargs(**kw):
    """假命令行参数：默认彩排、不带头、没有 --only。"""
    base = dict(config="配置.yaml", submit=False, headed=False, reset_progress=False, only="")
    base.update(kw)
    return types.SimpleNamespace(**base)


class OnlyTest(unittest.TestCase):
    def test_没给不过滤(self):
        self.assertEqual(cli.only_buckets("", AUDS), [])
        self.assertEqual(cli.only_buckets(None, AUDS), [])

    def test_大小写不敏感且去掉空白(self):
        self.assertEqual(cli.only_buckets(" a , c ", AUDS), ["A", "C"])

    def test_未知桶当场报错_文案含可选桶(self):
        with self.assertRaises(SystemExit) as e:
            cli.only_buckets("A,Z", AUDS)
        self.assertEqual(str(e.exception), "--only 里有不存在的桶：Z（本活动可选：A, B, C）")

    def test_过滤(self):
        self.assertEqual([a["id"] for a in cli.keep_buckets(AUDS, ["B"])], ["B"])
        self.assertEqual(cli.keep_buckets(AUDS, []), AUDS)


class ParserTest(unittest.TestCase):
    def test_共用开关齐全(self):
        ap = cli.parser("真建（默认彩排）", only=True)
        self.assertEqual({a.dest for a in ap._actions},
                         {"help", "config", "submit", "headed", "reset_progress", "only"})

    def test_按需加减开关(self):
        ap = cli.parser("真建（默认彩排）", config=False, only=False, reset_progress=False)
        self.assertEqual({a.dest for a in ap._actions}, {"help", "submit", "headed"})

    def test_帮助文案来自共用常量(self):
        ap = cli.parser("真建（默认彩排）", only=True)
        helps = {a.dest: a.help for a in ap._actions}
        self.assertEqual(helps["config"], cli.CONFIG_HELP)
        self.assertEqual(helps["headed"], cli.HEADED_HELP)
        self.assertEqual(helps["reset_progress"], cli.RESET_HELP)
        self.assertEqual(helps["only"], cli.ONLY_HELP)
        self.assertEqual(helps["submit"], "真建（默认彩排）", "--submit 的说明各脚本自述")


class ContextTest(unittest.TestCase):
    """装载：目录与账本按约定拼、--only 落到这一趟的桶上。"""

    def setUp(self):
        self.act = ROOT / "_tmp" / "test_cli" / self._testMethodName
        cfg = {"label": "火山引擎MediaKit", "audiences": [dict(a) for a in AUDS]}
        self.patchers = [mock.patch.object(cli.campaign, "load_or_exit", return_value=cfg),
                         mock.patch.object(cli.campaign, "activity_dir", return_value=str(self.act))]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_目录与账本按约定拼(self):
        ctx = cli.context(mkargs(only="b"), shots="ads_shots", progress="ads_progress.json")
        self.assertEqual(ctx.shot_dir, os.path.join(str(self.act), "日志", "ads_shots"))
        self.assertEqual(ctx.progress.path, os.path.join(str(self.act), "日志", "ads_progress.json"))
        self.assertEqual([a["id"] for a in ctx.auds], ["B"], "--only 要落到这一趟的桶上")
        self.assertEqual(ctx.report.status, "OK", "装载完就有一份干净的结果，异常收尾才有东西可标")

    def test_不给账本就不开(self):
        ctx = cli.context(mkargs(), shots="audience_shots")
        self.assertIsNone(ctx.progress)
        self.assertEqual(len(ctx.auds), 3, "没有 --only 就是全部桶")

    def test_未知桶当场报错(self):
        with self.assertRaises(SystemExit):
            cli.context(mkargs(only="Z"), shots="ads_shots")

    def test_账本路径只有一处拼(self):
        self.assertEqual(cli.progress_path("/act", "x_progress.json"),
                         os.path.join("/act", "日志", "x_progress.json"))
        reset = cli.open_progress("/act", "x_progress.json", reset=True)
        self.assertEqual(reset.data, {}, "reset=True 就是空账本")

    def test_正式提交时账本按严格模式打开(self):
        with mock.patch.object(cli, "open_progress", return_value="strict-ledger") as opened:
            ctx = cli.context(mkargs(submit=True), shots="ads_shots",
                              progress="ads_progress.json")
        self.assertEqual(ctx.progress, "strict-ledger")
        opened.assert_called_once_with(
            str(self.act), "ads_progress.json", reset=False, strict=True)

    def test_正式账本损坏时用退出码2停下(self):
        path = pathlib.Path(self.act) / "日志" / "broken.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ 坏", encoding="utf-8")
        with self.assertRaises(SystemExit) as e:
            cli.open_progress(str(self.act), "broken.json", strict=True)
        self.assertEqual(e.exception.code, 2)

    def test_彩排配置禁止正式提交(self):
        with mock.patch.object(cli.campaign, "is_rehearsal", return_value=True):
            with self.assertRaisesRegex(SystemExit, "彩排配置"):
                cli.context(mkargs(submit=True), shots="ads_shots")


class SessionTest(unittest.TestCase):
    def test_会话参数由外壳定(self):
        shots = os.path.join("/act", "日志", "x_shots")
        ctx = cli.Context({}, "/act", shots, [], [])
        seen = {}

        class FakeSession:
            def __enter__(self):
                return "手柄"

            def __exit__(self, *a):
                return False

        def fake_session(**kw):
            seen.clear()
            seen.update(kw)
            return FakeSession()

        with mock.patch.object(cli.ui, "session", fake_session):
            with ctx.session(mkargs(submit=True)) as s:
                self.assertEqual(s, "手柄")
            self.assertEqual(seen, {"headed": False, "dry_run": False, "shot_dir": shots})
            ctx.session(mkargs(submit=False, headed=True))
            self.assertEqual(seen, {"headed": True, "dry_run": True, "shot_dir": shots})
            ctx.session(mkargs(submit=True), dry_run=True)
            self.assertTrue(seen["dry_run"], "可以显式盖掉（--delete 那种照旧不提交）")


class FinishTest(unittest.TestCase):
    def _finish(self, report):
        logs = []
        with mock.patch.object(cli.ui, "log", logs.append):
            with self.assertRaises(SystemExit) as e:
                cli.finish(report)
        return logs, e.exception.code

    def test_结果三态与退出码(self):
        ok = bucket_runner.RunReport()
        self.assertEqual(self._finish(ok), (["RESULT: OK | 总用时 0.0 秒"], 0))

        warn = bucket_runner.RunReport()
        warn.warned = 1
        self.assertEqual(self._finish(warn), (["RESULT: HAS_WARN | 总用时 0.0 秒"], 1))

        bad = bucket_runner.RunReport()
        bad.failed = 1
        self.assertEqual(self._finish(bad), (["RESULT: HAS_FAILURES | 总用时 0.0 秒"], 1))

        fatal = bucket_runner.RunReport()
        fatal.fatal = True
        self.assertEqual(self._finish(fatal), (["RESULT: HAS_FAILURES | 总用时 0.0 秒"], 1))

    def test_fatal_只取首行_长了截断(self):
        ctx = cli.Context({}, "", "", [], [])
        logs = []
        with mock.patch.object(cli.ui, "log", logs.append):
            cli.fatal(ctx, RuntimeError("第一行\n第二行"))
            self.assertEqual(logs, ["  ✗ 失败:第一行"], "playwright 的调用日志别整屏刷出来")
            cli.fatal(ctx, RuntimeError("y" * 500))
            self.assertEqual(logs[-1], "  ✗ 失败:" + "y" * 160)
        self.assertTrue(ctx.report.fatal)
        self.assertEqual(self._finish(ctx.report), (["RESULT: HAS_FAILURES | 总用时 0.0 秒"], 1))

    def test_不走结果的命令也能共用收尾(self):
        logs = []
        with mock.patch.object(cli.ui, "log", logs.append):
            with self.assertRaises(SystemExit) as e:
                cli.exit_with("HAS_WARN（提交了但回读没查到，下次重跑）", 1)
        self.assertEqual(logs, ["RESULT: HAS_WARN（提交了但回读没查到，下次重跑）"])
        self.assertEqual(e.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
