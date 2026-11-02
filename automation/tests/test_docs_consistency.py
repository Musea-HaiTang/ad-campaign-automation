# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "automation",
    ROOT / "web",
    ROOT / "scripts",
    ROOT / "ad_output" / "AGENTS.md",
    ROOT / "ad_output" / "流程文档",
)
EXCLUDED_PARTS = {"tests", "__pycache__", "_tmp"}
EXCLUDED_FILES = {"发布前整改计划.md", "决策台账.md", "数据库迁移版本.md"}
SCAN_SUFFIXES = {".md", ".py", ".ps1", ".js", ".html"}
LEGACY_REFERENCES = (
    "判定门槛.yaml",
    "复盘动作.yaml",
    "数据/判定/",
    "圈选记录.md",
    "perf_db.py",
    "perf_payload.py",
    "audience_policy.py",
    "seed_demo.py",
    "广告投放数据.csv",
    "资源级累计.csv",
    "fetch_log",
    "daily_change",
    "批次/2026-",
)


def active_files():
    for root in SCAN_ROOTS:
        if root.is_file():
            yield root
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            if EXCLUDED_PARTS.intersection(path.parts) or path.name in EXCLUDED_FILES:
                continue
            yield path


class DocsConsistencyTest(unittest.TestCase):
    def test_运行文档和脚本不再引用废弃文件(self):
        hits = []
        for path in active_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in LEGACY_REFERENCES:
                if pattern in text:
                    hits.append(f"{path.relative_to(ROOT)}: {pattern}")
        self.assertEqual(hits, [], "发现废弃运行引用：\n" + "\n".join(hits))

    def test_关键运维文档存在(self):
        required = (
            ROOT / "automation" / "docs" / "数据库v2说明.md",
            ROOT / "automation" / "docs" / "数据库迁移版本.md",
            ROOT / "automation" / "docs" / "磁盘清理.md",
            ROOT / "automation" / "docs" / "巡检与自动复盘.md",
            ROOT / "automation" / "docs" / "复盘会话格式.md",
        )
        self.assertEqual([path for path in required if not path.is_file()], [])

    def test_README状态不把已完成项目写成进行中(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("项目正在按", readme)
        self.assertNotIn("继续完成 P1", readme)
        self.assertIn("P0 发布阻断项和 P1 长期维护整改", readme)


if __name__ == "__main__":
    unittest.main()
