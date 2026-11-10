# -*- coding: utf-8 -*-
from pathlib import Path
import sys
import unittest
from unittest import mock

from _temp import temp_workdir


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation" / "scripts"))

import board_service  # noqa: E402


class BoardServiceTest(unittest.TestCase):
    def health(self, pid=123, port=8771):
        return {
            "service": "ad_management-board",
            "pid": pid,
            "port": port,
            "host": "127.0.0.1",
            "db": board_service.V2_DB,
        }

    def test_只接受状态健康PID全部匹配的看板(self):
        state = {"pid": 123, "port": 8771}
        with mock.patch.object(board_service.runtime_state, "read_state", return_value=state), \
                mock.patch.object(board_service, "health", return_value=self.health()), \
                mock.patch.object(board_service.runtime_state, "process_matches", return_value=True):
            self.assertEqual(board_service.current()["port"], 8771)

    def test_健康PID不匹配时不认作本项目(self):
        state = {"pid": 123, "port": 8771}
        with mock.patch.object(board_service.runtime_state, "read_state", return_value=state), \
                mock.patch.object(board_service, "health", return_value=self.health(pid=999)), \
                mock.patch.object(board_service.runtime_state, "clear_state"):
            self.assertEqual(board_service.current(), {})

    def test_状态文件丢失时从实际端口找回看板(self):
        with mock.patch.object(board_service.runtime_state, "read_state", return_value={}), \
                mock.patch.object(
                    board_service.runtime_state, "listening_ports", return_value=[8777]
                ), \
                mock.patch.object(
                    board_service, "health", return_value=self.health(port=8777)
                ), \
                mock.patch.object(board_service.runtime_state, "write_state") as write:
            self.assertEqual(board_service.current(discover=True)["port"], 8777)
        write.assert_called_once()

    def test_进程查询不可用时仍复用健康看板(self):
        state = {"pid": 123, "port": 8771}
        with mock.patch.object(board_service.runtime_state, "read_state", return_value=state), \
                mock.patch.object(board_service, "health", return_value=self.health()), \
                mock.patch.object(
                    board_service.runtime_state, "process_matches",
                    return_value=True,
                ) as matches:
            self.assertEqual(board_service.current()["port"], 8771)
        self.assertTrue(matches.call_args.kwargs["allow_unknown"])

    def test_stop只结束状态文件记录的PID(self):
        state = {"pid": 123, "port": 8771}
        with mock.patch.object(board_service, "discover_boards", return_value=[]), \
                mock.patch.object(board_service, "current", return_value=state), \
                mock.patch.object(
                    board_service.runtime_state, "terminate_process", return_value=True
                ) as terminate, \
                mock.patch.object(board_service.time, "sleep"), \
                mock.patch.object(board_service.runtime_state, "clear_state") as clear:
            self.assertEqual(board_service.stop(), 0)
        terminate.assert_called_once_with(123, force=True)
        clear.assert_called_once_with("board")

    def test_start复用最早看板并清理重复实例(self):
        boards = [
            {"pid": 123, "port": 8770},
            {"pid": 456, "port": 8771},
        ]
        with mock.patch.object(board_service, "discover_boards", return_value=boards), \
                mock.patch.object(board_service.runtime_state, "write_state") as write, \
                mock.patch.object(
                    board_service.runtime_state, "terminate_process", return_value=True
                ) as terminate:
            self.assertEqual(board_service.start_hidden(), 0)
        write.assert_called_once_with("board", boards[0])
        terminate.assert_called_once_with(456, force=True)

    def test_端口扫描失败时仍按状态和健康接口复用(self):
        state = {"pid": 123, "port": 8771}
        with mock.patch.object(board_service, "discover_boards", return_value=[]), \
                mock.patch.object(board_service, "current", return_value=state):
            self.assertEqual(board_service.start_hidden(), 0)

    def test_MAC看板使用独立后台会话(self):
        state = {"pid": 123, "port": 8770}
        with temp_workdir("board-service-") as tmp, \
                mock.patch.object(board_service, "LOG", str(Path(tmp) / "board.log")), \
                mock.patch.object(board_service, "discover_boards", return_value=[]), \
                mock.patch.object(board_service, "current", side_effect=[{}, state]), \
                mock.patch.object(board_service.runtime_state, "read_state", return_value={}), \
                mock.patch.object(board_service.runtime_state, "IS_WINDOWS", False), \
                mock.patch.object(board_service.subprocess, "Popen") as popen:
            self.assertEqual(board_service.start_hidden(), 0)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()
