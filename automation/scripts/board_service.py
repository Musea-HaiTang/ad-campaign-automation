# -*- coding: utf-8 -*-
"""看板服务的起 / 停 / 查；实际端口和 PID 以运行状态文件为准。"""
import argparse
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runtime_state

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WEB = os.path.join(REPO, "web")
PREFERRED_PORT = 8770
SERVICE = "ad_management-board"
LOG = os.path.join(tempfile.gettempdir(), "board_service.log")
V2_DB = os.path.join(REPO, "activities", "_db", "投放数据.db")


def log(*args):
    print(*args, flush=True)


def board_url(port):
    return "http://127.0.0.1:%d/" % int(port)


def health(port):
    try:
        data = runtime_state.get_json("http://127.0.0.1:%d/api/health" % int(port))
    except Exception:
        return {}
    return data if data.get("service") == SERVICE else {}


def _same_database(path):
    expected = os.path.normcase(os.path.abspath(V2_DB))
    actual = os.path.normcase(os.path.abspath(str(path or "")))
    return bool(path) and actual == expected


def _state_from_health(port):
    info = health(port)
    try:
        pid = int(info.get("pid"))
        actual_port = int(info.get("port"))
    except (TypeError, ValueError):
        return {}
    if actual_port != int(port) or not _same_database(info.get("db")):
        return {}
    return {
        "service": SERVICE,
        "pid": pid,
        "port": actual_port,
        "host": info.get("host") or "127.0.0.1",
        "db": info.get("db"),
        "started": info.get("started"),
    }


def discover_boards(preferred=PREFERRED_PORT):
    """找出本项目所有健康看板，状态文件损坏时也能复用或清理。"""
    found = []
    for port in runtime_state.listening_ports(preferred):
        state = _state_from_health(port)
        if state:
            found.append(state)
    return found


def current(discover=False):
    """返回状态与健康检查都确认属于本项目的看板进程。"""
    state = runtime_state.read_state("board")
    if state:
        try:
            pid = int(state["pid"])
            port = int(state["port"])
        except (KeyError, TypeError, ValueError):
            runtime_state.clear_state("board")
        else:
            info = health(port)
            if (
                info.get("service") == SERVICE
                and int(info.get("pid") or 0) == pid
                and int(info.get("port") or 0) == port
                and _same_database(info.get("db"))
                and runtime_state.process_matches(
                    pid, [REPO, "app.py"], allow_unknown=True
                )
            ):
                return state
            runtime_state.clear_state("board", pid=pid)
    if discover:
        boards = discover_boards()
        if boards:
            state = boards[0]
            runtime_state.write_state("board", state)
            return state
    return {}


def start_hidden(preferred_port=PREFERRED_PORT, auto_minutes=30):
    boards = discover_boards(preferred_port)
    if boards:
        running = boards[0]
        runtime_state.write_state("board", running)
        for duplicate in boards[1:]:
            runtime_state.terminate_process(duplicate["pid"], force=True)
            log("看板服务：结束重复实例 PID %s，%s" % (
                duplicate["pid"], board_url(duplicate["port"])
            ))
        log("看板服务：已经在跑（PID %s），%s" % (
            running["pid"], board_url(running["port"])
        ))
        return 0

    running = current()
    if running:
        log("看板服务：已经在跑（PID %s），%s" % (
            running["pid"], board_url(running["port"])
        ))
        return 0

    stale = runtime_state.read_state("board")
    if stale:
        runtime_state.clear_state("board", pid=stale.get("pid"))

    py = sys.executable
    if runtime_state.IS_WINDOWS:
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        if os.path.isfile(pyw):
            py = pyw
    with open(LOG, "w", encoding="utf-8", errors="replace") as logf:
        command = [
            py, "-u", "app.py", "--db", V2_DB,
            "--port", str(int(preferred_port)), "--auto", str(int(auto_minutes)),
        ]
        subprocess.Popen(
            command,
            cwd=WEB,
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
            **runtime_state.detached_process_kwargs(),
        )

    deadline = time.time() + 25
    while time.time() < deadline:
        running = current()
        if running:
            log("看板服务：已在后台起来（PID %s），%s" % (
                running["pid"], board_url(running["port"])
            ))
            log("  它的输出（你一般不用看）：%s" % LOG)
            return 0
        time.sleep(0.4)
    log("看板服务：25 秒都没起来，查看日志：%s" % LOG)
    return 1


def stop():
    boards = discover_boards()
    if not boards:
        running = current()
        boards = [running] if running else []
    if not boards:
        log("看板服务：没有本项目验证过的运行状态")
        return 0
    for running in boards:
        pid = int(running["pid"])
        runtime_state.terminate_process(pid, force=True)
        log("看板服务：停掉进程 %d，%s（公共浏览器不动）" % (
            pid, board_url(running["port"])
        ))
    time.sleep(1)
    runtime_state.clear_state("board")
    return 0


def status():
    running = current(discover=True)
    if running:
        log("看板服务：在跑（PID %s），%s" % (running["pid"], board_url(running["port"])))
        return 0
    log("看板服务：没在跑，或运行状态无法验证为本项目")
    return 0


def main():
    parser = argparse.ArgumentParser(description="看板服务的起 / 停 / 查")
    parser.add_argument("--start", action="store_true", help="无窗口启动")
    parser.add_argument("--stop", action="store_true", help="停止状态文件中验证过的本项目进程")
    parser.add_argument("--status", action="store_true", help="查看实际地址")
    parser.add_argument("--url", action="store_true", help="只输出当前看板 URL")
    parser.add_argument("--port", type=int, default=PREFERRED_PORT, help="首选端口，占用时自动向后寻找")
    parser.add_argument("--auto", type=int, default=30, help="看板自动刷新分钟数，0 = 关闭")
    args = parser.parse_args()
    if args.url:
        running = current(discover=True)
        if running:
            print(board_url(running["port"]))
            return 0
        return 1
    if args.stop:
        return stop()
    if args.status:
        return status()
    return start_hidden(args.port, args.auto)


if __name__ == "__main__":
    sys.exit(main())
