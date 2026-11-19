from __future__ import annotations

import importlib
import unittest

from automation.scripts.__main__ import COMMANDS


class CommandRouterTest(unittest.TestCase):
    def test_all_commands_import_and_expose_main(self):
        for name, module_name in COMMANDS.items():
            with self.subTest(command=name):
                module = importlib.import_module("automation.scripts." + module_name)
                self.assertTrue(callable(getattr(module, "main", None)))

    def test_unknown_command_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "未知命令"):
            importlib.import_module("automation.scripts.__main__").main(["missing"])


if __name__ == "__main__":
    unittest.main()
