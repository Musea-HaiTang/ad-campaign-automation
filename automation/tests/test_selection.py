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
import workspace_repo as repo  # noqa: E402


class KeywordsTest(unittest.TestCase):
    def test_逗号分隔_去空格_去空项(self):
        aud = {"keywordGroup": {"keywords": " 剪辑 , 混剪 ,,  剪映 "}}
        self.assertEqual(rs.keywords_of(aud), ["剪辑", "混剪", "剪映"])

    def test_没写关键词给空表(self):
        self.assertEqual(rs.keywords_of({}), [])
        self.assertEqual(rs.keywords_of({"keywordGroup": {}}), [])

    def test_真实D桶词表是96个_回归锚点(self):
        path = REPO / "activities/火山引擎MediaKit/配置/火山引擎MediaKit-hang.yaml"
        if not path.exists():
            self.skipTest("需要本地真实活动样本，发布包中不含")
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

    def test_圈选结果写入数据库且同一桶同一时刻幂等(self):
        d = ROOT / "_tmp" / "test_selection_record"
        d.mkdir(parents=True, exist_ok=True)
        db = d / "data.db"
        if db.exists():
            db.unlink()
        conn = repo.connect(str(db))
        activity = repo.save_activity(conn, {
            "activity_key": "demo", "display_name": "示例",
            "brand": "示例", "owner": "hang", "name_prefix": "demo",
            "task_group_name": "demo", "activity_link": "https://example.com",
            "status": "active", "started_on": "2026-09-21", "ended_on": None,
        })
        repo.save_bucket(conn, activity["id"], {
            "bucket_key": "D", "display_name": "D类",
            "topic": "", "target": "", "keywords_text": "",
            "default_threshold_exposure": 1000, "status": "active",
        })
        conn.close()
        first = rs.record_selection("demo", "D", "2026-09-21 16:44",
                                    96, 51677, 3400000, str(db))
        again = rs.record_selection("demo", "D", "2026-09-21 16:44",
                                    96, 51677, 3400000, str(db))
        self.assertEqual(first["id"], again["id"])
        conn = repo.connect(str(db))
        rows = repo.list_selection_runs(conn, activity["id"])
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["keyword_count"], 96)
        self.assertEqual(rows[0]["article_count"], 51677)


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
