# -*- coding: utf-8 -*-
"""数据库 v2 的公开数据接口。

只暴露活动、桶、桶批次、取数、文案、指标和复盘的业务操作；调用方不直接写 SQL。
数据库是运行期唯一数据源；YAML 只用于导入和一次性执行参数。
"""
import datetime
import os
import sqlite3
from contextlib import contextmanager

import db_backup

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V2_DB = os.path.join(REPO, "activities", "_db", "投放数据.db")
SCHEMA_VERSION = 6

CURRENT_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_bucket_current AS
SELECT bb.*
FROM bucket_batch bb
WHERE bb.status <> 'aborted'
  AND bb.id = (
    SELECT candidate.id
    FROM bucket_batch candidate
    WHERE candidate.bucket_id = bb.bucket_id
      AND candidate.status <> 'aborted'
    ORDER BY candidate.batch_no DESC
    LIMIT 1
  );
"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS schema_version (
  version    INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_key    TEXT NOT NULL UNIQUE,
  display_name    TEXT NOT NULL,
  brand           TEXT NOT NULL,
  owner           TEXT NOT NULL,
  name_prefix     TEXT NOT NULL,
  task_group_name TEXT NOT NULL UNIQUE,
  activity_link   TEXT NOT NULL,
  status          TEXT NOT NULL CHECK(status IN ('active', 'ended')),
  started_on      TEXT NOT NULL CHECK(length(started_on) = 10),
  ended_on        TEXT CHECK(ended_on IS NULL OR (
                     length(ended_on) = 10 AND ended_on >= started_on
                   ))
);

CREATE TABLE IF NOT EXISTS bucket (
  id                        INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id               INTEGER NOT NULL REFERENCES activity(id),
  bucket_key                TEXT NOT NULL,
  display_name              TEXT NOT NULL,
  topic                     TEXT NOT NULL DEFAULT '',
  target                    TEXT NOT NULL DEFAULT '',
  keywords_text             TEXT NOT NULL DEFAULT '',
  default_threshold_exposure INTEGER NOT NULL CHECK(default_threshold_exposure > 0),
  status                    TEXT NOT NULL CHECK(status IN ('active', 'paused', 'ended')),
  UNIQUE(activity_id, bucket_key)
);

CREATE TABLE IF NOT EXISTS bucket_batch (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  bucket_id     INTEGER NOT NULL REFERENCES bucket(id),
  batch_no      INTEGER NOT NULL CHECK(batch_no > 0),
  status        TEXT NOT NULL CHECK(status IN (
                  'planned', 'creating', 'running', 'closed', 'aborted'
                )),
  change_reason TEXT NOT NULL DEFAULT '',
  created_by    TEXT NOT NULL CHECK(created_by IN ('ai', 'operator', 'system')),
  started_on    TEXT NOT NULL CHECK(length(started_on) = 10),
  ended_on      TEXT CHECK(ended_on IS NULL OR (
                  length(ended_on) = 10 AND ended_on >= started_on
                )),
  task_id       TEXT UNIQUE,
  task_name     TEXT,
  task_state    TEXT,
  UNIQUE(bucket_id, batch_no)
);

CREATE TABLE IF NOT EXISTS fetch_run (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id   INTEGER NOT NULL REFERENCES activity(id),
  scope         TEXT NOT NULL CHECK(scope IN ('full', 'today')),
  triggered_by  TEXT NOT NULL CHECK(triggered_by IN ('manual', 'auto', 'system')),
  requested_from TEXT,
  requested_to   TEXT,
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  status        TEXT NOT NULL CHECK(status IN ('running', 'ok', 'failed')),
  error_text    TEXT NOT NULL DEFAULT '',
  returned_days INTEGER NOT NULL DEFAULT 0 CHECK(returned_days >= 0),
  total_exposure INTEGER NOT NULL DEFAULT 0 CHECK(total_exposure >= 0),
  total_click    INTEGER NOT NULL DEFAULT 0 CHECK(total_click >= 0)
);

CREATE TABLE IF NOT EXISTS creative (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id      INTEGER NOT NULL REFERENCES bucket_batch(id),
  resource_id   TEXT,
  resource_name TEXT NOT NULL DEFAULT '',
  copy_id       TEXT NOT NULL,
  title         TEXT NOT NULL,
  summary       TEXT NOT NULL,
  highlight     TEXT NOT NULL DEFAULT '',
  angle_key     TEXT NOT NULL DEFAULT '',
  style_key     TEXT NOT NULL DEFAULT '',
  presentation_type TEXT NOT NULL DEFAULT '',
  validation_slot   TEXT NOT NULL DEFAULT '',
  slot          TEXT NOT NULL CHECK(slot IN (
                  'control', 'experiment1', 'experiment2', 'single'
                )),
  weight_pct    INTEGER NOT NULL CHECK(weight_pct BETWEEN 0 AND 100),
  status        TEXT NOT NULL CHECK(status IN (
                  'planned', 'created', 'running', 'retained', 'dropped'
                )),
  UNIQUE(batch_id, slot)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_creative_resource
  ON creative(batch_id, resource_id) WHERE resource_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS daily_metric (
  batch_id          INTEGER NOT NULL REFERENCES bucket_batch(id),
  metric_date       TEXT NOT NULL CHECK(length(metric_date) = 10),
  exposure          INTEGER NOT NULL DEFAULT 0 CHECK(exposure >= 0),
  click             INTEGER NOT NULL DEFAULT 0 CHECK(click >= 0),
  login_exposure    INTEGER NOT NULL DEFAULT 0 CHECK(login_exposure >= 0),
  login_click       INTEGER NOT NULL DEFAULT 0 CHECK(login_click >= 0),
  last_fetch_run_id INTEGER NOT NULL REFERENCES fetch_run(id),
  PRIMARY KEY(batch_id, metric_date)
);

CREATE TABLE IF NOT EXISTS resource_reading (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id      INTEGER NOT NULL REFERENCES bucket_batch(id),
  creative_id   INTEGER NOT NULL REFERENCES creative(id),
  fetch_run_id  INTEGER NOT NULL REFERENCES fetch_run(id),
  captured_at   TEXT NOT NULL,
  exposure      INTEGER NOT NULL DEFAULT 0 CHECK(exposure >= 0),
  click         INTEGER NOT NULL DEFAULT 0 CHECK(click >= 0),
  UNIQUE(batch_id, creative_id, fetch_run_id)
);

CREATE TABLE IF NOT EXISTS selection_run (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  bucket_id     INTEGER NOT NULL REFERENCES bucket(id),
  exported_at   TEXT NOT NULL,
  keyword_count INTEGER NOT NULL CHECK(keyword_count > 0),
  article_count INTEGER NOT NULL CHECK(article_count >= 0),
  total_click   INTEGER NOT NULL CHECK(total_click >= 0),
  UNIQUE(bucket_id, exported_at)
);

CREATE TABLE IF NOT EXISTS review (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id             INTEGER NOT NULL UNIQUE REFERENCES bucket_batch(id),
  status               TEXT NOT NULL CHECK(status IN (
                         'due', 'drafting', 'waiting_approval', 'done'
                       )),
  trigger_fetch_run_id INTEGER REFERENCES fetch_run(id),
  triggered_at         TEXT NOT NULL,
  threshold_exposure   INTEGER NOT NULL CHECK(threshold_exposure > 0),
  total_exposure       INTEGER NOT NULL CHECK(total_exposure >= 0),
  total_click          INTEGER NOT NULL CHECK(total_click >= 0),
  conclusion           TEXT CHECK(conclusion IS NULL OR conclusion IN (
                         'pass', 'fail', 'need_more_test'
                       )),
  new_copy_count       INTEGER NOT NULL DEFAULT 0 CHECK(new_copy_count >= 0),
  thread_id            TEXT,
  report_text          TEXT NOT NULL DEFAULT '',
  completed_at         TEXT
);

CREATE TABLE IF NOT EXISTS review_resource (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  review_id   INTEGER NOT NULL REFERENCES review(id),
  creative_id INTEGER NOT NULL REFERENCES creative(id),
  exposure    INTEGER NOT NULL DEFAULT 0 CHECK(exposure >= 0),
  click       INTEGER NOT NULL DEFAULT 0 CHECK(click >= 0),
  action      TEXT NOT NULL CHECK(action IN (
                'keep', 'drop', 'retest', 'small_edit'
              )),
  reason      TEXT NOT NULL DEFAULT '',
  UNIQUE(review_id, creative_id)
);

CREATE INDEX IF NOT EXISTS idx_bucket_activity ON bucket(activity_id, status);
CREATE INDEX IF NOT EXISTS idx_batch_bucket ON bucket_batch(bucket_id, batch_no DESC);
CREATE INDEX IF NOT EXISTS idx_batch_task ON bucket_batch(task_id);
CREATE INDEX IF NOT EXISTS idx_fetch_activity ON fetch_run(activity_id, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_day ON daily_metric(metric_date);
CREATE INDEX IF NOT EXISTS idx_reading_batch ON resource_reading(batch_id, creative_id);
CREATE INDEX IF NOT EXISTS idx_selection_bucket ON selection_run(bucket_id, exported_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_status ON review(status, triggered_at);

{CURRENT_VIEW_SQL}

CREATE VIEW IF NOT EXISTS v_review_due AS
SELECT r.*, r.total_exposure AS exposure, r.total_click AS click,
       bb.bucket_id, b.bucket_key, b.display_name AS bucket_name,
       bb.task_name AS task, bb.task_state, bb.batch_no, bb.started_on,
       a.id AS activity_id, a.activity_key, a.display_name AS activity_name
FROM review r
JOIN bucket_batch bb ON bb.id = r.batch_id
JOIN bucket b ON b.id = bb.bucket_id
JOIN activity a ON a.id = b.activity_id
WHERE r.status = 'due';

CREATE VIEW IF NOT EXISTS v_activity_freshness AS
SELECT a.id AS activity_id, a.activity_key,
       MAX(f.finished_at) AS last_successful_fetch_at
FROM activity a
LEFT JOIN fetch_run f ON f.activity_id = a.id AND f.status = 'ok'
GROUP BY a.id, a.activity_key;
"""


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _row(row):
    return dict(row) if row is not None else None


def connect(path=None):
    """打开 v2 数据库并确保 schema 已建立。"""
    path = path or V2_DB
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    _backup_before_migration(conn, path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _backup_before_migration(conn, path):
    """旧库进入迁移前先强制生成一致性备份；备份失败则不迁移。"""
    has_tables = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
    ).fetchone()
    if not has_tables:
        return
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = int(row[0] or 0) if row else 0
    except sqlite3.OperationalError:
        current = 0
    if current >= SCHEMA_VERSION:
        return
    db_path = os.path.abspath(path)
    db_backup.backup_database(
        db_path,
        backup_dir=os.path.join(os.path.dirname(db_path), "backups"),
        keep=7,
        tag=f"pre-v{current}",
    )


@contextmanager
def transaction(conn):
    """在已有事务内不重复提交；顶层调用整段成功才提交，异常整段回滚。"""
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def _migrate(conn):
    """把旧版遗留结构升到当前版本；有数据时拒绝静默删除。"""
    _ensure_creative_columns(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = row[0] if row else None
    if current is not None and current >= SCHEMA_VERSION:
        return
    legacy = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('daily', 'task')"
        )
    }
    for name in sorted(legacy):
        count = conn.execute("SELECT COUNT(*) FROM %s" % name).fetchone()[0]
        if count:
            raise RuntimeError(
                "数据库仍有遗留表 %s（%d 行），请先迁移，不能静默删除" % (name, count)
            )
        conn.execute("DROP TABLE %s" % name)
    _repair_imported_batch_order(conn)
    conn.execute("DROP VIEW IF EXISTS v_bucket_current")
    conn.executescript(CURRENT_VIEW_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES(?, ?)",
        (SCHEMA_VERSION, _now()),
    )


def _ensure_creative_columns(conn):
    """给 v5 及更早的 creative 表补文案分类字段；旧行保留空值。"""
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(creative)").fetchall()
    }
    for name in ("presentation_type", "validation_slot"):
        if name not in columns:
            conn.execute(
                "ALTER TABLE creative ADD COLUMN %s TEXT NOT NULL DEFAULT ''" % name
            )


def _repair_imported_batch_order(conn):
    """修正旧库导入时首批被追加到批次末尾的问题。

    后台 task_id 单调递增，能可靠表示同一桶的建单先后；旧导入脚本先迁移后续批次，
    最后才补首批，导致首批拿到了最大的 batch_no。这里只重排与 task_id 顺序不一致的桶，
    并用首批最早一条按天数据修正其起投日。

    `bucket_batch.status` 是项目内批次生命周期，`task_state` 才是后台工单状态。
    后台工单下线只改后者，本迁移不修改任一个状态字段。
    """
    buckets = conn.execute("SELECT id FROM bucket ORDER BY id").fetchall()
    with conn:
        for bucket in buckets:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT bb.*, "
                    "(SELECT MIN(d.metric_date) FROM daily_metric d "
                    " WHERE d.batch_id=bb.id) AS first_metric_date "
                    "FROM bucket_batch bb WHERE bb.bucket_id=?",
                    (bucket["id"],),
                ).fetchall()
            ]
            if not rows:
                continue

            changed_start = False
            for batch in rows:
                first_metric_date = batch["first_metric_date"]
                if (batch["change_reason"] == "首批" and first_metric_date and
                        first_metric_date < batch["started_on"]):
                    conn.execute(
                        "UPDATE bucket_batch SET started_on=? WHERE id=?",
                        (first_metric_date, batch["id"]),
                    )
                    batch["started_on"] = first_metric_date
                    changed_start = True

            def order_key(batch):
                task_id = str(batch["task_id"] or "")
                if task_id.isdigit():
                    return (0, int(task_id), batch["started_on"], batch["id"])
                return (1, 0, batch["started_on"], batch["id"])

            ordered = sorted(rows, key=order_key)
            desired = {batch["id"]: no for no, batch in enumerate(ordered, 1)}
            if not changed_start and all(
                    batch["batch_no"] == desired[batch["id"]] for batch in rows):
                continue

            max_batch = max(batch["batch_no"] for batch in rows)
            max_id = max(batch["id"] for batch in rows)
            offset = max_batch + max_id + 1000
            for batch in rows:
                conn.execute(
                    "UPDATE bucket_batch SET batch_no=? WHERE id=?",
                    (offset + batch["id"], batch["id"]),
                )
            for batch in rows:
                conn.execute(
                    "UPDATE bucket_batch SET batch_no=? WHERE id=?",
                    (desired[batch["id"]], batch["id"]),
                )


def save_activity(conn, data):
    fields = (
        "activity_key", "display_name", "brand", "owner", "name_prefix",
        "task_group_name", "activity_link", "status", "started_on", "ended_on",
    )
    values = [data.get(name) for name in fields]
    with transaction(conn):
        conn.execute(
            "INSERT INTO activity(%s) VALUES(%s) "
            "ON CONFLICT(activity_key) DO UPDATE SET display_name=excluded.display_name, "
            "brand=excluded.brand, owner=excluded.owner, name_prefix=excluded.name_prefix, "
            "task_group_name=excluded.task_group_name, activity_link=excluded.activity_link, "
            "status=excluded.status, started_on=excluded.started_on, ended_on=excluded.ended_on"
            % (", ".join(fields), ",".join("?" for _ in fields)),
            values,
        )
    return get_activity(conn, data["activity_key"])


def get_activity(conn, activity_key):
    return _row(conn.execute(
        "SELECT * FROM activity WHERE activity_key=?", (activity_key,)
    ).fetchone())


def set_activity_status(conn, activity_key, status, ended_on=None):
    """切换活动生命周期；启动时清空收尾日，收尾时必须给有效日期。"""
    if status not in ("active", "ended"):
        raise ValueError("status 只能是 active 或 ended")
    row = get_activity(conn, activity_key)
    if row is None:
        raise ValueError("没有这个活动：%s" % activity_key)
    if status == "active":
        ended_on = None
    elif not ended_on:
        raise ValueError("活动收尾必须给收尾日")
    if ended_on:
        try:
            datetime.date.fromisoformat(ended_on)
        except ValueError:
            raise ValueError("收尾日要写成 YYYY-MM-DD")
        if ended_on < row["started_on"]:
            raise ValueError("收尾日不能早于活动开始日")
    with conn:
        conn.execute(
            "UPDATE activity SET status=?, ended_on=? WHERE activity_key=?",
            (status, ended_on, activity_key),
        )
    return get_activity(conn, activity_key)


def list_activities(conn):
    return [
        _row(row) for row in conn.execute(
            "SELECT * FROM activity ORDER BY activity_key"
        ).fetchall()
    ]


def save_bucket(conn, activity_id, data):
    fields = (
        "activity_id", "bucket_key", "display_name", "topic", "target",
        "keywords_text", "default_threshold_exposure", "status",
    )
    values = [activity_id] + [data.get(name) for name in fields[1:]]
    with transaction(conn):
        conn.execute(
            "INSERT INTO bucket(%s) VALUES(%s) "
            "ON CONFLICT(activity_id, bucket_key) DO UPDATE SET "
            "display_name=excluded.display_name, topic=excluded.topic, target=excluded.target, "
            "keywords_text=excluded.keywords_text, "
            "default_threshold_exposure=excluded.default_threshold_exposure, "
            "status=excluded.status" % (", ".join(fields), ",".join("?" for _ in fields)),
            values,
        )
    return _row(conn.execute(
        "SELECT * FROM bucket WHERE activity_id=? AND bucket_key=?",
        (activity_id, data["bucket_key"]),
    ).fetchone())


def list_buckets(conn, activity_id):
    return [
        _row(row) for row in conn.execute(
            "SELECT * FROM bucket WHERE activity_id=? ORDER BY bucket_key",
            (activity_id,),
        ).fetchall()
    ]


def get_bucket(conn, activity_id, bucket_key):
    return _row(conn.execute(
        "SELECT * FROM bucket WHERE activity_id=? AND bucket_key=?",
        (activity_id, bucket_key),
    ).fetchone())


def create_bucket_batch(conn, bucket_id, started_on, change_reason="",
                        created_by="system", status="planned"):
    """为指定桶创建下一条独立批次，batch_no 只在该桶内递增。"""
    with transaction(conn):
        row = conn.execute(
            "SELECT COALESCE(MAX(batch_no), 0) + 1 AS n FROM bucket_batch WHERE bucket_id=?",
            (bucket_id,),
        ).fetchone()
        batch_no = row["n"]
        cur = conn.execute(
            "INSERT INTO bucket_batch(bucket_id, batch_no, status, change_reason, "
            "created_by, started_on) VALUES(?,?,?,?,?,?)",
            (bucket_id, batch_no, status, change_reason, created_by, started_on),
        )
    return get_bucket_batch(conn, cur.lastrowid)


def get_bucket_batch(conn, batch_id):
    return _row(conn.execute("SELECT * FROM bucket_batch WHERE id=?", (batch_id,)).fetchone())


def get_current_batch(conn, bucket_id):
    return _row(conn.execute(
        "SELECT * FROM v_bucket_current WHERE bucket_id=?", (bucket_id,)
    ).fetchone())


def ensure_batch_for_task(conn, activity_id, bucket_key, task_name, started_on,
                          change_reason="", created_by="ai", status="running"):
    """按完整工单名幂等登记一个桶批次，task_id 可由后续取数补全。"""
    bucket = conn.execute(
        "SELECT * FROM bucket WHERE activity_id=? AND bucket_key=?",
        (activity_id, bucket_key),
    ).fetchone()
    if bucket is None:
        raise ValueError("活动里没有这个桶：%s" % bucket_key)
    existing = conn.execute(
        "SELECT * FROM bucket_batch WHERE bucket_id=? AND task_name=? "
        "ORDER BY batch_no DESC LIMIT 1",
        (bucket["id"], task_name),
    ).fetchone()
    if existing is not None:
        task_state = "进行中" if status in ("running", "creating") else None
        with transaction(conn):
            conn.execute(
                "UPDATE bucket_batch SET task_state=?, status=? WHERE id=?",
                (task_state, status, existing["id"]),
            )
        return get_bucket_batch(conn, existing["id"])
    row = create_bucket_batch(
        conn, bucket["id"], started_on, change_reason=change_reason,
        created_by=created_by, status=status,
    )
    with transaction(conn):
        task_state = "进行中" if status in ("running", "creating") else None
        conn.execute(
            "UPDATE bucket_batch SET task_name=?, task_state=? WHERE id=?",
            (task_name, task_state, row["id"]),
        )
    return get_bucket_batch(conn, row["id"])


def start_fetch_run(conn, activity_id, scope, triggered_by,
                    requested_from=None, requested_to=None):
    with conn:
        cur = conn.execute(
            "INSERT INTO fetch_run(activity_id, scope, triggered_by, requested_from, "
            "requested_to, started_at, status) VALUES(?,?,?,?,?,?,'running')",
            (activity_id, scope, triggered_by, requested_from, requested_to, _now()),
        )
    return _row(conn.execute("SELECT * FROM fetch_run WHERE id=?", (cur.lastrowid,)).fetchone())


def finish_fetch_run(conn, fetch_id, status, error_text="", returned_days=0,
                     total_exposure=0, total_click=0):
    if status not in ("ok", "failed"):
        raise ValueError("status 只能是 ok / failed")
    with conn:
        conn.execute(
            "UPDATE fetch_run SET finished_at=?, status=?, error_text=?, returned_days=?, "
            "total_exposure=?, total_click=? WHERE id=?",
            (_now(), status, error_text, returned_days, total_exposure, total_click, fetch_id),
        )
    return _row(conn.execute("SELECT * FROM fetch_run WHERE id=?", (fetch_id,)).fetchone())


def add_creative(conn, batch_id, resource_id, resource_name, copy_id, title, summary,
                 angle_key, style_key, slot, weight_pct, status="planned",
                 presentation_type="", validation_slot=""):
    resource_id = str(resource_id).strip() if resource_id else None
    with conn:
        cur = conn.execute(
            "INSERT INTO creative(batch_id, resource_id, resource_name, copy_id, title, "
            "summary, angle_key, style_key, presentation_type, validation_slot, "
            "slot, weight_pct, status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, resource_id, resource_name, copy_id, title, summary,
             angle_key, style_key, presentation_type, validation_slot,
             slot, weight_pct, status),
        )
    return _row(conn.execute("SELECT * FROM creative WHERE id=?", (cur.lastrowid,)).fetchone())


def save_creative(conn, batch_id, resource_id, resource_name, copy_id, title, summary,
                  angle_key, style_key, slot, weight_pct, status,
                  presentation_type="", validation_slot=""):
    """按批次槽位幂等保存文案；重复执行会更新同一行。"""
    resource_id = str(resource_id).strip() if resource_id else None
    with transaction(conn):
        conn.execute(
            "INSERT INTO creative(batch_id, resource_id, resource_name, copy_id, title, "
            "summary, angle_key, style_key, presentation_type, validation_slot, "
            "slot, weight_pct, status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(batch_id, slot) DO UPDATE SET resource_id=excluded.resource_id, "
            "resource_name=excluded.resource_name, copy_id=excluded.copy_id, "
            "title=excluded.title, summary=excluded.summary, "
            "angle_key=excluded.angle_key, style_key=excluded.style_key, "
            "presentation_type=excluded.presentation_type, "
            "validation_slot=excluded.validation_slot, "
            "weight_pct=excluded.weight_pct, status=excluded.status",
            (batch_id, resource_id, resource_name or "", copy_id, title, summary,
             angle_key, style_key, presentation_type, validation_slot,
             slot, weight_pct, status),
        )
    return _row(conn.execute(
        "SELECT * FROM creative WHERE batch_id=? AND slot=?", (batch_id, slot)
    ).fetchone())


def latest_creative_copy(conn, activity_id, resource_name):
    """按资源名找最近一条带文案内容的快照，供复用旧资源的新批次继承。"""
    return _row(conn.execute(
        "SELECT c.* FROM creative c "
        "JOIN bucket_batch bb ON bb.id=c.batch_id "
        "JOIN bucket b ON b.id=bb.bucket_id "
        "WHERE b.activity_id=? AND c.resource_name=? "
        "AND (c.title<>'' OR c.summary<>'') "
        "ORDER BY c.id DESC LIMIT 1",
        (activity_id, resource_name),
    ).fetchone())


def upsert_daily_metric(conn, batch_id, metric_date, exposure, click,
                        login_exposure, login_click, fetch_run_id):
    with conn:
        conn.execute(
            "INSERT INTO daily_metric(batch_id, metric_date, exposure, click, "
            "login_exposure, login_click, last_fetch_run_id) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(batch_id, metric_date) DO UPDATE SET exposure=excluded.exposure, "
            "click=excluded.click, login_exposure=excluded.login_exposure, "
            "login_click=excluded.login_click, last_fetch_run_id=excluded.last_fetch_run_id",
            (batch_id, metric_date, exposure, click, login_exposure, login_click, fetch_run_id),
        )


def add_resource_reading(conn, batch_id, creative_id, fetch_run_id, captured_at,
                         exposure, click):
    with conn:
        conn.execute(
            "INSERT INTO resource_reading(batch_id, creative_id, fetch_run_id, captured_at, "
            "exposure, click) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(batch_id, creative_id, fetch_run_id) DO UPDATE SET "
            "captured_at=excluded.captured_at, exposure=excluded.exposure, click=excluded.click",
            (batch_id, creative_id, fetch_run_id, captured_at, exposure, click),
        )


def save_selection_run(conn, activity_id, bucket_key, exported_at,
                       keyword_count, article_count, total_click):
    bucket = get_bucket(conn, activity_id, bucket_key)
    if bucket is None:
        raise ValueError("活动里没有这个桶：%s" % bucket_key)
    with conn:
        conn.execute(
            "INSERT INTO selection_run(bucket_id, exported_at, keyword_count, "
            "article_count, total_click) VALUES(?,?,?,?,?) "
            "ON CONFLICT(bucket_id, exported_at) DO UPDATE SET "
            "keyword_count=excluded.keyword_count, article_count=excluded.article_count, "
            "total_click=excluded.total_click",
            (bucket["id"], exported_at, int(keyword_count), int(article_count),
             int(total_click)),
        )
    return _row(conn.execute(
        "SELECT * FROM selection_run WHERE bucket_id=? AND exported_at=?",
        (bucket["id"], exported_at),
    ).fetchone())


def list_selection_runs(conn, activity_id):
    return [
        _row(row) for row in conn.execute(
            "SELECT s.*, b.bucket_key FROM selection_run s "
            "JOIN bucket b ON b.id=s.bucket_id WHERE b.activity_id=? "
            "ORDER BY s.exported_at, s.id",
            (activity_id,),
        ).fetchall()
    ]


def latest_resource_readings(conn, batch_id):
    """每个 creative 取最新一次读数。"""
    rows = conn.execute(
        "SELECT * FROM resource_reading WHERE batch_id=? ORDER BY captured_at, id",
        (batch_id,),
    ).fetchall()
    latest = {}
    for row in rows:
        latest[row["creative_id"]] = _row(row)
    return list(latest.values())


def daily_metrics(conn, batch_id):
    return [
        _row(row) for row in conn.execute(
            "SELECT * FROM daily_metric WHERE batch_id=? ORDER BY metric_date",
            (batch_id,),
        ).fetchall()
    ]


def activity_days(conn, activity_id):
    return [
        row["metric_date"] for row in conn.execute(
            "SELECT DISTINCT d.metric_date FROM daily_metric d "
            "JOIN bucket_batch bb ON bb.id=d.batch_id "
            "JOIN bucket b ON b.id=bb.bucket_id WHERE b.activity_id=? "
            "ORDER BY d.metric_date",
            (activity_id,),
        ).fetchall()
    ]


def activity_last_day(conn, activity_id):
    row = conn.execute(
        "SELECT MAX(d.metric_date) AS day FROM daily_metric d "
        "JOIN bucket_batch bb ON bb.id=d.batch_id "
        "JOIN bucket b ON b.id=bb.bucket_id WHERE b.activity_id=?",
        (activity_id,),
    ).fetchone()
    return row["day"] if row else None


def count_bucket_batches(conn, activity_id):
    return conn.execute(
        "SELECT COUNT(*) FROM bucket_batch bb "
        "JOIN bucket b ON b.id=bb.bucket_id WHERE b.activity_id=?",
        (activity_id,),
    ).fetchone()[0]


def single_resource_map(conn, activity_id):
    """工单完整名 → 该工单唯一资源名；只返回确实只有一个资源的批次。"""
    rows = conn.execute(
        "SELECT bb.task_name, MIN(c.resource_name) AS resource_name, COUNT(c.id) AS n "
        "FROM bucket_batch bb "
        "JOIN bucket b ON b.id=bb.bucket_id "
        "JOIN creative c ON c.batch_id=bb.id "
        "WHERE b.activity_id=? AND bb.task_name IS NOT NULL AND bb.task_name<>'' "
        "GROUP BY bb.id, bb.task_name HAVING COUNT(c.id)=1",
        (activity_id,),
    ).fetchall()
    return {row["task_name"]: row["resource_name"] for row in rows if row["resource_name"]}


def last_successful_fetch(conn, activity_id):
    return _row(conn.execute(
        "SELECT * FROM fetch_run WHERE activity_id=? AND status='ok' "
        "ORDER BY finished_at DESC, id DESC LIMIT 1",
        (activity_id,),
    ).fetchone())


def list_fetch_runs(conn, activity_id, limit=200):
    return [
        _row(row) for row in conn.execute(
            "SELECT * FROM fetch_run WHERE activity_id=? "
            "ORDER BY started_at DESC, id DESC LIMIT ?",
            (activity_id, int(limit)),
        ).fetchall()
    ]


def full_fetch_on(conn, activity_id, day):
    return _row(conn.execute(
        "SELECT * FROM fetch_run WHERE activity_id=? AND scope='full' AND status='ok' "
        "AND substr(started_at, 1, 10)=? ORDER BY finished_at DESC, id DESC LIMIT 1",
        (activity_id, day),
    ).fetchone())


def ensure_review(conn, batch_id, fetch_run_id, threshold_exposure,
                  total_exposure, total_click, triggered_at=None):
    """到门槛时创建复盘；重复巡检返回同一行，不覆盖首次触发证据。"""
    existing = conn.execute("SELECT * FROM review WHERE batch_id=?", (batch_id,)).fetchone()
    if existing is not None:
        return _row(existing)
    with conn:
        cur = conn.execute(
            "INSERT INTO review(batch_id, status, trigger_fetch_run_id, triggered_at, "
            "threshold_exposure, total_exposure, total_click) "
            "VALUES(?, 'due', ?, ?, ?, ?, ?)",
            (batch_id, fetch_run_id, triggered_at or _now(), threshold_exposure,
             total_exposure, total_click),
        )
    return _row(conn.execute("SELECT * FROM review WHERE id=?", (cur.lastrowid,)).fetchone())


def list_review_due(conn, activity_id=None):
    if activity_id is None:
        rows = conn.execute("SELECT * FROM v_review_due ORDER BY triggered_at").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM v_review_due WHERE activity_id=? ORDER BY triggered_at",
            (activity_id,),
        ).fetchall()
    return [_row(row) for row in rows]


def get_review(conn, batch_id):
    return _row(conn.execute(
        "SELECT * FROM review WHERE batch_id=?", (batch_id,)
    ).fetchone())


def add_review_resource(conn, review_id, creative_id, exposure, click,
                        action, reason=""):
    with conn:
        conn.execute(
            "INSERT INTO review_resource(review_id, creative_id, exposure, click, action, reason) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(review_id, creative_id) DO UPDATE SET exposure=excluded.exposure, "
            "click=excluded.click, action=excluded.action, reason=excluded.reason",
            (review_id, creative_id, exposure, click, action, reason),
        )
    return _row(conn.execute(
        "SELECT * FROM review_resource WHERE review_id=? AND creative_id=?",
        (review_id, creative_id),
    ).fetchone())


def list_review_resources(conn, review_id):
    return [
        _row(row) for row in conn.execute(
            "SELECT * FROM review_resource WHERE review_id=? ORDER BY id",
            (review_id,),
        ).fetchall()
    ]


def assign_review_thread(conn, review_id, thread_id, status="drafting"):
    with conn:
        conn.execute(
            "UPDATE review SET thread_id=?, status=? WHERE id=?",
            (thread_id, status, review_id),
        )
    return _row(conn.execute("SELECT * FROM review WHERE id=?", (review_id,)).fetchone())


def save_review(conn, review_id, status=None, conclusion=None, new_copy_count=None,
                thread_id=None, report_text=None, completed_at=None):
    """更新复盘结果；只更新显式传入的字段。"""
    fields, values = [], []
    for name, value in (
        ("status", status),
        ("conclusion", conclusion),
        ("new_copy_count", new_copy_count),
        ("thread_id", thread_id),
        ("report_text", report_text),
        ("completed_at", completed_at),
    ):
        if value is not None:
            fields.append("%s=?" % name)
            values.append(value)
    if not fields:
        return _row(conn.execute("SELECT * FROM review WHERE id=?", (review_id,)).fetchone())
    values.append(review_id)
    with conn:
        conn.execute("UPDATE review SET %s WHERE id=?" % ", ".join(fields), values)
    return _row(conn.execute("SELECT * FROM review WHERE id=?", (review_id,)).fetchone())
