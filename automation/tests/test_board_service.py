# -*- coding: utf-8 -*-
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation" / "scripts"))

import board_service  # noqa: E402


class BoardServiceTest(unittest.TestCase):
    def test_只接受状态健康PID全部匹配的看板(self):
        state = {"pid": 123, "port": 8771}
        health = {"service": "ad_management-board", "pid": 123, "port": 8771}
        with mock.patch.object(board_service.runtime_state, "read_state", return_value=state), \
                mock.patch.object(board_service, "health", return_value=health), \
                mock.patch.object(board_service.runtime_state, "process_matches", return_value=True):
            self.assertEqual(board_service.current()["port"], 8771)

    def test_健康PID不匹配时不认作本项目(self):
        state = {"pid": 123, "port": 8771}
        health = {"service": "ad_management-board", "pid": 999, "port": 8771}
        with mock.patch.object(board_service.runtime_state, "read_state", return_value=state), \
                mock.patch.object(board_service, "health", return_value=health), \
                mock.patch.object(board_service.runtime_state, "pid_alive", return_value=True):
            self.assertEqual(board_service.current(), {})

    def test_stop只结束状态文件记录的PID(self):
        state = {"pid": 123, "port": 8771}
        with mock.patch.object(board_service, "current", return_value=state), \
                mock.patch.object(board_service.subprocess, "run") as run, \
                mock.patch.object(board_service.time, "sleep"), \
                mock.patch.object(board_service.runtime_state, "clear_state") as clear:
            self.assertEqual(board_service.stop(), 0)
        run.assert_called_once_with(["taskkill", "/F", "/T", "/PID", "123"], capture_output=True)
        clear.assert_called_once_with("board", pid=123)


if __name__ == "__main__":
    unittest.main()
