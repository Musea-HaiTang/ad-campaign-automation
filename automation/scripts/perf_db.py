# -*- coding: utf-8 -*-
"""投放数据台账（SQLite）——取数落地的唯一真相，看板只从这里读。

为什么不继续用"快照文件夹"当真相（2026-09-20 用户拍板）：
  1. **跨活动迟早要做** → 库带「活动」维度（键 = 任务组名），一条 SQL 就能跨活动；
  2. **每天不必重拉全区间** → 库里已有 9/14~9/19，今天只补「最近有数据那天 ~ 今天」；
  3. 「今天」的数据**不是终值**（随时刷新、反复变大），必须能"同键覆盖"——快照文件夹
     只能靠"最新一份"顶替，于是出了「窄区间快照顶掉真相、网站只剩 3 天」的事故（真踩过）。

四张表：
  activity          活动（主键 = 任务组名）：跨活动的锚
  task              工单维度：活动 / 工单名 / 状态 / 状态读数时刻
  daily             按天事实，主键 (task_id, day)：历史是终值只写一次，今天反复覆盖
  resource_reading  资源读数，主键 (task_id, resource_id, fetched_at)：每次取数追加一条
                    （资源级接口给的是**累计值**，天然是读数序列；两条读数相减 = 区间增量）

⚠ 库文件**不进 git**（二进制没法 diff）：`activities/_db/投放数据.db`。
   `数据/{时刻}/` 的 CSV 快照保留，作为可 diff 的"取数流水"原始存档。

纯数据层：不 import 别的东西、不读 YAML、不连后台，能脱浏览器单测
（见 `automation/tests/test_perf_db.py`）。
"""
import os
import sqlite3

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB = os.path.join(REPO, "activities", "_db", "投放数据.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
  activity_id TEXT PRIMARY KEY,
  dir_name    TEXT,
  label       TEXT
);
CREATE TABLE IF NOT EXISTS task (
  task_id     TEXT PRIMARY KEY,
  activity_id TEXT NOT NULL,
  task_name   TEXT NOT NULL,
  state       TEXT,
  state_at    TEXT
);
CREATE TABLE IF NOT EXISTS daily (
  task_id        TEXT NOT NULL,
  day            TEXT NOT NULL,
  exposure       INTEGER NOT NULL DEFAULT 0,
  click          INTEGER NOT NULL DEFAULT 0,
  login_exposure INTEGER NOT NULL DEFAULT 0,
  login_click    INTEGER NOT NULL DEFAULT 0,
  fetched_at     TEXT,
  PRIMARY KEY (task_id, day)
);
CREATE INDEX IF NOT EXISTS idx_daily_day ON daily(day);
CREATE TABLE IF NOT EXISTS resource_reading (
  task_id       TEXT NOT NULL,
  resource_id   TEXT NOT NULL,
  fetched_at    TEXT NOT NULL,
  activity_id   TEXT NOT NULL,
  task_name     TEXT NOT NULL,
  group_label   TEXT,
  resource_name TEXT,
  exposure      INTEGER NOT NULL DEFAULT 0,
  click         INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (task_id, resource_id, fetched_at)
);
CREATE INDEX IF NOT EXISTS idx_reading_activity ON resource_reading(activity_id, task_id);
"""


def connect(path=None):
    """开库（父目录自动建）。同一个路径拿到同一个文件，纯标准库、零依赖。"""
    path = path or DEFAULT_DB
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)   # 取数子进程在写、页面在读时，别一撞就报 locked
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_activity(conn, activity_id, dir_name="", label=""):
    """活动维度：键 = 任务组名（后台就是按任务组查的）。"""
    conn.execute(
        "INSERT INTO activity(activity_id, dir_name, label) VALUES(?,?,?) "
        "ON CONFLICT(activity_id) DO UPDATE SET dir_name=excluded.dir_name, label=excluded.label",
        (activity_id, dir_name, label))


def upsert_tasks(conn, activity_id, tasks, state_at):
    """工单维度 + 状态读数。tasks = [{"id","name","state"}]；状态取的是**本次取数那一刻**的值。"""
    conn.executemany(
        "INSERT INTO task(task_id, activity_id, task_name, state, state_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(task_id) DO UPDATE SET task_name=excluded.task_name, state=excluded.state, "
        "state_at=excluded.state_at, activity_id=excluded.activity_id",
        [(str(t["id"]), activity_id, t["name"], t.get("state") or "", state_at) for t in tasks])


def upsert_daily(conn, rows):
    """按天事实 upsert。rows = [(task_id, day, e, c, le, lc, fetched_at)]。

    幂等：历史天是终值，重拉只是覆盖成同样的数；今天是半截，每次刷都被覆盖成更新的数。
    """
    conn.executemany(
        "INSERT INTO daily(task_id, day, exposure, click, login_exposure, login_click, fetched_at) "
        "VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(task_id, day) DO UPDATE SET exposure=excluded.exposure, click=excluded.click, "
        "login_exposure=excluded.login_exposure, login_click=excluded.login_click, "
        "fetched_at=excluded.fetched_at", rows)


def add_resource_readings(conn, rows):
    """资源读数追加。rows = [(task_id, resource_id, fetched_at, activity_id, task_name,
    group_label, resource_name, e, c)]；同一 (任务,资源,时刻) 重复写不会翻倍。"""
    conn.executemany(
        "INSERT INTO resource_reading(task_id, resource_id, fetched_at, activity_id, task_name, "
        "group_label, resource_name, exposure, click) VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(task_id, resource_id, fetched_at) DO UPDATE SET "
        "group_label=excluded.group_label, resource_name=excluded.resource_name, "
        "exposure=excluded.exposure, click=excluded.click", rows)


def days(conn, activity_id):
    """库里这个活动已有的全部日期（升序）。"""
    cur = conn.execute(
        "SELECT DISTINCT d.day FROM daily d JOIN task t ON t.task_id = d.task_id "
        "WHERE t.activity_id = ? ORDER BY d.day", (activity_id,))
    return [r["day"] for r in cur.fetchall()]


def last_day(conn, activity_id):
    """最近有数据的那天；空库返回 None（取数用它决定增量起点）。"""
    ds = days(conn, activity_id)
    return ds[-1] if ds else None


def order_cells(conn, activity_id):
    """按天事实 → {工单id: {日期: [曝光, 点击, 登录曝光, 登录点击]}}。"""
    out = {}
    cur = conn.execute(
        "SELECT d.task_id, d.day, d.exposure, d.click, d.login_exposure, d.login_click "
        "FROM daily d JOIN task t ON t.task_id = d.task_id WHERE t.activity_id = ? "
        "ORDER BY d.day", (activity_id,))
    for r in cur.fetchall():
        out.setdefault(r["task_id"], {})[r["day"]] = [
            r["exposure"], r["click"], r["login_exposure"], r["login_click"]]
    return out


def tasks(conn, activity_id):
    """工单维度表（含状态读数）。"""
    cur = conn.execute(
        "SELECT task_id, task_name, state, state_at FROM task WHERE activity_id = ? "
        "ORDER BY task_name", (activity_id,))
    return [dict(r) for r in cur.fetchall()]


def latest_resource_readings(conn, activity_id):
    """每个 (工单, 资源) 取**最新一次**读数 —— 资源级是累计值，最新读数 = 整段累计。

    （读数是一串时间序列：以后要算"某段时间各涨了多少"，拿两条读数相减即可。）
    """
    cur = conn.execute(
        "SELECT task_id, task_name, resource_id, group_label, resource_name, exposure, click, fetched_at "
        "FROM resource_reading WHERE activity_id = ? ORDER BY fetched_at", (activity_id,))
    latest = {}
    for r in cur.fetchall():
        latest[(r["task_id"], r["resource_id"])] = dict(r)   # 时间升序 → 最后一条即最新
    return list(latest.values())
