# -*- coding: utf-8 -*-
"""运行测试并将结果写入 JSON，供 AI 或自动化脚本读取。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "automation" / "tests"
REPORTS = ROOT / "automation" / "_tmp" / "pytest-reports"
SAFE_DELETE_PREFIX = "CODEBUDDY_SAFE_DELETE_"


def choose_mode(requested: str, environ: dict[str, str]) -> tuple[str, str]:
    if requested != "auto":
        return requested, "命令行指定"
    if any(key.startswith(SAFE_DELETE_PREFIX) for key in environ):
        return "by-file", "检测到 WorkBuddy 安全删除垫片环境"
    return "full", "未检测到 WorkBuddy 安全删除垫片环境"


def parse_report(path: Path) -> dict:
    root = ET.parse(path).getroot()
    tests = failed = errors = skipped = 0
    failures = []
    for suite in root.iter("testsuite"):
        tests += int(suite.attrib.get("tests", 0))
        failed += int(suite.attrib.get("failures", 0))
        errors += int(suite.attrib.get("errors", 0))
        skipped += int(suite.attrib.get("skipped", 0))
    for case in root.iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        name = case.attrib.get("name", "")
        classname = case.attrib.get("classname", "")
        failures.append(f"{classname}::{name}".strip(":"))
    return {
        "tests": tests,
        "passed": max(0, tests - failed - errors - skipped),
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "failures": failures,
    }


def run_pytest(python: str, targets: list[Path], report: Path) -> dict:
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.time()
    command = [
        python,
        "-m",
        "pytest",
        "-q",
        *map(str, targets),
        f"--junitxml={report}",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = completed.stdout
        return_code = completed.returncode
    except OSError as exc:
        output = str(exc)
        return_code = None

    if not report.exists():
        return {
            "status": "failed",
            "returnCode": return_code,
            "tests": 1,
            "passed": 0,
            "failed": 1,
            "errors": 0,
            "skipped": 0,
            "failures": ["pytest 未生成结果文件"],
            "output": output[-12000:],
            "durationSeconds": round(time.time() - started, 3),
        }
    try:
        result = parse_report(report)
    except (ET.ParseError, OSError) as exc:
        return {
            "status": "failed",
            "returnCode": return_code,
            "tests": 1,
            "passed": 0,
            "failed": 1,
            "errors": 0,
            "skipped": 0,
            "failures": [f"测试报告无法读取：{exc}"],
            "output": output[-12000:],
            "durationSeconds": round(time.time() - started, 3),
        }
    result.update({
        "status": "ok" if result["failed"] == 0 and result["errors"] == 0 else "failed",
        "returnCode": return_code,
        "output": "" if result["failed"] == 0 and result["errors"] == 0 else output[-12000:],
        "durationSeconds": round(time.time() - started, 3),
    })
    return result


def run_suite(python: str, mode: str) -> dict:
    REPORTS.mkdir(parents=True, exist_ok=True)
    if mode == "full":
        result = run_pytest(python, [TESTS], REPORTS / "all.xml")
        result["targets"] = ["automation/tests"]
        return result

    files = sorted(TESTS.glob("test_*.py"))
    results = []
    for path in files:
        item = run_pytest(python, [path], REPORTS / f"{path.stem}.xml")
        item["path"] = str(path.relative_to(ROOT))
        results.append(item)
    summary = {
        key: sum(item[key] for item in results)
        for key in ("tests", "passed", "failed", "errors", "skipped")
    }
    ok = bool(files) and all(item["status"] == "ok" for item in results)
    return {
        "status": "ok" if ok else "failed",
        "tests": summary["tests"],
        "passed": summary["passed"],
        "failed": summary["failed"],
        "errors": summary["errors"],
        "skipped": summary["skipped"],
        "targets": [str(path.relative_to(ROOT)) for path in files],
        "results": results,
        "durationSeconds": round(sum(item["durationSeconds"] for item in results), 3),
    }


def write_result(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="运行测试并生成机器可读结果")
    parser.add_argument("--mode", choices=("auto", "full", "by-file"), default="auto")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", default=str(ROOT / ".local" / "test-results.json"))
    args = parser.parse_args()

    mode, reason = choose_mode(args.mode, os.environ)
    result = run_suite(args.python, mode)
    result.update({
        "mode": mode,
        "modeReason": reason,
        "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    write_result(output, result)
    print(
        "TEST_RESULT: {status} | mode={mode} | passed={passed} "
        "failed={failed} errors={errors} skipped={skipped}".format(
            status=result["status"],
            mode=mode,
            passed=result["passed"],
            failed=result["failed"],
            errors=result["errors"],
            skipped=result["skipped"],
        )
    )
    print(f"TEST_RESULT_FILE: {output}")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
