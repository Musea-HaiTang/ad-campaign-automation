# -*- coding: utf-8 -*-
"""只读检查运行环境；首次登录时保存动态广告用户名。"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any


sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "automation" / "scripts"))

import runtime_state  # noqa: E402
from python_support import SUPPORTED_PYTHON_LABEL, supported_python  # noqa: E402

DB_PATH = REPO / "activities" / "_db" / "投放数据.db"
OPERATOR_PATH = REPO / ".local" / "operator.json"
PREFERRED_DASHBOARD_PORT = 8770
PREFERRED_CDP_PORT = 9222


def report(ok: bool, label: str, detail: str = "", fix: str = "",
           failures: list[str] | None = None) -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}" + (f": {detail}" if detail else ""))
    if not ok and fix:
        print(f"       修复：{fix}")
    if not ok and failures is not None:
        failures.append(label)
    return ok


def parse_listener_pids(netstat_text: str, port: int) -> list[int]:
    pids: set[int] = set()
    suffix = f":{port}"
    for line in netstat_text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].endswith(suffix):
                try:
                    pids.add(int(parts[4]))
                except ValueError:
                    pass
    return sorted(pids)


def listener_pids(port: int) -> list[int]:
    return runtime_state.listener_pids(port)


def process_info(pid: int) -> dict[str, str]:
    return {
        str(key): str(value or "")
        for key, value in runtime_state.process_info(pid).items()
    }


def is_project_port_owner(port: int, info: dict[str, str]) -> bool:
    command = runtime_state.normalize_process_text(info.get("CommandLine", ""))
    repo = runtime_state.normalize_process_text(str(REPO))
    if "app.py" in command:
        return repo in command
    if "remote-debugging-port" in command:
        return repo in command and ".browser-profile" in command
    return False


def check_port(
    port: int,
    label: str,
    failures: list[str],
    allow_fallback: bool = False,
) -> bool:
    try:
        pids = listener_pids(port)
    except Exception as exc:
        report(False, f"{label} {port}", str(exc), "重新运行诊断；若仍失败，检查系统端口查询工具是否可用。", failures)
        return False
    if not pids:
        report(True, f"{label} {port}", "端口空闲")
        return True

    details = []
    all_project = True
    for pid in pids:
        info = process_info(pid)
        name = info.get("Name") or "未知进程"
        own = is_project_port_owner(port, info)
        all_project = all_project and own
        details.append(f"PID {pid} {name} ({'本项目' if own else '非本项目'})")
    if not all_project and allow_fallback:
        fallback = runtime_state.next_free_port(port)
        report(
            True,
            f"{label} {port}",
            "；".join(details) + f"；启动时自动改用 {fallback}",
        )
        return True
    report(
        all_project,
        f"{label} {port}",
        "；".join(details),
        "端口被其他程序占用，不要直接结束该进程；先关闭冲突程序后重试。",
        failures,
    )
    return all_project


def check_python(failures: list[str]) -> None:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = supported_python(sys.version_info.major, sys.version_info.minor)
    report(
        ok,
        "Python",
        f"{version} ({sys.executable})",
        f"使用 {SUPPORTED_PYTHON_LABEL}，并重新运行 AI 一键部署。",
        failures,
    )


def check_venv(failures: list[str]) -> None:
    expected = (REPO / ".venv").resolve()
    current = Path(sys.executable).resolve()
    ok = expected == current.parent.parent
    hint = (
        ".venv\\Scripts\\python.exe scripts\\doctor.py"
        if sys.platform == "win32" else ".venv/bin/python scripts/doctor.py"
    )
    report(
        ok,
        "虚拟环境",
        str(current),
        f"使用 {hint} 运行诊断。",
        failures,
    )


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


def check_dependencies(failures: list[str]) -> bool:
    checks = [
        ("PyYAML", "yaml", "PyYAML"),
        ("Playwright", "playwright", "playwright"),
        ("pytest", "pytest", "pytest"),
    ]
    all_ok = True
    for label, module, distribution in checks:
        available = importlib.util.find_spec(module) is not None
        version = package_version(distribution)
        all_ok = report(
            available,
            label,
            version or "未安装",
            "运行 scripts/setup_ai.py 安装 requirements.txt。",
            failures,
        ) and all_ok
    return all_ok


def check_browser(failures: list[str]) -> tuple[str, Path] | None:
    try:
        sys.path.insert(0, str(REPO / "automation" / "scripts"))
        import browser_broker

        path = Path(browser_broker.browser_exe())
        name = browser_broker.browser_kind(path)
    except Exception as exc:
        report(
            False,
            "浏览器",
            str(exc),
            "安装 Microsoft Edge 或 Google Chrome，或重新运行一键部署。",
            failures,
        )
        return None
    report(True, "浏览器", f"{name}: {path}")
    return name, path


def check_dashboard_port(failures: list[str]) -> bool:
    state = runtime_state.read_state("board")
    port = int(state.get("port") or PREFERRED_DASHBOARD_PORT)
    if state:
        try:
            health = runtime_state.get_json(f"http://127.0.0.1:{port}/api/health")
        except Exception:
            health = {}
        healthy = (
            health.get("service") == "ad_management-board"
            and int(health.get("pid") or 0) == int(state.get("pid") or 0)
            and int(health.get("port") or 0) == port
        )
        report(
            healthy,
            "看板健康接口",
            f"127.0.0.1:{port}",
            "重新启动看板；不要按端口结束未知进程。",
            failures,
        )
        if not healthy:
            return False
    return check_port(port, "看板端口", failures, allow_fallback=True)


def check_browser_port(failures: list[str]) -> bool:
    state = runtime_state.read_state("browser")
    port = int(state.get("port") or PREFERRED_CDP_PORT)
    return check_port(port, "浏览器调试端口", failures, allow_fallback=True)


def read_operator() -> dict[str, Any]:
    if not OPERATOR_PATH.is_file():
        raise RuntimeError("缺少 .local/operator.json，请先运行 scripts/setup_ai.py --owner <owner>")
    data = json.loads(OPERATOR_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not str(data.get("owner") or "").strip():
        raise RuntimeError(".local/operator.json 缺少 owner")
    return data


def write_ad_username(username: str) -> None:
    data = read_operator()
    data["ad_username"] = username
    temp = OPERATOR_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, OPERATOR_PATH)


def check_operator(failures: list[str]) -> bool:
    try:
        data = read_operator()
        report(True, "操作者配置", f"owner={data['owner']}")
        return True
    except Exception as exc:
        report(False, "操作者配置", str(exc), "先运行一键部署并设置 owner。", failures)
        return False


def check_database(failures: list[str]) -> None:
    if not DB_PATH.is_file():
        report(False, "数据库", f"不存在: {DB_PATH}", "运行 scripts/setup_ai.py 初始化数据库。", failures)
        return
    try:
        uri = "file:" + DB_PATH.as_posix() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("PRAGMA query_only=ON")
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.close()

        sys.path.insert(0, str(REPO / "automation" / "scripts"))
        import workspace_repo

        ok = version == workspace_repo.SCHEMA_VERSION and integrity == "ok" and not foreign_keys
        detail = f"schema v{version}，integrity={integrity}，foreign_key_issues={len(foreign_keys)}"
        report(
            ok,
            "数据库",
            detail,
            "备份数据库后运行迁移或恢复；不要删除现有数据库重建。",
            failures,
        )
    except Exception as exc:
        report(False, "数据库", str(exc), "检查数据库文件、schema_version 和外键。", failures)


def wait_for_probe(page: Any, probe: Any, label: str, login: bool, minutes: float) -> tuple[bool, str]:
    deadline = time.monotonic() + (minutes * 60 if login else 0)
    while True:
        try:
            ok, detail = probe(page)
        except Exception as exc:
            ok, detail = False, str(exc).splitlines()[0][:160]
        print(f"  {label}: {'OK' if ok else 'WAIT'} | {detail}")
        if ok:
            return True, detail
        if not login or time.monotonic() >= deadline:
            return False, detail
        time.sleep(5)


def check_logins(login: bool, minutes: float, failures: list[str], operator_ok: bool) -> None:
    if not operator_ok:
        report(False, "CSDN 登录", "操作者配置无效，未启动登录", "先修复 owner 配置。", failures)
        return

    try:
        sys.path.insert(0, str(REPO / "automation" / "scripts"))
        import browser_broker
        import wait_login
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        report(False, "CSDN 登录", str(exc), "先安装依赖并重新运行一键部署。", failures)
        return

    login_hint = (
        ".venv\\Scripts\\python.exe scripts\\doctor.py --login"
        if sys.platform == "win32" else ".venv/bin/python scripts/doctor.py --login"
    )
    try:
        browser_broker.ensure("headed" if login else "headless")
        with sync_playwright() as playwright:
            context = browser_broker.connect(playwright)
            admin_page = context.new_page()
            data_page = context.new_page()
            try:
                admin_page.goto(
                    wait_login.DEFAULT_URL,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                admin_page.wait_for_timeout(1000)
                if login:
                    print("请在弹出的浏览器中登录 CSDN 广告后台。")
                admin_ok, admin_detail = wait_for_probe(
                    admin_page,
                    wait_login.probe_admin,
                    "广告后台",
                    login,
                    minutes,
                )
                if admin_ok:
                    username = wait_login.ui.login_identity(admin_page)["userName"]
                    write_ad_username(username)
                    report(True, "广告后台登录", f"用户 {username}")
                else:
                    report(
                        False,
                        "广告后台登录",
                        admin_detail,
                        f"运行 {login_hint}",
                        failures,
                    )

                data_page.goto(
                    wait_login.DATABI_URL,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                data_page.wait_for_timeout(1000)
                if login:
                    print("请在浏览器中登录 CSDN 数据平台 data.csdn.net。")
                data_ok, data_detail = wait_for_probe(
                    data_page,
                    lambda page: wait_login.probe_databi(page, navigate=False),
                    "数据平台",
                    login,
                    minutes,
                )
                report(
                    data_ok,
                    "数据平台登录",
                    data_detail,
                    f"运行 {login_hint}",
                    failures,
                )
            finally:
                try:
                    admin_page.close()
                    data_page.close()
                except Exception:
                    pass
    except Exception as exc:
        report(False, "CSDN 登录", str(exc).splitlines()[0][:200], "检查浏览器启动和登录 profile。", failures)


def main() -> int:
    parser = argparse.ArgumentParser(description="检查项目运行环境")
    parser.add_argument("--login", action="store_true", help="打开浏览器，等待两个 CSDN 站点分别登录")
    parser.add_argument("--minutes", type=float, default=15.0, help="每个站点最多等待多少分钟")
    args = parser.parse_args()

    failures: list[str] = []
    print("CSDN 广告投放自动化 - 环境诊断")
    print(f"项目目录：{REPO}")
    print()

    check_python(failures)
    check_venv(failures)
    deps_ok = check_dependencies(failures)
    browser_ok = check_browser(failures) is not None
    check_dashboard_port(failures)
    cdp_port_usable = check_browser_port(failures)
    check_database(failures)
    operator_ok = check_operator(failures)

    if deps_ok and browser_ok and cdp_port_usable:
        check_logins(args.login, args.minutes, failures, operator_ok)
    else:
        report(
            False,
            "CSDN 登录",
            "依赖、浏览器或浏览器调试端口未就绪",
            "先完成一键部署；端口冲突时不要结束未知进程。",
            failures,
        )

    print()
    if failures:
        print(f"DOCTOR: FAILED ({len(failures)} 项)")
        return 1
    print("DOCTOR: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
