# -*- coding: utf-8 -*-
"""本项目运行状态、端口探测和进程身份校验。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
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
IS_WINDOWS = os.name == "nt"


def run_hidden(args, **kwargs):
    """运行后台系统命令，Windows 下不创建可见控制台窗口。"""
    if HIDDEN_FLAGS:
        kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | HIDDEN_FLAGS
    return subprocess.run(args, **kwargs)


def detached_process_kwargs() -> dict:
    """后台服务脱离当前终端；Windows 和 macOS 使用各自机制。"""
    if IS_WINDOWS:
        return {"creationflags": 0x00000008 | 0x00000200}
    return {"start_new_session": True}


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


def _parse_netstat_listeners(text: str) -> dict[int, list[int]]:
    found: dict[int, set[int]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            try:
                port = int(parts[1].rsplit(":", 1)[1])
                pid = int(parts[4])
            except (IndexError, ValueError):
                continue
            found.setdefault(port, set()).add(pid)
    return {port: sorted(pids) for port, pids in found.items()}


def _parse_lsof_listeners(text: str) -> dict[int, list[int]]:
    """解析 macOS `lsof -Fpcn` 输出。"""
    found: dict[int, set[int]] = {}
    pid = 0
    for line in text.splitlines():
        if line.startswith("p"):
            try:
                pid = int(line[1:])
            except ValueError:
                pid = 0
        elif line.startswith("n") and pid:
            address = line[1:]
            try:
                port = int(address.rsplit(":", 1)[1])
            except (IndexError, ValueError):
                continue
            found.setdefault(port, set()).add(pid)
    return {port: sorted(pids) for port, pids in found.items()}


def listener_map() -> dict[int, list[int]]:
    try:
        if IS_WINDOWS:
            result = run_hidden(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=20,
            )
            return _parse_netstat_listeners(result.stdout)
        lsof = shutil.which("lsof") or "/usr/sbin/lsof"
        result = run_hidden(
            [lsof, "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=20,
        )
        return _parse_lsof_listeners(result.stdout)
    except Exception:
        return {}


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


def process_commands() -> dict[int, str]:
    """返回当前进程号到完整命令行的映射（非 Windows）。"""
    if IS_WINDOWS:
        return {}
    try:
        result = run_hidden(
            ["/bin/ps", "-ww", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except Exception:
        return {}
    processes = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            processes[int(parts[0])] = parts[1]
    return processes


def process_info(pid: int) -> dict:
    if int(pid) <= 0:
        return {}
    if not IS_WINDOWS:
        command = process_commands().get(int(pid), "")
        if not command:
            return {}
        executable = command.split(None, 1)[0]
        return {
            "ProcessId": int(pid),
            "Name": os.path.basename(executable),
            "ExecutablePath": executable,
            "CommandLine": command,
        }
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


def normalize_process_text(value: str) -> str:
    return os.path.normcase(str(value)).replace("\\", "/")


def process_matches(pid: int, fragments: list[str], allow_unknown: bool = False) -> bool:
    info = process_info(pid)
    command = normalize_process_text(info.get("CommandLine") or "")
    if not command:
        return bool(allow_unknown)
    return all(normalize_process_text(f) in command for f in fragments)


def terminate_process(pid: int, force: bool = True) -> bool:
    """结束本项目已经校验过身份的进程。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if IS_WINDOWS:
        result = run_hidden(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
        )
        return result.returncode == 0
    try:
        stop_signal = getattr(signal, "SIGKILL", signal.SIGTERM) if force else signal.SIGTERM
        os.kill(pid, stop_signal)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False


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
