# -*- coding: utf-8 -*-
from pathlib import Path
import sys
import unittest
from unittest import mock

from _temp import temp_workdir


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation" / "scripts"))

import runtime_state  # noqa: E402


class RuntimeStateTest(unittest.TestCase):
    def test_状态写入读取和按PID清理(self):
        with temp_workdir("runtime-state-") as tmp:
            path = Path(tmp) / "state.json"
            with mock.patch.dict(runtime_state.STATE_PATHS, {"test": path}):
                runtime_state.write_state("test", {"pid": 12, "port": 8771})
                self.assertEqual(runtime_state.read_state("test")["port"], 8771)
                runtime_state.clear_state("test", pid=99)
                self.assertTrue(path.exists())
                runtime_state.clear_state("test", pid=12)
                self.assertFalse(path.exists())

    def test_端口回退跳过占用端口(self):
        ports = iter([False, False, True])
        with mock.patch.object(runtime_state, "is_free", side_effect=lambda _p: next(ports)):
            self.assertEqual(runtime_state.next_free_port(8770), 8772)

    def test_进程身份要求全部片段匹配(self):
        info = {"CommandLine": r'"python.exe" app.py --db "D:\repo\activities\db.sqlite"'}
        with mock.patch.object(runtime_state, "process_info", return_value=info):
            self.assertTrue(runtime_state.process_matches(1, [r"D:\repo", "app.py"]))
            self.assertFalse(runtime_state.process_matches(1, [r"D:\repo", "other.py"]))


if __name__ == "__main__":
    unittest.main()
