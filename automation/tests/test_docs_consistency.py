# -*- coding: utf-8 -*-
from pathlib import Path
import re
import unittest
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "运营使用说明.md",
    ROOT / "automation",
    ROOT / "web",
    ROOT / "scripts",
    ROOT / "activities" / "_示例活动",
    ROOT / "ad_output" / "AGENTS.md",
    ROOT / "ad_output" / "流程文档",
)
EXCLUDED_PARTS = {"tests", "__pycache__", "_tmp"}
EXCLUDED_FILES = {"决策台账.md", "数据库迁移版本.md"}
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
    "push_github.ps1",
    "scripts/setup.ps1",
    "scripts/verify_tests.ps1",
)
LOCAL_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:\\Users\\"),
    re.compile(r"(?i)D:\\Codex_WorkingSpace"),
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

    def test_废弃入口未回流(self):
        self.assertFalse((ROOT / "scripts" / "setup.ps1").exists())
        self.assertFalse((ROOT / "scripts" / "verify_tests.ps1").exists())
        self.assertFalse((ROOT / "scripts" / "push_github.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "setup_ai.py").is_file())
        self.assertTrue((ROOT / "scripts" / "verify_tests.py").is_file())

    def test_CI覆盖_Windows_macOS和Python支持范围(self):
        workflow = (
            ROOT / ".github" / "workflows" / "python-compatibility.yml"
        ).read_text(encoding="utf-8")
        for value in (
            "windows-latest",
            "macos-latest",
            '"3.11"',
            '"3.12"',
            '"3.13"',
            '"3.14"',
            '"3.15"',
        ):
            self.assertIn(value, workflow)

    def test_关键运维文档存在(self):
        required = (
            ROOT / "README.md",
            ROOT / "AGENTS.md",
            ROOT / "AI一键部署.md",
            ROOT / "运营使用说明.md",
            ROOT / "automation" / "README.md",
            ROOT / "automation" / "docs" / "执行层全流程.md",
            ROOT / "automation" / "docs" / "数据库说明.md",
            ROOT / "automation" / "docs" / "数据库迁移版本.md",
            ROOT / "automation" / "docs" / "磁盘清理.md",
            ROOT / "automation" / "docs" / "部署说明.md",
            ROOT / "automation" / "docs" / "登录与验收.md",
            ROOT / "automation" / "docs" / "故障排查.md",
            ROOT / "automation" / "docs" / "巡检与自动复盘.md",
            ROOT / "automation" / "docs" / "复盘会话格式.md",
            ROOT / "ad_output" / "AGENTS.md",
            ROOT / "ad_output" / "流程文档" / "CSDN广告投放自动化流程.md",
        )
        self.assertEqual([path for path in required if not path.is_file()], [])

    def test_发布文档的相对链接都有目标文件(self):
        missing = []
        for path in active_files():
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
                    missing.append(f"{path.relative_to(ROOT)}: {target}")
        self.assertEqual(missing, [], "发布文档存在失效链接：\n" + "\n".join(missing))

    def test_示例活动链接只使用保留域名(self):
        config_dir = ROOT / "activities" / "_示例活动" / "配置"
        for path in config_dir.rglob("*.yaml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            campaign = data.get("campaign") or {}
            link = campaign.get("activityLink")
            if not link:
                continue
            host = (urlparse(str(link)).hostname or "").lower()
            self.assertTrue(
                host == "example.com" or host.endswith(".example.com"),
                "%s 的活动链接必须使用 example.com：%s" % (path, link),
            )

    def test_公开内容不写本机绝对路径(self):
        hits = []
        for path in active_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in LOCAL_PATH_PATTERNS:
                if pattern.search(text):
                    hits.append(str(path.relative_to(ROOT)))
                    break
        self.assertEqual(hits, [], "发现本机绝对路径：\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
