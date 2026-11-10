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
        with mock.patch.object(runtime_state, "listening_ports", return_value=[8770, 8771]):
            self.assertEqual(runtime_state.next_free_port(8770), 8772)

    def test_进程身份要求全部片段匹配(self):
        info = {"CommandLine": r'"python.exe" app.py --db "D:\repo\activities\db.sqlite"'}
        with mock.patch.object(runtime_state, "process_info", return_value=info):
            self.assertTrue(runtime_state.process_matches(1, [r"D:\repo", "app.py"]))
            self.assertFalse(runtime_state.process_matches(1, [r"D:\repo", "other.py"]))

    def test_进程信息不可用时可选择接受未知(self):
        with mock.patch.object(runtime_state, "process_info", return_value={}):
            self.assertFalse(runtime_state.process_matches(1, ["app.py"]))
            self.assertTrue(
                runtime_state.process_matches(1, ["app.py"], allow_unknown=True)
            )

    def test_一次解析多个监听端口(self):
        rows = """  TCP    127.0.0.1:8770    0.0.0.0:0    LISTENING    123
  TCP    127.0.0.1:8777    0.0.0.0:0    LISTENING    456
  TCP    127.0.0.1:9000    0.0.0.0:0    LISTENING    789
"""
        with mock.patch.object(runtime_state, "IS_WINDOWS", True), \
                mock.patch.object(
                    runtime_state, "run_hidden",
                    return_value=mock.Mock(stdout=rows),
                ):
            self.assertEqual(runtime_state.listening_ports(8770, 10), [8770, 8777])

    def test_MAC解析_LSOF监听端口(self):
        rows = """p123
n127.0.0.1:8770
p456
n[::1]:8777
"""
        self.assertEqual(
            runtime_state._parse_lsof_listeners(rows),
            {8770: [123], 8777: [456]},
        )

    def test_MAC端口扫描调用_LSOF(self):
        rows = "p123\nn127.0.0.1:8770\n"
        with mock.patch.object(runtime_state, "IS_WINDOWS", False), \
                mock.patch.object(runtime_state.shutil, "which", return_value="/usr/sbin/lsof"), \
                mock.patch.object(
                    runtime_state, "run_hidden",
                    return_value=mock.Mock(stdout=rows),
                ) as run:
            self.assertEqual(runtime_state.listener_map(), {8770: [123]})
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn"],
        )

    def test_MAC结束进程使用系统信号(self):
        with mock.patch.object(runtime_state, "IS_WINDOWS", False), \
                mock.patch.object(runtime_state.os, "kill") as kill:
            self.assertTrue(runtime_state.terminate_process(123, force=True))
        kill.assert_called_once()

    def test_MAC读取完整命令行(self):
        rows = """123 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir=/repo/.browser-profile
456 /repo/.venv/bin/python app.py
"""
        with mock.patch.object(runtime_state, "IS_WINDOWS", False), \
                mock.patch.object(
                    runtime_state, "run_hidden",
                    return_value=mock.Mock(stdout=rows),
                ) as run:
            processes = runtime_state.process_commands()
        self.assertIn("--user-data-dir=/repo/.browser-profile", processes[123])
        self.assertEqual(run.call_args.args[0], ["/bin/ps", "-ww", "-axo", "pid=,command="])

    def test_后台进程参数按平台选择(self):
        with mock.patch.object(runtime_state, "IS_WINDOWS", False):
            self.assertEqual(
                runtime_state.detached_process_kwargs(),
                {"start_new_session": True},
            )
        with mock.patch.object(runtime_state, "IS_WINDOWS", True):
            self.assertIn("creationflags", runtime_state.detached_process_kwargs())

    def test_后台命令在_WINDOWS_使用隐藏窗口(self):
        if not runtime_state.HIDDEN_FLAGS:
            self.skipTest("仅 Windows 需要隐藏控制台参数")
        with mock.patch.object(runtime_state.subprocess, "run") as run:
            runtime_state.run_hidden(["cmd.exe", "/c", "exit 0"], capture_output=True)
        self.assertTrue(
            run.call_args.kwargs["creationflags"] & runtime_state.HIDDEN_FLAGS
        )

    def test_文件锁阻止第二个持有者(self):
        with temp_workdir("runtime-lock-") as tmp:
            path = Path(tmp) / "service.lock"
            first = runtime_state.acquire_file_lock(path)
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(runtime_state.acquire_file_lock(path))
            finally:
                runtime_state.release_file_lock(first)
            second = runtime_state.acquire_file_lock(path)
            self.assertIsNotNone(second)
            runtime_state.release_file_lock(second)


if __name__ == "__main__":
    unittest.main()
