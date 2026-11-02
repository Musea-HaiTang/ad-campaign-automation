# -*- coding: utf-8 -*-
"""供应商无关巡检：刷新今天数据 → 判定 → 输出待复盘队列和报告。"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

import runtime_state


sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_DB = REPO / "activities" / "_db" / "投放数据.db"
REPORT_DIR = REPO / "automation" / "_tmp" / "patrol"
SESSION_ENV_KEYS = ("CODEBUDDY_SESSION_ID", "CLAUDE_SESSION_ID")


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def board_base_url() -> str:
    state = runtime_state.read_state("board")
    port = int(state.get("port") or 8770)
    return f"http://127.0.0.1:{port}"


def request_json(url: str, method: str = "GET") -> tuple[int, dict]:
    data = b"" if method == "POST" else None
    request = urllib.request.Request(url, method=method, data=data)
    try:
        with _opener().open(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": raw}
        return exc.code, body


def wait_fetch(base_url: str, timeout: float, interval: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        code, body = request_json(base_url + "/api/fetch/status?all=1")
        if code != 200:
            raise RuntimeError(f"读取取数状态失败：HTTP {code} {body}")
        batch = body.get("batch") or {}
        if not batch.get("running") and not body.get("anyRunning"):
            return batch
        if time.monotonic() >= deadline:
            raise TimeoutError(f"等待取数超时（{timeout:g} 秒）")
        time.sleep(interval)


def refresh_today(base_url: str, timeout: float, interval: float) -> dict:
    code, body = request_json(base_url + "/api/fetch?today=1&all=1", method="POST")
    if code == 202:
        return wait_fetch(base_url, timeout, interval)
    if code == 409:
        message = str(body.get("error") or "")
        if "正在取数" in message or "队列里还排着" in message:
            return wait_fetch(base_url, timeout, interval)
        if "都已收尾" in message or "都取过数" in message or body.get("blocked"):
            return body.get("batch") or {"mode": None, "items": [], "errorCount": 0}
    raise RuntimeError(f"启动今日刷新失败：HTTP {code} {body}")


def run_script(args: list[str]) -> str:
    result = subprocess.run(
        [sys.executable, *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(output or f"命令失败：{' '.join(args)}")
    return output


def collect_reviews(db_path: Path) -> list[dict]:
    output = run_script([
        str(HERE / "review_queue.py"),
        "--db", str(db_path),
        "list",
    ])
    return json.loads(output)


def current_session_id(environ=None) -> str:
    environ = environ or os.environ
    for key in SESSION_ENV_KEYS:
        value = str(environ.get(key) or "").strip()
        if value:
            return value
    return ""


def reviews_to_assign(reviews: list[dict]) -> list[dict]:
    return [row for row in reviews if not str(row.get("thread_id") or "").strip()]


def assign_reviews(db_path: Path, reviews: list[dict], session_id: str) -> list[int]:
    if not session_id:
        return []
    assigned = []
    for review in reviews_to_assign(reviews):
        review_id = int(review["id"])
        run_script([
            str(HERE / "review_queue.py"),
            "--db", str(db_path),
            "assign", str(review_id), session_id,
        ])
        review["thread_id"] = session_id
        assigned.append(review_id)
    return assigned


def report_text(batch: dict, judge_output: str, reviews: list[dict],
                session_id: str = "", assigned: list[int] | None = None) -> str:
    errors = int(batch.get("errorCount") or 0)
    assigned = assigned or []
    lines = [
        "# 巡检报告",
        "",
        "时间：" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
        "## 取数",
        f"模式：{batch.get('mode') or '跳过'}；完成：{batch.get('done', 0)}；失败：{errors}",
        "",
        "## 判定",
        judge_output or "无输出",
        "",
        "## 待复盘",
        f"共 {len(reviews)} 项",
        f"当前会话：{session_id or '未提供'}",
        f"自动回写：{len(assigned)} 项",
    ]
    for row in reviews:
        lines.append(
            f"- {row['display_name']} / {row['bucket_key']} / "
            f"{row['task_name']} / 曝光 {row['total_exposure']} / 点击 {row['total_click']}"
        )
    return "\n".join(lines).rstrip() + "\n"


def write_report(text: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".md")
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="运行一次供应商无关巡检")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="数据库路径")
    parser.add_argument("--base-url", default="", help="看板服务地址；缺省读取运行状态")
    parser.add_argument("--timeout", type=float, default=600, help="等待今日取数的秒数")
    parser.add_argument("--interval", type=float, default=2, help="轮询间隔秒数")
    args = parser.parse_args()

    try:
        base_url = (args.base_url or board_base_url()).rstrip("/")
        batch = refresh_today(base_url, args.timeout, args.interval)
    except Exception as exc:
        print("PATROL: FAILED")
        print(f"取数失败：{exc}", file=sys.stderr)
        return 1

    if int(batch.get("errorCount") or 0):
        print("PATROL: FAILED")
        print(f"取数有 {batch['errorCount']} 项失败，本次不执行判定。", file=sys.stderr)
        return 1

    try:
        judge_output = run_script([
            str(HERE / "judge_batch.py"),
            "--v2-db", str(args.db),
            "--mark",
            "--brief",
        ])
        reviews = collect_reviews(Path(args.db))
        session_id = current_session_id()
        assigned = assign_reviews(Path(args.db), reviews, session_id)
    except Exception as exc:
        print("PATROL: FAILED")
        print(f"判定失败：{exc}", file=sys.stderr)
        return 1

    text = report_text(batch, judge_output, reviews, session_id, assigned)
    path = write_report(text)
    print(text)
    print(f"报告：{path}")
    print(f"PATROL: {'DUE' if reviews else 'OK'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
