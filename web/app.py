# -*- coding: utf-8 -*-
"""投放看板服务（本地）：浏览器打开就是看板，页面自己来拿数据；取数挂在一只**公共浏览器**上。

用户 2026-09-17 定：可视化走「**前后端分离**」——
    ① 取数 `automation/scripts/fetch_perf.py`（要登录态、连后台；**增量**）→ 写台账库
    ② 本服务（`web/app.py`）读**数据库 v2**（`activities/_db/投放数据.db`）→ 聚合成 JSON → 交给页面
    ③ 页面（`web/static/`）`fetch` → 渲染；筛选 / 切换都在浏览器里算

用户 2026-09-24 定：**浏览器常驻**——双击 `web/start-hidden.vbs` 起服务时就开起来，之后每次「刷新 / 取数」
都复用它（省掉每次 ≈1.7 秒的起/关浏览器开销）。取数逻辑仍在 `automation/scripts/fetch_perf.py`
（`fetch_mod.run`），本服务只是把那只浏览器喂给它——依赖方向还是 web → automation，没变。

用户 2026-10-16 定：那只浏览器改成**独立于本服务的公共浏览器**（`automation/scripts/
browser_broker.py`，首选 CDP 9222，冲突时使用实际端口）：以前"一个登录 profile 只能被一个进程用"，开建任务的浏览器就把看板
的取数全挤没了，只能手工"停看板 → 跑脚本 → 起看板"；现在谁都不用抢——看板、建任务脚本、
`wait_login.py` 同时挂上去、各开各的标签页。**关掉本服务窗口不再关浏览器**（它还归别的程序用），
要关就 `python automation/scripts/browser_broker.py --stop`。

用户 2026-09-28 定：**一个服务管多个活动**——
启动时用 `campaign.discover()` 扫 `activities/*/配置/*.yaml` 建一张**活动登记表**；
下面每个接口都可以带 `?activity=<任务组名>`，不给就用默认活动（有数据的那个）。
**浏览器仍然只有一只**（公共资源，大家挂它），所以取数是**串行**的；
但「今天已取」的配额、取数记录、状态都是**按活动各算一份**。

接口（全部只读，不写文件、不连后台）：
    GET /                      看板页面
    GET /app.css, /app.js      页面资源
    GET /api/health            服务身份、PID、实际端口和数据库路径
    GET /api/activities        活动登记表（id / 标签 / 目录 / 库内数据到哪天）
    GET /api/perf              台账聚合好的 JSON（区间 = 库里有的全部日期）
    GET /api/todo              **所有活动**里「到门槛 · 没复盘 · 还在投」的工单
                               （页面右上角那个角标 + 弹窗；跨活动，所以只能服务端算）
    GET /api/snapshots         数据库 `fetch_run` 取数记录——不是数据源，只是取数凭据
    GET /api/fetch/status      取数状态（正在跑没 / 上次取数时刻 / 今天取过数没）
    GET /api/fetch/status?all=1  **一次刷全部活动**那一批的进度（哪个在跑 / 哪个跑完 / 跳过谁）
    POST /api/fetch            **取数**：把昨天的数固定下来（默认区间＝到昨天，写 `fetch_run`）
                               —— **一天只允许一次**（用户 2026-09-20 定：昨天不会再变，重复取没意义）
    POST /api/fetch?today=1    **刷新今天**：只查今天这一天（常驻浏览器后实测
                               首次 ≈1.8 秒、之后 0.9~1.1 秒），随时可以点
                               —— 两个模式共用「同时只跑一个」的闸，互不占用对方的配额；
                               刷新只写数据库，不生成文件

    用户 2026-10-09 定：**页面上的「刷新」「取数」= 一次把所有登记的活动都跑一遍**
    （`?all=1`，顺序 = 当前看的活动先跑）。理由：浏览器只有一只、取数本来就串行，
    分开点并不会更快；而「待复盘」角标是跨活动的，只刷一个活动它必然半新半旧。
    单活动的 `?activity=xxx` 仍然保留（自动刷新、脚本、命令行都还在用）。

    （以上除 `/` 与页面资源外，都可以带 `?activity=<任务组名>`；不给 = 默认活动。
      「同时只跑一个」是**全局**的——浏览器只有一只；「今天已取」是**按活动**算的。）

⚠ 服务开着时照样可以在命令行跑 `fetch_perf.py`、`run_*.py`、`wait_login.py`——
   它们挂的是同一只公共浏览器（`--headed` 会把公共浏览器切成有窗口，会重启一次）。

用法：
    .venv\\Scripts\\python.exe -u web/app.py
    ... --port 8770      # 首选 8770（只本机）；占用时自动向后寻找；--host 0.0.0.0 才允许同局域网其他机器访问
    ... --db 别的.db     # 换数据库（默认 activities/_db/投放数据.db）
    ... --auto 30        # 自动刷新间隔（分钟；默认 30，给 0 关掉）
    懒得敲命令就双击 `web/start-hidden.vbs`。

用户 2026-09-28 定：**服务自己定时刷新**（`--auto`，默认 30 分钟）——
每天第一次先跑一次「取数」（把**昨天**的终值固定下来，只刷今天的话昨天那行会永远停在半截），
之后每 N 分钟刷「今天」的实时数；每个活动轮着来，串行仍由取数线程保证（浏览器只有一只）。
页头会显示「数据截止 / 最近取数 / 自动刷新（上次几点跑的）」。
"""
import argparse
import collections
import datetime
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent          # web/
REPO = HERE.parent
STATIC = HERE / "static"
sys.path.insert(0, str(REPO / "automation" / "scripts"))

import campaign as campaign_mod  # noqa: E402
import fetch_perf as fetch_mod   # noqa: E402
import runtime_state  # noqa: E402
import workspace_payload as wp  # noqa: E402
import workspace_repo as workspace_repo  # noqa: E402

CTYPE = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "application/javascript; charset=utf-8"}

# 活动登记表：启动时建一次，之后 HTTP 线程与取数线程都只读它（2026-09-28 多活动）
ACTIVITIES = {}             # 任务组名 -> {"id","label","cfg","cfg_path","activity_dir","data_root"}
DB_PATH = None              # 台账库：**全活动共用一份**（schema 本来就带活动维度）
DEFAULT_ID = None           # 页面不给 ?activity= 时用哪个活动
ACTUAL_PORT = None
SERVICE_NAME = "ad_management-board"
STARTED_AT = None
BOARD_LOCK = None

# 取数任务状态：**每个活动一份**（页面轮询它）；取数本身仍是全局串行（浏览器只有一只）
FETCH = {}
JOBS = queue.Queue()        # 取数线程的任务队列，元素 = (活动id, 模式)（一次只跑一个）
BROWSER = None              # 取数线程那只连接（挂在公共浏览器上）；**只有取数线程碰它**

# 自动刷新（2026-09-28 用户定：每 30 分钟；服务得有人开着）
#   每天**第一次**先跑一次「取数」（默认区间 = 最近有数据那天 ~ 昨天，把昨天的终值固定下来），
#   之后每 N 分钟刷一次「今天」的实时数。理由：只刷今天的话，昨天那行永远停在"半截的今天"，
#   复盘看到的昨天曝光会偏低。串行仍由取数线程保证（浏览器只有一只）。
AUTO = {"minutes": 30, "at": {}}    # minutes=0 关掉；at[活动] = 上次自动跑的时刻
AUTO_STEP = 30                      # 每 30 秒检查一次；真正执行仍受 AUTO["minutes"] 约束

# 活动生命周期以数据库 `activity.status` / `ended_on` 为准。已收尾活动不再参加整批刷新、
# 待复盘和自动复盘；登记表里照常留着（页面能看历史），要看历史仍可切过去。
#   补数窗口（同日用户定 N=2）：收尾日之后**再自动补 2 天**——后台数据回传有延迟，收尾那行
#   当天取到的是半截的，隔天重取才是终值。窗口内仍算"在跑"（自动刷新照跑、角标照算），
#   窗口外才彻底停。
ENDED_GRACE_DAYS = 2

# 「一次刷所有活动」的那一批（2026-10-09 用户定）：页面点刷新 / 取数 = 登记的活动全跑一遍。
# 这里只记"这一批点了谁、什么模式、什么时候点的"；每个活动的进度仍从 `FETCH` 现读——
# 两处各记一份状态迟早对不上（`FETCH` 是取数线程写的唯一真源）。
BATCH = {"mode": None, "at": None, "ids": [], "skipped": []}


def new_fetch_state():
    """一个活动的取数状态（形状与改造前一致，页面不用改字段名）。"""
    return {"running": False, "mode": None, "started": None, "finished": None, "ok": None,
            "snapshot": None, "error": None, "by": None, "permanent": False,
            "lines": collections.deque(maxlen=400)}


def activity(aid=None):
    """按任务组名取活动登记项；`None`/空串 = 默认活动；不认识的名字返回 None。"""
    if aid in (None, ""):
        aid = DEFAULT_ID
    return ACTIVITIES.get(aid)


def refresh_activity_statuses():
    """从数据库刷新活动生命周期；运行中的服务不必因启停而重启。"""
    global DEFAULT_ID
    if not ACTIVITIES:
        return
    conn = workspace_repo.connect(DB_PATH)
    try:
        rows = workspace_repo.list_activities(conn)
    finally:
        conn.close()
    by_id = {row["id"]: row for row in rows}
    for item in ACTIVITIES.values():
        row = by_id.get(item["db_id"])
        if row:
            item["ended"] = row["status"] == "ended"
            item["endedDay"] = row["ended_on"]
    if DEFAULT_ID in ACTIVITIES and ACTIVITIES[DEFAULT_ID].get("ended"):
        DEFAULT_ID = next(
            (aid for aid, item in ACTIVITIES.items()
             if not item.get("ended") and db_state(item)["days"]),
            DEFAULT_ID,
        )


def pick(query):
    """`?activity=` 里的活动 → (登记项, 请求里写的那个名字)；没给就用默认活动。"""
    wanted = (query.get("activity") or [""])[0] or DEFAULT_ID
    return activity(wanted), wanted


def flag(query, name):
    """`?<name>=1` 这种开关（页面统一这么传；`true` / `yes` 也认）。"""
    return (query.get(name) or ["0"])[0] in ("1", "true", "yes")


def snapshot_names(item):
    """取数凭据：数据库 v2 的 `fetch_run`。"""
    conn = workspace_repo.connect(DB_PATH)
    try:
        runs = workspace_repo.list_fetch_runs(conn, item["db_id"])
    finally:
        conn.close()
    return [r["finished_at"] or r["started_at"] for r in reversed(runs)]

def last_fetch(item):
    """最近一次成功取数的时间。"""
    names = snapshot_names(item)
    return names[-1] if names else None


def today_fetched(item):
    """今天是否已经跑过写入终值的完整取数。"""
    conn = workspace_repo.connect(DB_PATH)
    try:
        row = workspace_repo.full_fetch_on(
            conn, item["db_id"], datetime.date.today().isoformat()
        )
    finally:
        conn.close()
    return row["started_at"] if row else None


def db_state(item):
    """库内数据到哪天、有多少天（页头要显示"数据截止"，也用来判断要不要先取数）。"""
    try:
        conn = workspace_repo.connect(DB_PATH)
        try:
            ds = workspace_repo.activity_days(conn, item["db_id"])
        finally:
            conn.close()
    except Exception as e:
        return {"error": str(e), "days": 0, "first": None, "last": None}
    return {"days": len(ds), "first": ds[0] if ds else None, "last": ds[-1] if ds else None}


def fetch_state(item):
    """一个活动的取数状态（页面轮询用）。`busy` = 别的活动正在取数（取数是串行的）。"""
    st = FETCH.setdefault(item["id"], new_fetch_state())
    today = datetime.date.today().isoformat()
    conn = workspace_repo.connect(DB_PATH)
    try:
        last = workspace_repo.last_successful_fetch(conn, item["db_id"])
        state = db_state(item)
        done = workspace_repo.full_fetch_on(conn, item["db_id"], today)
        today_all = all(
            other.get("ended") or
            workspace_repo.full_fetch_on(conn, other["db_id"], today) is not None
            for other in ACTIVITIES.values()
        )
    finally:
        conn.close()
    busy = running_activity()
    at = AUTO["at"].get(item["id"])
    return {
        "running": st["running"], "mode": st["mode"],
        "started": st["started"], "finished": st["finished"],
        "ok": st["ok"], "snapshot": st["snapshot"], "error": st["error"],
        "lines": list(st["lines"])[-40:],
        "activity": item["id"], "by": st["by"],
        "auto": {"minutes": AUTO["minutes"],
                 "at": at.strftime("%H:%M:%S") if at else None,
                 "ok": st["ok"] if st["by"] == "auto" else None},
        "busy": bool(busy and busy != item["id"]),
        "busyWith": busy if busy != item["id"] else None,
        "lastFetch": last["finished_at"] if last else None,
        "lastFetchTime": last["finished_at"] if last else "",
        "db": state, "todayDone": bool(done),
        "todayFetch": done["started_at"] if done else None,
        "todayDoneAll": today_all,
        "readOnly": False,
    }


def ended_until(item):
    """补数窗口的最后一天（收尾日 + 2 天）；标记里没写收尾日 → `None`。"""
    try:
        deadline = (datetime.date.fromisoformat(item.get("endedDay") or "")
                    + datetime.timedelta(days=ENDED_GRACE_DAYS))
    except ValueError:
        return None
    return deadline.isoformat()


def fetch_stopped(item):
    """这个活动现在是否**彻底不用取数**了（已收尾 且 过了「收尾日 + 2 天」补数窗口）。

    窗口内仍当"在跑"：后台数据回传有延迟，收尾那天取的数是半截的，隔 1~2 天重取才是终值。
    """
    if not item.get("ended"):
        return False
    until = ended_until(item)
    return True if until is None else datetime.date.today().isoformat() > until


def today_fetched_all():
    """所有**还在跑**的活动今天都取过数没（配额仍是**按活动**各算一份，这里只是取交集）。

    彻底停掉的活动（收尾 + 过了补数窗口）不参与：它不再自动取数，算上它会永远显示"今天还没取"。
    """
    live = [it for it in ACTIVITIES.values() if not fetch_stopped(it)]
    return all(today_fetched(it) for it in live)


def running_activity():
    """当前正在取数的活动（取数串行：浏览器只有一只，所以最多一个）。"""
    for aid, st in FETCH.items():
        if st["running"]:
            return aid
    return None


def activities_payload():
    """活动登记表（页面切换器用）；顺序 = 登记顺序 = 配置路径排序，稳定不变。"""
    return {"default": DEFAULT_ID,
            "activities": [{"id": it["id"], "label": it["label"],
                            "dir": it.get("activity_dir", ""),
                            "cfgPath": it.get("cfg_path", ""), "db": db_state(it),
                            "ended": bool(it.get("ended"))}
                           for it in ACTIVITIES.values()]}


def todo_payload():
    """**所有活动**的「到门槛 · 没复盘 · 还在投」工单（页面角标 + 弹窗）。

    为什么在服务端算：页面一次只加载一个活动（`/api/perf` 按 `?activity=` 给），
    「所有活动合计」只有服务端知道谁是全部活动。
    规则本体在 `workspace_payload.todo_rows()`——与 `/api/perf` 共用同一套判定
    （`judging.py`），不在页面里另抄一份（口径抄第二遍迟早跟第一份走散）。
    算不出来的活动（库里还没数据 / YAML 坏了）**跳过并打一行**，不让一个活动拖垮整份清单。

    ⚠ 缓存（2026-10-09 修）：**取数正在跑的时候不吃缓存、也不写缓存**——那一刻库是
    "只有一部分活动是新数"的样子，缓存了会给页面看半分钟旧清单（页面角标显示 1、
    表格里明明有三条，就是这么来的）。取数线程每跑完一个活动会 `invalidate_todo()`。
    """
    items = []
    conn = workspace_repo.connect(DB_PATH)
    try:
        for item in ACTIVITIES.values():
            if not item.get("ended"):
                items.extend(wp.todo_rows(conn, item["db_id"]))
    finally:
        conn.close()
    items.sort(key=lambda r: (-(r["exposure"] / max(r["threshold"], 1)),
                              r["activity"], r["bucket"]))
    return {"count": len(items),
            "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "items": items}


def auto_action(item, now=None):
    """自动刷新现在该干什么：`full`（还没取过数）/ `today`（刷今天）/ `None`（还没到时候）。

    - **今天没取过数** → 先跑一次「取数」：默认区间补到昨天，把昨天的终值固定下来（一天一次）；
    - 之后按 `AUTO["minutes"]` 的间隔刷「今天」的实时数（随时可点的那种，不落流水）；
    - 到没到点看 `AUTO["at"]`（**本活动上次自动尝试的时刻**）——成功和失败都算一次，
      失败后也按同一间隔重试，不能把 30 秒的调度检查变成 30 秒重试；
    - 任务组不存在等永久错误暂停自动重试；手动触发仍可重新检查；
    - **活动收尾**（数据库 `activity.status='ended'`）→ 只在「收尾日 + 2 天」补数窗口内继续自动补，
      过了窗口不再自动刷新（2026-10-12）；
    - `AUTO["minutes"] = 0` = 关掉。
    """
    if not AUTO["minutes"] or fetch_stopped(item):
        return None
    if FETCH.get(item["id"], {}).get("permanent"):
        return None
    last = AUTO["at"].get(item["id"])
    now = now or datetime.datetime.now()
    if last and (now - last) < datetime.timedelta(minutes=AUTO["minutes"]):
        return None
    if not today_fetched(item):
        return "full"
    return "today"


def auto_worker():
    """自动刷新线程：醒来就逐个活动投任务（取数线程再串行执行）。

    到点还没轮上（浏览器正忙 / 上一次还没跑完）就跳过，下一轮再说——不排队、不堆任务。
    """
    while True:
        time.sleep(AUTO_STEP)
        if not AUTO["minutes"]:
            continue
        for aid, item in list(ACTIVITIES.items()):
            mode = auto_action(item)
            if not mode:
                continue
            code, _ = start_fetch(aid, mode, by="auto")
            if code == 202:
                AUTO["at"][aid] = datetime.datetime.now()
                print("  自动刷新：%s %s（每 %d 分钟一次）"
                      % (item["label"], "取数（固定昨天）" if mode == "full" else "刷新今天",
                         AUTO["minutes"]), flush=True)


def fetch_note(aid):
    """取数过程的一行：**全部**进这个活动的状态（页面看得到）；**窗口只打结论行**。

    2026-09-29 用户要求窗口"规范一点"：页面那份是明细（逐工单 × 日期、逐资源），
    窗口只留「RESULT: …」「✗ …」——正常跑完一行，出问题一眼看得到。
    """
    def note(line):
        FETCH[aid]["lines"].append(line)
        s = line.strip()
        if s.startswith(("RESULT:", "✗", "!")):
            print("  [%s] %s" % (aid, s), flush=True)
    return note


def fetch_error(e):
    """取数失败给人看的那句话。

    只有**真像登录态问题**（跳了登录页 / 未授权 / 401 / 403）才提 `wait_login.py`。
    2026-10-12 修：原来无条件套这句提示，把"日期区间算错""DNS 都解析不出来"也一起
    指去重登，纯属误导——一次故障最贵的成本就是把人带去查错的地方。
    """
    msg = str(e)
    if re.search(r"登录|未授权|unauthor|40[13]", msg, re.I):
        return "%s（登录态过期就去跑 automation/scripts/wait_login.py）" % msg
    return msg


def _fetch_job(item, mode):
    """真正跑一次取数：`today`＝只查今天 / `full`＝默认区间补到昨天。

    **两者都不落 CSV 流水**（2026-10-14 起默认不落）：取数事件和指标都写入数据库 v2。
    """
    if mode == "today":
        today = datetime.date.today().isoformat()
        fetch_mod.run(item["id"], v2_db_path=DB_PATH, date_from=today, date_to=today,
                      note=fetch_note(item["id"]), browser=BROWSER)
    else:
        fetch_mod.run(item["id"], v2_db_path=DB_PATH,
                      note=fetch_note(item["id"]), browser=BROWSER)


def fetch_worker():
    """取数线程：**独占**那一条浏览器连接，任务从队列里来（playwright 同步接口不能跨线程）。

    起服务时就把公共浏览器拉起来（用户要的：双击 start-hidden.vbs 就起）；拉不起来也不算完蛋——
    第一次点刷新会再试一次。出错的连接不留着，直接断开重挂（**浏览器本身不关**，别的程序还在用）。
    """
    global BROWSER
    BROWSER = fetch_mod.Browser()
    try:
        BROWSER.start()
        print("  浏览器：已挂上公共浏览器（刷新 / 取数都复用它；关本窗口不关它）", flush=True)
    except Exception as e:
        print("  ! 浏览器：没起来（点第一次刷新时会再试）：%s" % e, flush=True)
        BROWSER.close()
    while True:
        job = JOBS.get()
        if job is None:                        # 收工信号（关窗口 / Ctrl+C）
            break
        aid, mode = job
        item, st = ACTIVITIES[aid], FETCH[aid]
        try:
            _fetch_job(item, mode)
            st["ok"] = True
            st["permanent"] = False
            st["snapshot"] = last_fetch(item)
        except Exception as e:
            st["ok"] = False
            st["permanent"] = isinstance(e, fetch_mod.PermanentFetchError)
            st["error"] = fetch_error(e)
            if st["permanent"]:
                st["error"] += "（自动重试已暂停；修正后请手动重试）"
            BROWSER.close()                    # 断开这条连接；下一次重挂（不关浏览器）
            traceback.print_exc()              # 详细堆栈打到服务窗口，方便回头查
        finally:
            st["running"] = False
            st["finished"] = datetime.datetime.now().strftime("%H:%M:%S")
    BROWSER.close()
    print("  浏览器：已断开连接（公共浏览器留着给别的程序用；要关：browser_broker.py --stop）",
          flush=True)


def batch_state():
    """页面那条"正在刷新 2/3：火山…"的进度（一次刷全部活动，2026-10-09 用户定）。

    每个活动的状态**现读 `FETCH`**（取数线程写的唯一真源）；这里只负责排序 + 数个数。
    没跑过任何一批时返回空 items，页面据此不显示进度。
    """
    skipped = {s["activity"]: s for s in BATCH["skipped"]}
    items = []
    for aid in list(BATCH["ids"]) + [s["activity"] for s in BATCH["skipped"]]:
        item = ACTIVITIES.get(aid)
        if item is None:                       # 活动被移除了：跳过，别让进度卡住
            continue
        if aid in skipped:
            items.append({"activity": aid, "label": item["label"], "state": "skipped",
                          "note": skipped[aid]["note"], "started": None, "finished": None,
                          "error": None})
            continue
        st = FETCH.setdefault(aid, new_fetch_state())
        state = ("running" if st["running"] else
                 "ok" if st["ok"] else
                 "error" if st["ok"] is False else "pending")
        items.append({"activity": aid, "label": item["label"], "state": state, "note": None,
                      "started": st["started"], "finished": st["finished"], "error": st["error"]})
    return {"mode": BATCH["mode"], "at": BATCH["at"], "items": items,
            "total": len(items), "done": sum(1 for i in items if i["state"] != "pending"
                                             and i["state"] != "running"),
            "running": any(i["state"] in ("pending", "running") for i in items),
            "okCount": sum(1 for i in items if i["state"] == "ok"),
            "errorCount": sum(1 for i in items if i["state"] == "error"),
            "skippedCount": sum(1 for i in items if i["state"] == "skipped")}


def busy_reason():
    """现在能不能投任务；不能就给一句给人看的原因（`None` = 可以）。

    队列非空也算忙（2026-10-09 加）：一次刷全部活动时，两个任务中间有一瞬间
    `running_activity()` 是 None——不把队列算进来，自动刷新 / 手快点第二下就会重复排队。
    """
    busy = running_activity()
    if busy:
        return "正在取数中（%s），等这一批跑完再点" % busy
    if not JOBS.empty():
        return "队列里还排着 %d 个任务没跑完，等这一批跑完再点" % JOBS.qsize()
    return None


def enqueue_fetch(item, mode, by):
    """把一次取数**塞进队列**（不查闸）：状态先写上再排队——页面轮询靠它。"""
    st = FETCH[item["id"]]
    st.update({"running": True, "mode": mode,
               "started": datetime.datetime.now().strftime("%H:%M:%S"),
               "finished": None, "ok": None, "snapshot": None, "error": None, "by": by})
    st["lines"].clear()
    JOBS.put((item["id"], mode))


def start_fetch(aid, mode="full", force=False, by="manual"):
    """把一次取数**投进队列**：`full`＝取数（到昨天，一天一次）/ `today`＝刷新今天。

    真正干活的是常驻的取数线程（浏览器在它那儿）。返回 (http 码, 内容)。
    「同时只跑一个」是全局的（浏览器只有一只，跨活动也串行）；「今天已取」按活动算。
    `by` 只记账（`manual` = 页面点的 / `auto` = 自动刷新），不参与任何闸。
    """
    item = activity(aid)
    if item is None:
        return 404, {"error": "没有这个活动：%s" % aid}
    busy = busy_reason()
    if busy:
        return 409, {"error": busy, "state": fetch_state(item)}
    today = datetime.date.today().isoformat()
    if mode == "full" and not force:
        done = today_fetched(item)
        if done:
            return 409, {"error": "今天已经取过数了（%s）——昨天不会再变；今天的实时数请点「刷新」" % done,
                         "blocked": True, "state": fetch_state(item)}
    enqueue_fetch(item, mode, by)
    return 202, {"started": True, "activity": item["id"], "state": fetch_state(item)}


def start_fetch_all(mode="today", current=None, force=False, by="manual"):
    """**一次把登记的活动全跑一遍**（用户 2026-10-09 定）：页面的刷新 / 取数都走这里。

    为什么改成这样：浏览器只有一只、取数本来就是串行的，"一次只刷一个活动"没有省下任何时间，
    只是把一条队列拆成好几次点击；而「待复盘」角标是**跨活动**的，只刷一个活动它必然半新半旧。
    顺序 = **当前看的活动先跑**，其余按登记顺序（眼前这块先变新）。

    `full`（取数）仍按活动各算「一天一次」的配额：已经取过的**跳过、并在结果里说明**，
    不整批报错（自动刷新每天早上已经把 full 跑过一遍，手动再点通常就是"只剩某个活动没取"）。
    **已收尾的活动一律跳过**（2026-10-12 用户定）：活动投完了就没必要再整批带上它——
    它一失败还会把整批拖成"0 成功 N 失败"，看不出到底是谁出问题。要补它得切到那个活动
    单独点「取数」（单活动入口不拦，那是人明确要的）。
    """
    busy = busy_reason()
    if busy:
        return 409, {"error": busy, "batch": batch_state()}
    ids = list(ACTIVITIES)
    if current in ids:
        ids.remove(current)
        ids.insert(0, current)
    run, skipped = [], []
    for aid in ids:
        item = ACTIVITIES[aid]
        if item.get("ended"):               # 收尾了就整批不带它——补数窗口只管自动刷新那一趟
            skipped.append({"activity": aid,
                            "note": "已收尾，不再整批取数——要补就切到它单独点「取数」"})
            continue
        if mode == "full" and not force:
            done = today_fetched(item)
            if done:
                skipped.append({"activity": aid, "note": "今天已经取过数了（%s）" % done})
                continue
        run.append(aid)
    if not run:
        if skipped and all(s["note"].startswith("已收尾") for s in skipped):
            return 409, {"error": "登记的活动都已收尾，没有要取数的"
                                  "——要补历史数据请切到那个活动单独点「取数」",
                         "blocked": True, "batch": batch_state()}
        return 409, {"error": "所有活动今天都取过数了——昨天不会再变；今天的实时数请点「刷新」",
                     "blocked": True, "batch": batch_state()}
    BATCH.update({"mode": mode, "at": datetime.datetime.now().strftime("%H:%M:%S"),
                  "ids": run, "skipped": skipped})
    for aid in run:
        enqueue_fetch(ACTIVITIES[aid], mode, by)
    return 202, {"started": True, "mode": mode, "activities": run,
                 "skipped": [s["activity"] for s in skipped], "batch": batch_state()}


class Handler(BaseHTTPRequestHandler):
    """只放 HTTP 的事；活动配置与库路径都在模块级的登记表 / DB_PATH 里。"""

    def _send(self, code, body, ctype):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")   # 别缓存：点了刷新就得是新数
        self.end_headers()
        try:
            self.wfile.write(raw)
        except Exception:
            pass

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _static(self, name):
        p = STATIC / name
        if not p.exists():
            self._send(404, "404：没有这个页面资源 %s" % name, "text/plain; charset=utf-8")
            return
        self._send(200, p.read_bytes(), CTYPE.get(p.suffix, "application/octet-stream"))

    def do_GET(self):
        refresh_activity_statuses()
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        if u.path in ("/", "/index.html"):
            self._static("index.html")
            return
        if u.path in ("/app.css", "/app.js"):
            self._static(u.path.lstrip("/"))
            return
        if u.path == "/api/activities":
            self._json(200, activities_payload())
            return
        if u.path == "/api/health":
            self._json(200, {
                "service": SERVICE_NAME,
                "pid": os.getpid(),
                "port": ACTUAL_PORT,
                "db": DB_PATH,
                "started": STARTED_AT,
            })
            return
        if u.path == "/api/todo":                 # 跨活动：不吃 ?activity=，就在 pick() 之前拦下来
            self._json(200, todo_payload())
            return
        if u.path == "/api/fetch/status" and flag(q, "all"):
            # 一次刷全部活动的进度（2026-10-09）：跨活动，也拦在 pick() 之前
            self._json(200, {"batch": batch_state(), "anyRunning": running_activity()})
            return
        item, wanted = pick(q)
        if item is None:
            self._json(404, {"error": "没有这个活动：%s" % wanted})
            return
        if u.path == "/api/snapshots":
            self._json(200, {"activity": item["id"], "snapshots": snapshot_names(item)})
            return
        if u.path == "/api/perf":
            conn = workspace_repo.connect(DB_PATH)
            try:
                self._json(200, wp.build_payload(conn, item["db_id"]))
            finally:
                conn.close()
            return
        if u.path == "/api/fetch/status":
            self._json(200, fetch_state(item))
            return
        self._send(404, "404：只提供 /、/app.css、/app.js、/api/activities、/api/todo、"
                        "/api/perf、/api/snapshots、/api/fetch/status",
                   "text/plain; charset=utf-8")

    def do_POST(self):
        refresh_activity_statuses()
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/fetch":
            if flag(q, "all"):
                # 页面上的刷新 / 取数 = 一次跑全部活动（2026-10-09 用户定）；
                # `?activity=` 只用来决定"谁先跑"，不影响跑哪些。
                cur = pick(q)[0]
                code, obj = start_fetch_all("today" if flag(q, "today") else "full",
                                            current=cur["id"] if cur else None,
                                            force=flag(q, "force"))
                self._json(code, obj)
                return
            item, wanted = pick(q)
            if item is None:
                self._json(404, {"error": "没有这个活动：%s" % wanted})
                return
            code, obj = start_fetch(item["id"], "today" if flag(q, "today") else "full",
                                    flag(q, "force"))
            self._json(code, obj)
            return
        self._send(404, "404：POST 只支持 /api/fetch", "text/plain; charset=utf-8")

    def log_message(self, fmt, *args):      # 访问日志：只报 4xx / 5xx
        # 页面每次拉数据、每个静态资源都会走这里 —— 全打出来会把窗口刷满（2026-09-29 用户反馈）
        code = str(args[1]) if len(args) > 1 else ""
        if code[:1] not in ("4", "5"):
            return
        print("  ! %s" % (fmt % args), flush=True)


class BoardServer(ThreadingHTTPServer):
    """看板服务的 HTTP 服务端——**Windows 下不许第二个实例绑同一个端口**。

    2026-10-12 踩到：`http.server` 默认 `allow_reuse_address = 1`，而这在 Windows 上等价于
    SO_REUSEADDR——第二个看板照样能绑上 8770、**不报"端口被占用"**，于是两个实例一起去抢
    同一个 `.browser-profile`：抢到锁的那个正常，另一个每次取数都报"浏览器起不来"，
    页面请求又在两个实例之间随机落 → 看起来像"时好时坏"。
    Windows 下关掉它 → 第二个实例启动就绑不上（报清楚），比默默变成两个服务强。
    """
    allow_reuse_address = (os.name != "nt")


def serve_v2(args):
    """数据库 v2 单库运行：读取、取数和复盘都走同一个库。"""
    global BOARD_LOCK, DB_PATH, DEFAULT_ID, ACTUAL_PORT, STARTED_AT
    BOARD_LOCK = runtime_state.acquire_file_lock(
        runtime_state.TMP / "board-service.lock"
    )
    if BOARD_LOCK is None:
        print("看板服务已经有另一个实例正在运行或启动中", flush=True)
        return
    existing = runtime_state.read_state("board")
    if existing:
        try:
            current = runtime_state.get_json(
                "http://127.0.0.1:%d/api/health" % int(existing["port"])
            )
        except Exception:
            current = {}
        if (
            current.get("service") == SERVICE_NAME
            and int(current.get("pid") or 0) == int(existing.get("pid") or 0)
            and runtime_state.process_matches(
                int(existing.get("pid") or 0), [str(REPO), "app.py"],
                allow_unknown=True,
            )
        ):
            print("看板服务已经在运行：http://127.0.0.1:%s/" % existing["port"], flush=True)
            runtime_state.release_file_lock(BOARD_LOCK)
            BOARD_LOCK = None
            return
    DB_PATH = args.db
    AUTO["minutes"] = max(0, int(args.auto))
    conn = workspace_repo.connect(DB_PATH)
    try:
        rows = workspace_repo.list_activities(conn)
    finally:
        conn.close()
    if not rows:
        raise SystemExit("v2 库里没有活动：%s" % DB_PATH)
    try:
        found = campaign_mod.discover(REPO / "activities")
        configs = {it["id"]: it for it in found}
    except Exception as e:
        raise SystemExit("活动 YAML 登记失败：%s" % e)
    for row in rows:
        aid = row["activity_key"]
        matched = configs.get(aid)
        ACTIVITIES[aid] = {
            "id": aid, "db_id": row["id"], "label": row["display_name"],
            "cfg": matched["cfg"] if matched else {},
            "cfg_path": matched["cfg_path"] if matched else "",
            "activity_dir": matched["activity_dir"] if matched else "",
            "data_root": None,
            "ended": row["status"] == "ended", "endedDay": row["ended_on"],
        }
        FETCH[aid] = new_fetch_state()
    DEFAULT_ID = next(
        (aid for aid, item in ACTIVITIES.items()
         if not item.get("ended") and db_state(item)["days"]),
        next((aid for aid, item in ACTIVITIES.items() if db_state(item)["days"]),
             rows[0]["activity_key"]),
    )

    print("看板服务已启动（数据库 v2 单库）：", flush=True)
    print("  v2 库：%s" % DB_PATH, flush=True)
    for aid, item in ACTIVITIES.items():
        state = db_state(item)
        print("  活动：%s（%s）—— 库内 %d 天，%s ~ %s%s" % (
            item["label"], aid, state["days"], state["first"] or "—",
            state["last"] or "—", "（默认）" if aid == DEFAULT_ID else "",
        ), flush=True)
    server = None
    last_error = None
    for port in range(args.port, args.port + 100):
        try:
            server = BoardServer((args.host, port), Handler)
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise SystemExit("  起不来：从 %s:%d 起 100 个端口都无法监听。原始报错：%s" %
                         (args.host, args.port, last_error))
    ACTUAL_PORT = int(server.server_address[1])
    STARTED_AT = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    runtime_state.write_state("board", {
        "service": SERVICE_NAME,
        "pid": os.getpid(),
        "port": ACTUAL_PORT,
        "host": args.host,
        "db": DB_PATH,
        "started": STARTED_AT,
    })
    print("  打开：http://%s:%d/" % (args.host, ACTUAL_PORT), flush=True)
    worker = threading.Thread(target=fetch_worker, name="fetch", daemon=True)
    worker.start()
    threading.Thread(target=auto_worker, name="auto", daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  收到退出：断开 v2 取数连接，收工…", flush=True)
    finally:
        runtime_state.clear_state("board", pid=os.getpid())
        JOBS.put(None)
        worker.join(timeout=10)
        runtime_state.release_file_lock(BOARD_LOCK)
        BOARD_LOCK = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=workspace_repo.V2_DB, help="数据库 v2 路径")
    ap.add_argument("--port", type=int, default=8770, help="首选端口（默认 8770，占用时自动向后寻找）")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认只本机；0.0.0.0 = 同局域网可访问）")
    ap.add_argument("--auto", type=int, default=30,
                    help="自动刷新间隔（分钟；默认 30，**给 0 就关掉**）。每天第一次先跑一次「取数」把昨天固定下来")
    a = ap.parse_args()

    serve_v2(a)


if __name__ == "__main__":
    main()
