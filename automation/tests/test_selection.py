# -*- coding: utf-8 -*-
"""run_selection 的纯函数单测（不开浏览器）。

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

import run_selection as rs  # noqa: E402


class KeywordsTest(unittest.TestCase):
    def test_逗号分隔_去空格_去空项(self):
        aud = {"keywordGroup": {"keywords": " 剪辑 , 混剪 ,,  剪映 "}}
        self.assertEqual(rs.keywords_of(aud), ["剪辑", "混剪", "剪映"])

    def test_没写关键词给空表(self):
        self.assertEqual(rs.keywords_of({}), [])
        self.assertEqual(rs.keywords_of({"keywordGroup": {}}), [])

    def test_真实D桶词表是96个_回归锚点(self):
        path = REPO / "activities/火山引擎MediaKit/调整/2026-09-17-D桶换词重投.yaml"
        with open(path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        aud = [a for a in cfg["audiences"] if a["id"] == "D"][0]
        kws = rs.keywords_of(aud)
        self.assertEqual(len(kws), 96)
        self.assertEqual(kws[0], "解说")
        self.assertEqual(kws[-1], "图文转视频")


class CsvPathTest(unittest.TestCase):
    def test_文件名由脚本拼_带日期(self):
        out = rs.csv_path("数据/圈选", "2026-09-21_D桶96词_")
        self.assertTrue(out.endswith("_D桶96词_圈选博文_" + rs.time.strftime("%Y%m%d") + ".csv"))

    def test_不含空格_能直接喂给下一个脚本(self):
        self.assertNotIn(" ", rs.csv_path("数据/圈选", "2026-09-21_D桶96词_"))


class SummarizeTest(unittest.TestCase):
    def test_数博文数与总点击数_标题里的换行不算多行(self):
        txt = ('"article_id","title","article_url","last_30_days_pv"\n'
               '1,"a\nb","https://x/1",10\n'
               '2,"c","https://x/2",5\n')
        self.assertEqual(rs.summarize(txt), (2, 15, 7.5))

    def test_空文本给零(self):
        self.assertEqual(rs.summarize(""), (0, 0, 0.0))

    def test_非数字点击数跳过但不影响计数(self):
        txt = '"article_id","title","article_url","last_30_days_pv"\n1,"a","u",\n'
        self.assertEqual(rs.summarize(txt), (1, 0, 0.0))

    def test_台账表头只写一次_每行一条记录(self):
        d = ROOT / "_tmp" / "test_selection"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "圈选记录.md"
        try:
            rs.append_record(str(p), "2026-09-21 16:44", "D", 96, 51677, 3400000, 65.8, "a.csv")
            rs.append_record(str(p), "2026-09-22 10:00", "D", 96, 52000, 3500000, 67.3, "b.csv")
            text = p.read_text(encoding="utf-8")
            self.assertEqual(text.count("| 导出时间 |"), 1)
            self.assertIn("| 2026-09-21 16:44 | D | 96 | 51,677 | 3,400,000 | 65.8 | a.csv |", text)
            self.assertIn("b.csv", text)
        finally:
            p.unlink(missing_ok=True)


class RetryFetchTest(unittest.TestCase):
    """下载重试：大导出下载会超时/断流，重试是必须的（2026-09-29 实测两次超时）。"""

    def test_第一次失败_第二次成功(self):
        calls = []

        def fetch():
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError("Timeout 30000ms exceeded")
            return b"ok"

        self.assertEqual(rs.retry_fetch(fetch, attempts=3, log=lambda *a: None), b"ok")
        self.assertEqual(len(calls), 2)

    def test_全失败_抛RuntimeError并写清重试次数(self):
        def fetch():
            raise TimeoutError("boom")

        with self.assertRaises(RuntimeError) as cm:
            rs.retry_fetch(fetch, attempts=3, log=lambda *a: None)
        self.assertIn("已重试 3 次", str(cm.exception))

    def test_下载超时够大_Playwright默认30秒拉不动大导出(self):
        # 2026-09-29 实测：39.9 万行 105 秒、93.7 万行 165 秒
        self.assertGreaterEqual(rs.DOWNLOAD_TIMEOUT_MS, 600000)
        self.assertGreaterEqual(rs.DOWNLOAD_ATTEMPTS, 2)


if __name__ == "__main__":
    unittest.main()
