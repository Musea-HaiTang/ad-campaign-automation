# -*- coding: utf-8 -*-
import fnmatch
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
RELEASE_ALLOWLIST = ROOT / "scripts" / "release_allowlist.txt"
SCAN_ROOTS = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "运营使用说明.md",
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
MACHINE_SPECIFIC_REFERENCES = (
    "3.12.4",
    "3.14.6",
    "本机默认 `python`",
    "启动浏览器需提权",
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


def release_patterns():
    return [
        line.strip()
        for line in RELEASE_ALLOWLIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def release_files():
    patterns = release_patterns()
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns):
            yield path, relative


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
            ROOT / "README.md",
            ROOT / "AGENTS.md",
            ROOT / "运营使用说明.md",
            ROOT / "automation" / "README.md",
            ROOT / "automation" / "docs" / "执行层全流程.md",
            ROOT / "automation" / "docs" / "数据库v2说明.md",
            ROOT / "automation" / "docs" / "数据库迁移版本.md",
            ROOT / "automation" / "docs" / "磁盘清理.md",
            ROOT / "automation" / "docs" / "巡检与自动复盘.md",
            ROOT / "automation" / "docs" / "复盘会话格式.md",
            ROOT / "ad_output" / "AGENTS.md",
            ROOT / "ad_output" / "流程文档" / "CSDN广告投放自动化流程.md",
        )
        self.assertEqual([path for path in required if not path.is_file()], [])

    def test_关键运维文档都进入发布白名单(self):
        patterns = release_patterns()
        required = (
            "README.md",
            "AGENTS.md",
            "运营使用说明.md",
            "automation/README.md",
            "automation/docs/执行层全流程.md",
            "automation/docs/数据库v2说明.md",
            "automation/docs/数据库迁移版本.md",
            "automation/docs/磁盘清理.md",
            "automation/docs/巡检与自动复盘.md",
            "automation/docs/复盘会话格式.md",
            "ad_output/AGENTS.md",
            "ad_output/流程文档/CSDN广告投放自动化流程.md",
        )
        missing = [
            path for path in required
            if not any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
        ]
        self.assertEqual(missing, [], "关键文档未进入发布白名单：\n" + "\n".join(missing))

    def test_发布文档的相对链接都有目标文件(self):
        missing = []
        for path, relative in release_files():
            if path.suffix.lower() != ".md":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                target = target.strip().strip("<>")
                if target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                target_path = target.split("#", 1)[0]
                if not target_path or any(char in target_path for char in "<>{}*"):
                    continue
                resolved = (path.parent / target_path).resolve()
                if not resolved.exists():
                    missing.append(f"{relative}: {target}")
        self.assertEqual(missing, [], "发布文档存在失效链接：\n" + "\n".join(missing))

    def test_README状态不把已完成项目写成进行中(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("项目正在按", readme)
        self.assertNotIn("继续完成 P1", readme)
        self.assertIn("P0 发布阻断项和 P1 长期维护整改", readme)

    def test_环境文档不写个人机器Python补丁版本(self):
        hits = []
        for path in active_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in MACHINE_SPECIFIC_REFERENCES:
                if pattern in text:
                    hits.append(f"{path.relative_to(ROOT)}: {pattern}")
        self.assertEqual(hits, [], "发现机器特定环境表述：\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
