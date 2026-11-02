# -*- coding: utf-8 -*-
import datetime
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import cleanup  # noqa: E402


class CleanupTest(unittest.TestCase):
    def _write(self, path: Path, text: str = "x") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _age(self, path: Path, now: datetime.datetime, days: float) -> None:
        stamp = (now - datetime.timedelta(days=days)).timestamp()
        os.utime(path, (stamp, stamp))

    def test_按期限清理日志截图和临时文件(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            now = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.timezone.utc)
            old_log = repo / "activities" / "demo" / "日志" / "runs" / "old.log"
            new_log = repo / "activities" / "demo" / "日志" / "runs" / "new.log"
            old_shot = repo / "activities" / "demo" / "日志" / "shots" / "old.png"
            new_shot = repo / "activities" / "demo" / "日志" / "shots" / "new.png"
            progress = repo / "activities" / "demo" / "日志" / "progress.json"
            old_tmp = repo / "automation" / "_tmp" / "old.tmp"
            new_tmp = repo / "automation" / "_tmp" / "new.tmp"
            for path in (old_log, new_log, old_shot, new_shot, progress, old_tmp, new_tmp):
                self._write(path)
            self._age(old_log, now, 8)
            self._age(new_log, now, 2)
            self._age(old_shot, now, 31)
            self._age(new_shot, now, 10)
            self._age(progress, now, 60)
            self._age(old_tmp, now, 2)

            result = cleanup.cleanup_project_files(repo, now=now)

            self.assertFalse(old_log.exists())
            self.assertTrue(new_log.exists())
            self.assertFalse(old_shot.exists())
            self.assertTrue(new_shot.exists())
            self.assertTrue(progress.exists())
            self.assertFalse(old_tmp.exists())
            self.assertTrue(new_tmp.exists())
            self.assertEqual(len(result["removed"]["logs"]), 1)
            self.assertEqual(len(result["removed"]["screenshots"]), 1)
            self.assertEqual(len(result["removed"]["temp"]), 1)

    def test_浏览器缓存清理保留登录态和扩展配置(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / ".browser-profile"
            cache_files = [
                profile / "Default" / "Cache" / "data_0",
                profile / "Default" / "Code Cache" / "code",
                profile / "component_crx_cache" / "component",
            ]
            protected = [
                profile / "Default" / "Network" / "Cookies",
                profile / "Local State",
                profile / "Default" / "Preferences",
                profile / "Default" / "Extensions" / "extension" / "manifest.json",
                profile / "Default" / "Service Worker" / "CacheStorage" / "site",
                profile / "Default" / "Service Worker" / "ScriptCache" / "script",
            ]
            for path in cache_files + protected:
                self._write(path)

            cleanup.clean_browser_cache(profile)

            self.assertTrue(all(not path.exists() for path in cache_files))
            self.assertTrue(all(path.exists() for path in protected))

    def test_七天内已检查时跳过浏览器缓存(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile"
            cache = profile / "Default" / "Cache" / "data"
            self._write(cache)
            now = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.timezone.utc)
            state = root / "browser-cleanup.json"
            state.write_text(json.dumps({
                "last_check": (now - datetime.timedelta(days=2)).isoformat(),
            }), encoding="utf-8")

            result = cleanup.maybe_clean_browser_profile(profile, state, now=now)

            self.assertEqual(result["status"], "skipped")
            self.assertTrue(cache.exists())

    def test_profile超过上限时等待确认(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile"
            cache = profile / "Default" / "Cache" / "data"
            self._write(cache, "12345")
            now = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.timezone.utc)
            result = cleanup.maybe_clean_browser_profile(
                profile,
                root / "state.json",
                now=now,
                profile_limit=1,
            )
            self.assertEqual(result["status"], "needs_confirmation")
            self.assertTrue(cache.exists())

    def test_浏览器运行中拒绝手动清理(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            cache = profile / "Default" / "Cache" / "data"
            self._write(cache)
            with mock.patch.object(cleanup, "browser_is_running", return_value=True):
                with self.assertRaises(RuntimeError):
                    cleanup.clean_browser_profile(profile)
            self.assertTrue(cache.exists())

    def test_深度清理只额外删除可重建组件缓存(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            component_cache = profile / "ProvenanceData" / "model.bin"
            cookies = profile / "Default" / "Network" / "Cookies"
            self._write(component_cache)
            self._write(cookies)

            cleanup.clean_browser_cache(profile, deep=True)

            self.assertFalse(component_cache.exists())
            self.assertTrue(cookies.exists())


if __name__ == "__main__":
    unittest.main()
