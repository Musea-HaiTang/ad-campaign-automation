# -*- coding: utf-8 -*-
"""AI 环境一键部署：直接从 Python 完成安装、配置和验收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
SETUP_RESULT = LOCAL / "setup-result.json"
SETUP_LOG = LOCAL / "setup-ai.log"


class SetupError(RuntimeError):
    pass


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(message)
    with SETUP_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run(
    command: list[str],
    check: bool = False,
    timeout_seconds: int = 300,
) -> subprocess.CompletedProcess:
    log("$ " + " ".join(command))
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(
            command,
            124,
            stdout=(exc.stdout or "") + f"\n命令超时（{timeout_seconds} 秒）",
        )
    if completed.stdout:
        with SETUP_LOG.open("a", encoding="utf-8") as handle:
            handle.write(completed.stdout.rstrip() + "\n")
    if check and completed.returncode != 0:
        raise SetupError(
            f"命令失败（{completed.returncode}）：{' '.join(command)}\n"
            f"{completed.stdout[-2000:]}"
        )
    return completed


def python_info(python: str) -> dict:
    probe = LOCAL / f"python-probe-{time.time_ns()}.json"
    code = (
        "import json,pathlib,sys; "
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({"
        "'version':'%d.%d.%d' % sys.version_info[:3],"
        "'executable':sys.executable"
        "}),encoding='utf-8')"
    )
    run([python, "-c", code, str(probe)])
    if not probe.exists():
        raise SetupError(f"Python 探测未生成结果：{python}")
    try:
        return json.loads(probe.read_text(encoding="utf-8"))
    finally:
        probe.unlink(missing_ok=True)


def compatible(info: dict) -> bool:
    major, minor, _ = map(int, info["version"].split("."))
    return major == 3 and 12 <= minor <= 14


def ensure_venv() -> tuple[str, dict]:
    base = python_info(sys.executable)
    log(f"基础 Python：{base['version']} ({base['executable']})")
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        if not compatible(base):
            raise SetupError("基础 Python 版本不在 3.12-3.14 范围内")
        run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    if not venv_python.exists():
        raise SetupError("创建 .venv 失败")
    info = python_info(str(venv_python))
    if not compatible(info):
        raise SetupError(f".venv Python 版本不兼容：{info['version']}")
    log(f"虚拟环境：{info['version']} ({info['executable']})")
    return str(venv_python), info


def has_pip(python: str) -> bool:
    return run([python, "-m", "pip", "--version"]).returncode == 0


def install_dependencies(python: str) -> None:
    requirements = ROOT / "requirements.txt"
    if not has_pip(python):
        run([python, "-m", "ensurepip", "--upgrade"])
    if not has_pip(python):
        run([
            sys.executable,
            "-m",
            "pip",
            "--python",
            python,
            "install",
            "--disable-pip-version-check",
            "pip",
        ])
    if not has_pip(python):
        raise SetupError("虚拟环境缺少 pip，ensurepip 和系统 pip 均未能修复")
    completed = run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements),
        ]
    )
    code = (
        "import json,pathlib,sys; import yaml,playwright,pytest; "
        "import importlib.metadata as m; "
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({"
        "'PyYAML':m.version('PyYAML'),"
        "'playwright':m.version('playwright'),"
        "'pytest':m.version('pytest')"
        "}),encoding='utf-8')"
    )
    probe = LOCAL / f"deps-probe-{time.time_ns()}.json"
    run([python, "-c", code, str(probe)])
    if not probe.exists():
        raise SetupError(
            f"依赖导入失败（pip 返回 {completed.returncode}）\n"
            f"{completed.stdout[-2000:]}"
        )
    try:
        versions = json.loads(probe.read_text(encoding="utf-8"))
    finally:
        probe.unlink(missing_ok=True)
    log(
        "依赖：PyYAML {PyYAML} / Playwright {playwright} / pytest {pytest}".format(
            **versions
        )
    )


def find_browser(kind: str) -> dict:
    config_path = LOCAL / "browser.json"
    if kind == "auto" and config_path.exists():
        try:
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            if saved.get("path") and Path(saved["path"]).exists():
                return {"kind": saved.get("kind", "Edge"), "path": saved["path"]}
        except (OSError, ValueError):
            pass

    groups = []
    if kind in ("auto", "edge"):
        roots = [
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("ProgramFiles"),
        ]
        groups.append((
            "Edge",
            [Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
             for root in roots if root],
        ))
    if kind in ("auto", "chrome"):
        roots = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        groups.append((
            "Chrome",
            [Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
             for root in roots if root],
        ))
    for name, paths in groups:
        for path in paths:
            if path.exists():
                return {"kind": name, "path": str(path)}
    raise SetupError(f"没有找到请求的浏览器：{kind}")


def ensure_owner(owner: str | None) -> str:
    config_path = LOCAL / "operator.json"
    if config_path.exists():
        try:
            current = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SetupError(f".local/operator.json 无法读取：{exc}") from exc
        if not current.get("owner"):
            raise SetupError(".local/operator.json 已存在但没有 owner")
        log(f"操作者配置：{current['owner']}")
        return str(current["owner"])
    if not owner:
        raise SetupError("首次部署必须通过 --owner 指定负责人标识")
    owner = owner.strip()
    if not owner or re.search(r'[\\/:*?"<>|\s]', owner):
        raise SetupError("owner 不能为空，且不能包含空格或路径保留字符")
    write_json(config_path, {"owner": owner, "ad_username": None})
    log(f"操作者配置已创建：{owner}")
    return owner


def ensure_database(python: str) -> None:
    database = ROOT / "activities" / "_db" / "投放数据.db"
    if not database.exists():
        code = (
            "import json,pathlib,sys; "
            "sys.path.insert(0,str(pathlib.Path.cwd()/'automation'/'scripts')); "
            "import workspace_repo; "
            "conn=workspace_repo.connect(sys.argv[2]); "
            "version=conn.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]; "
            "conn.close(); "
            "pathlib.Path(sys.argv[1]).write_text(json.dumps({'version':version}),encoding='utf-8')"
        )
        probe = LOCAL / f"db-probe-{time.time_ns()}.json"
        run([python, "-c", code, str(probe), str(database)])
        if not probe.exists():
            raise SetupError("数据库初始化失败")
        data = json.loads(probe.read_text(encoding="utf-8"))
        probe.unlink(missing_ok=True)
        log(f"数据库已创建：schema v{data['version']}")
    else:
        log("数据库已存在，保留原数据")

    demo = run([python, str(ROOT / "scripts" / "demo.py"), "--db", str(database)])
    if demo.returncode != 0:
        log(f"示例初始化返回 {demo.returncode}，继续用数据库结果校验")
    code = (
        "import json,pathlib,sys; "
        "sys.path.insert(0,str(pathlib.Path.cwd()/'automation'/'scripts')); "
        "import workspace_repo; "
        "conn=workspace_repo.connect(sys.argv[2]); "
        "count=conn.execute('SELECT COUNT(*) FROM activity').fetchone()[0]; "
        "conn.close(); "
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({'activityCount':count}),encoding='utf-8')"
    )
    probe = LOCAL / f"demo-probe-{time.time_ns()}.json"
    run([python, "-c", code, str(probe), str(database)])
    if not probe.exists():
        raise SetupError("示例活动校验失败")
    data = json.loads(probe.read_text(encoding="utf-8"))
    probe.unlink(missing_ok=True)
    if int(data["activityCount"]) < 1:
        raise SetupError("数据库中没有活动")
    log(f"活动数量：{data['activityCount']}")


def run_tests(python: str) -> dict:
    output = LOCAL / "test-results.json"
    verify = ROOT / "scripts" / "verify_tests.py"
    run([python, str(verify), "--python", python, "--output", str(output)])
    if not output.exists():
        raise SetupError("测试没有生成结果文件")
    result = json.loads(output.read_text(encoding="utf-8"))
    if result.get("status") != "ok":
        raise SetupError(f"自动化测试失败，详情见 {output}")
    log(
        "自动化测试通过：mode={mode} passed={passed} failed={failed} skipped={skipped}".format(
            mode=result.get("mode"),
            passed=result.get("passed", 0),
            failed=result.get("failed", 0),
            skipped=result.get("skipped", 0),
        )
    )
    return result


def start_board(python: str) -> dict:
    vbs = ROOT / "web" / "start-hidden.vbs"
    service = ROOT / "automation" / "scripts" / "board_service.py"
    try:
        os.startfile(str(vbs), arguments="/quiet")
    except (AttributeError, OSError) as exc:
        raise SetupError(f"无法通过 Windows shell 启动看板：{exc}") from exc
    log("已通过 Windows shell 启动看板")

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 30
    last_error = "看板未返回地址"
    while time.monotonic() < deadline:
        completed = run([python, str(service), "--url"])
        url = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
        if completed.returncode == 0 and url.startswith("http://127.0.0.1:"):
            try:
                with opener.open(url.rstrip("/") + "/api/health", timeout=5) as response:
                    health = json.loads(response.read().decode("utf-8"))
                if health.get("service") == "ad_management-board":
                    log(f"看板：{url}")
                    return {"url": url, "health": health}
                last_error = "健康检查返回了其他服务"
            except Exception as exc:
                last_error = str(exc)
        time.sleep(1)
    raise SetupError(f"看板启动失败：{last_error}")


def write_setup_result(status: str, message: str, data: dict | None = None) -> None:
    payload = {
        "status": status,
        "message": message,
        "repo": str(ROOT),
        "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "log": str(SETUP_LOG),
    }
    if data:
        payload.update(data)
    write_json(SETUP_RESULT, payload)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="AI 环境一键部署")
    parser.add_argument("--owner", default="")
    parser.add_argument("--browser", choices=("auto", "edge", "chrome"), default="auto")
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--start-board", action="store_true")
    args = parser.parse_args()

    LOCAL.mkdir(parents=True, exist_ok=True)
    SETUP_LOG.write_text("", encoding="utf-8")
    SETUP_RESULT.unlink(missing_ok=True)
    (LOCAL / "test-results.json").unlink(missing_ok=True)
    log("CSDN 广告投放自动化 - AI 一键部署")
    log(f"项目目录：{ROOT}")
    try:
        ensure_owner(args.owner)
        python, info = ensure_venv()
        install_dependencies(python)
        browser = find_browser(args.browser)
        write_json(LOCAL / "browser.json", browser)
        log(f"浏览器：{browser['kind']} {browser['path']}")
        for relative in (
            "activities/_db/backups",
            "automation/_tmp",
            ".browser-profile",
        ):
            (ROOT / relative).mkdir(parents=True, exist_ok=True)
        ensure_database(python)
        tests = run_tests(python) if args.run_tests else None
        board = start_board(python) if args.start_board else None
        write_setup_result("ok", "部署完成", {
            "venvPython": info,
            "browser": browser,
            "tests": tests,
            "board": board,
        })
        print("SETUP: OK")
        print(f"部署结果: {SETUP_RESULT}")
        print("下一步：运行 scripts/doctor.py --login，并在打开的浏览器中完成 CSDN 登录。")
        return 0
    except Exception as exc:
        with SETUP_LOG.open("a", encoding="utf-8") as handle:
            handle.write(traceback.format_exc() + "\n")
        write_setup_result("failed", str(exc))
        print(f"SETUP: FAILED | {exc}")
        print(f"日志: {SETUP_LOG}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
