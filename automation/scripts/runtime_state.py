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


def listener_pids(port: int) -> list[int]:
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=20,
    )
    suffix = f":{int(port)}"
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].endswith(suffix):
                try:
                    pids.add(int(parts[4]))
                except ValueError:
                    pass
    return sorted(pids)


def is_free(port: int) -> bool:
    return not listener_pids(port)


def next_free_port(preferred: int, span: int = 100) -> int:
    for port in range(int(preferred), int(preferred) + int(span)):
        if is_free(port):
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
        result = subprocess.run(
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


def process_matches(pid: int, fragments: list[str]) -> bool:
    info = process_info(pid)
    command = str(info.get("CommandLine") or "").replace("/", "\\").lower()
    return bool(command) and all(str(f).replace("/", "\\").lower() in command for f in fragments)


def get_json(url: str, timeout: float = 3.0) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
