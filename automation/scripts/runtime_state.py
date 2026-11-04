# -*- coding: utf-8 -*-
"""本项目运行状态、端口探测和进程身份校验。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import urllib.request


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TMP = REPO / "automation" / "_tmp"
STATE_PATHS = {
    "board": TMP / "board_service.json",
    "browser": TMP / "broker.json",
}
PS_PATH = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
HIDDEN_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_hidden(args, **kwargs):
    """运行后台系统命令，Windows 下不创建可见控制台窗口。"""
    if HIDDEN_FLAGS:
        kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | HIDDEN_FLAGS
    return subprocess.run(args, **kwargs)


def state_path(name: str) -> Path:
    try:
        return STATE_PATHS[name]
    except KeyError:
        raise ValueError(f"未知运行状态：{name}") from None


def read_state(name: str) -> dict:
    path = state_path(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_state(name: str, data: dict) -> None:
    path = state_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def clear_state(name: str, pid: int | None = None) -> None:
    path = state_path(name)
    if pid is not None:
        current = read_state(name)
        if current and int(current.get("pid") or 0) != int(pid):
            return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def listener_map() -> dict[int, list[int]]:
    try:
        result = run_hidden(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=20,
        )
    except Exception:
        return {}
    found = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            try:
                port = int(parts[1].rsplit(":", 1)[1])
                pid = int(parts[4])
            except (IndexError, ValueError):
                continue
            found.setdefault(port, set()).add(pid)
    return {port: sorted(pids) for port, pids in found.items()}


def listener_pids(port: int) -> list[int]:
    return listener_map().get(int(port), [])


def listening_ports(preferred: int, span: int = 100) -> list[int]:
    start, stop = int(preferred), int(preferred) + int(span)
    return sorted(port for port in listener_map() if start <= port < stop)


def is_free(port: int) -> bool:
    return not listener_pids(port)


def next_free_port(preferred: int, span: int = 100) -> int:
    occupied = set(listening_ports(preferred, span))
    for port in range(int(preferred), int(preferred) + int(span)):
        if port not in occupied:
            return port
    raise RuntimeError(f"{preferred} 起连续 {span} 个端口都被占用")


def process_info(pid: int) -> dict:
    if int(pid) <= 0:
        return {}
    executable = str(PS_PATH) if PS_PATH.is_file() else "powershell"
    command = (
        "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(int(pid)) + "' "
        "| Select-Object ProcessId,Name,ExecutablePath,CommandLine; "
        "$p | ConvertTo-Json -Compress"
    )
    try:
        result = run_hidden(
            [executable, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        text = result.stdout.strip()
        return json.loads(text) if text else {}
    except Exception:
        return {}


def pid_alive(pid: int) -> bool:
    return bool(process_info(pid))


def process_matches(pid: int, fragments: list[str], allow_unknown: bool = False) -> bool:
    info = process_info(pid)
    command = str(info.get("CommandLine") or "").replace("/", "\\").lower()
    if not command:
        return bool(allow_unknown)
    return all(str(f).replace("/", "\\").lower() in command for f in fragments)


def acquire_file_lock(path: Path):
    """取得跨进程排他锁；成功后必须把返回句柄保持到进程退出。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def release_file_lock(handle) -> None:
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()


def get_json(url: str, timeout: float = 3.0) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
