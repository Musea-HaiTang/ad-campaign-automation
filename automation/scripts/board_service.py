# -*- coding: utf-8 -*-
"""看板服务的起 / 停 / 查；实际端口和 PID 以运行状态文件为准。"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runtime_state

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WEB = os.path.join(REPO, "web")
PREFERRED_PORT = 8770
SERVICE = "ad_management-board"
LOG = os.path.join(os.environ.get("TEMP") or REPO, "board_service.log")
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


def current():
    """返回状态与健康检查都确认属于本项目的看板进程。"""
    state = runtime_state.read_state("board")
    if not state:
        return {}
    try:
        pid = int(state["pid"])
        port = int(state["port"])
    except (KeyError, TypeError, ValueError):
        runtime_state.clear_state("board")
        return {}
    info = health(port)
    if (
        info.get("service") == SERVICE
        and int(info.get("pid") or 0) == pid
        and int(info.get("port") or 0) == port
        and runtime_state.process_matches(pid, [REPO, "app.py"])
    ):
        return state
    if not runtime_state.pid_alive(pid):
        runtime_state.clear_state("board", pid=pid)
    return {}


def start_hidden(preferred_port=PREFERRED_PORT, auto_minutes=30):
    running = current()
    if running:
        log("看板服务：已经在跑（PID %s），%s" % (running["pid"], board_url(running["port"])))
        return 0

    stale = runtime_state.read_state("board")
    if stale:
        runtime_state.clear_state("board", pid=stale.get("pid"))

    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    if os.path.isfile(pyw):
        py = pyw
    with open(LOG, "w", encoding="utf-8", errors="replace") as logf:
        flags = 0x00000008 | 0x00000200
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
            creationflags=flags,
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
    running = current()
    if not running:
        log("看板服务：没有本项目验证过的运行状态")
        return 0
    pid = int(running["pid"])
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    time.sleep(1)
    runtime_state.clear_state("board", pid=pid)
    log("看板服务：停掉进程 %d（公共浏览器不动）" % pid)
    return 0


def status():
    running = current()
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
        running = current()
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
