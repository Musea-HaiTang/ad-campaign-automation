# -*- coding: utf-8 -*-
"""投放看板服务（本地）：浏览器打开就是看板，页面自己来拿数据；取数用一只**常驻浏览器**。

用户 2026-09-17 定：可视化走「**前后端分离**」——
    ① 取数 `automation/scripts/fetch_perf.py`（要登录态、连后台；**增量**）→ 写台账库
    ② 本服务（`web/app.py`）读**台账库**（`activities/_db/投放数据.db`）→ 聚合成 JSON → 交给页面
    ③ 页面（`web/static/`）`fetch` → 渲染；筛选 / 切换都在浏览器里算

用户 2026-09-24 定：**浏览器常驻**——双击 `web/start.bat` 起服务时就把浏览器开起来（无窗口），
之后每次「刷新 / 取数」都复用它（省掉每次 ≈1.7 秒的起/关浏览器开销）；
**关掉服务窗口 / Ctrl+C 时一起关**。取数逻辑仍在 `automation/scripts/fetch_perf.py`（`fetch_mod.run`），
本服务只是把它常驻的那只浏览器喂给它——依赖方向还是 web → automation，没变。

用户 2026-09-28 定：**一个服务管多个活动**（方案见 `web/多活动改造方案.md`）——
启动时用 `campaign.discover()` 扫 `activities/*/配置/*.yaml` 建一张**活动登记表**；
下面每个接口都可以带 `?activity=<任务组名>`，不给就用默认活动（有数据的那个）。
**浏览器仍然只有一只**（一个登录 profile 只能被一个进程用），所以取数是**串行**的；
但「今天已取」的配额、取数流水、状态都是**按活动各算一份**。

接口（全部只读，不写文件、不连后台）：
    GET /                      看板页面
    GET /app.css, /app.js      页面资源
    GET /api/activities        活动登记表（id / 标签 / 目录 / 库内数据到哪天）
    GET /api/perf              台账聚合好的 JSON（区间 = 库里有的全部日期）
    GET /api/todo              **所有活动**里「到门槛 · 没复盘 · 还在投」的工单
                               （页面右上角那个角标 + 弹窗；跨活动，所以只能服务端算）
    GET /api/snapshots         取数流水（原始存档）清单——不是数据源，只是取数凭据
    GET /api/fetch/status      取数状态（正在跑没 / 上次取数时刻 / 今天取过数没）
    GET /api/fetch/status?all=1  **一次刷全部活动**那一批的进度（哪个在跑 / 哪个跑完 / 跳过谁）
    POST /api/fetch            **取数**：把昨天的数固定下来（默认区间＝到昨天，落取数流水）
                               —— **一天只允许一次**（用户 2026-09-20 定：昨天不会再变，重复取没意义）
    POST /api/fetch?today=1    **刷新今天**：只查今天这一天（常驻浏览器后实测
                               首次 ≈1.8 秒、之后 0.9~1.1 秒），随时可以点
                               —— 两个模式共用「同时只跑一个」的闸，互不占用对方的配额；
                               刷新**不落取数流水**（数据进台账库就够，免得一天堆一堆文件夹）

    用户 2026-10-09 定：**页面上的「刷新」「取数」= 一次把所有登记的活动都跑一遍**
    （`?all=1`，顺序 = 当前看的活动先跑）。理由：浏览器只有一只、取数本来就串行，
    分开点并不会更快；而「待复盘」角标是跨活动的，只刷一个活动它必然半新半旧。
    单活动的 `?activity=xxx` 仍然保留（自动刷新、脚本、命令行都还在用）。

    （以上除 `/` 与页面资源外，都可以带 `?activity=<任务组名>`；不给 = 默认活动。
      「同时只跑一个」是**全局**的——浏览器只有一只；「今天已取」是**按活动**算的。）

⚠ **一个 profile 只能一个进程用**：服务开着时浏览器归它，别再在命令行跑 `fetch_perf.py`、
   也别跑 `wait_login.py`（会抢 `.browser-profile`）；要跑就先关掉这个窗口。

用法：
    .venv\\Scripts\\python.exe -u web/app.py [--config activities/{活动名}/配置/{品牌}{负责人}.yaml]
    ... --port 8770      # 默认 8770（只本机）；--host 0.0.0.0 才允许同局域网其他机器访问
    ... --db 别的.db     # 换台账库（默认 activities/_db/投放数据.db）
    ... --auto 30        # 自动刷新间隔（分钟；默认 30，给 0 关掉）
    （不给 --config 就登记 `activities/*/配置/*.yaml` 下的**全部**活动；
      给了就是"只登记这一个"——以前只认得一个活动，现在它降级成筛选器）
    懒得敲命令就双击 `web/start.bat`。

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
import perf_db  # noqa: E402
import perf_payload as pp  # noqa: E402

CTYPE = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "application/javascript; charset=utf-8"}

# 活动登记表：启动时建一次，之后 HTTP 线程与取数线程都只读它（2026-09-28 多活动）
ACTIVITIES = {}             # 任务组名 -> {"id","label","cfg","cfg_path","activity_dir","data_root"}
DB_PATH = None              # 台账库：**全活动共用一份**（schema 本来就带活动维度）
DEFAULT_ID = None           # 页面不给 ?activity= 时用哪个活动

# 取数任务状态：**每个活动一份**（页面轮询它）；取数本身仍是全局串行（浏览器只有一只）
FETCH = {}
JOBS = queue.Queue()        # 取数线程的任务队列，元素 = (活动id, 模式)（一次只跑一个）
BROWSER = None              # 常驻浏览器；**只有取数线程碰它**（playwright 同步接口不能跨线程）

# 自动刷新（2026-09-28 用户定：每 30 分钟；服务得有人开着）
#   每天**第一次**先跑一次「取数」（默认区间 = 最近有数据那天 ~ 昨天，把昨天的终值固定下来），
#   之后每 N 分钟刷一次「今天」的实时数。理由：只刷今天的话，昨天那行永远停在"半截的今天"，
#   复盘看到的昨天曝光会偏低。串行仍由取数线程保证（浏览器只有一只）。
AUTO = {"minutes": 30, "at": {}}    # minutes=0 关掉；at[活动] = 上次自动跑的时刻
AUTO_STEP = 30                      # 计时线程每 30 秒醒一次看该不该跑（不值当为它精算）

# 「活动收尾」标记（2026-10-12 用户定）：活动根下有 `已结束.md` 的活动**不再参加整批刷新**——
#   活动投完了、判定也停了（巡检那边同一条标记），登记表里照常留着（页面能看历史）；
#   要看 / 要补就切到它单独点「取数」（那是人明确要的）。
#   补数窗口（同日用户定 N=2）：收尾日之后**再自动补 2 天**——后台数据回传有延迟，收尾那行
#   当天取到的是半截的，隔天重取才是终值。窗口内仍算"在跑"（自动刷新照跑、角标照算），
#   窗口外才彻底停。
ENDED_MARKER = "已结束.md"
# 只认「收尾日：2026-10-12」这种**标签紧跟日期**的写法：正文里顺嘴提到的
# 「收尾日 + 2 天，本例 2026-10-14」不能被抓成收尾日（那会把窗口整体往后挪）。
ENDED_DAY_RE = re.compile(r"收尾日\*{0,2}\s*[：: ]\s*(\d{4}-\d{2}-\d{2})")
ENDED_GRACE_DAYS = 2

# /api/todo（跨活动的「到门槛 · 没复盘」清单）的结果缓存：弹窗可能连点，
# 而每算一次要把**每个活动**的 payload 都装配一遍。60 秒足够新，坏处是刚取完数
# 可能还看得到上一份（最多 1 分钟），代价比"每次点击全量重算"小得多。
TODO_CACHE = {"at": 0.0, "payload": None}
TODO_TTL = 60

# 「一次刷所有活动」的那一批（2026-10-09 用户定）：页面点刷新 / 取数 = 登记的活动全跑一遍。
# 这里只记"这一批点了谁、什么模式、什么时候点的"；每个活动的进度仍从 `FETCH` 现读——
# 两处各记一份状态迟早对不上（`FETCH` 是取数线程写的唯一真源）。
BATCH = {"mode": None, "at": None, "ids": [], "skipped": []}


def new_fetch_state():
    """一个活动的取数状态（形状与改造前一致，页面不用改字段名）。"""
    return {"running": False, "mode": None, "started": None, "finished": None, "ok": None,
            "snapshot": None, "error": None, "by": None,
            "lines": collections.deque(maxlen=400)}


def activity(aid=None):
    """按任务组名取活动登记项；`None`/空串 = 默认活动；不认识的名字返回 None。"""
    if aid in (None, ""):
        aid = DEFAULT_ID
    return ACTIVITIES.get(aid)


def pick(query):
    """`?activity=` 里的活动 → (登记项, 请求里写的那个名字)；没给就用默认活动。"""
    wanted = (query.get("activity") or [""])[0] or DEFAULT_ID
    return activity(wanted), wanted


def flag(query, name):
    """`?<name>=1` 这种开关（页面统一这么传；`true` / `yes` 也认）。"""
    return (query.get(name) or ["0"])[0] in ("1", "true", "yes")


def snap_time(name):
    """快照文件夹名 `2026-09-17_0944` → `2026-09-17 09:44`。"""
    if not name or "_" not in name:
        return name or ""
    d, t = name.split("_", 1)
    t = t.split("_")[0]
    return "%s %s:%s" % (d, t[:2], t[2:4]) if len(t) >= 4 else "%s %s" % (d, t)


def snapshot_names(item):
    return [p.name for p in pp.snapshots(item["data_root"])] if item.get("data_root") else []


def last_fetch(item):
    """最近一次**取数**的流水文件夹名（「刷新今天」不落流水，所以流水里只有取数）。"""
    names = snapshot_names(item)
    return names[-1] if names else None


def today_fetched(item):
    """今天是否已经**取过数**（＝写过一份不带标签的今天流水）。

    「刷新今天」写的是带标签的那种，不算数——否则点一次刷新就把当天的取数配额吃掉了。
    配额是**按活动**算的：给 KIRO 取数不吃火山的额度。
    """
    last = last_fetch(item)
    return last if (last and last.startswith(datetime.date.today().isoformat())) else None


def db_state(item):
    """库内数据到哪天、有多少天（页头要显示"数据截止"，也用来判断要不要先取数）。"""
    try:
        conn = perf_db.connect(DB_PATH)
        try:
            ds = perf_db.days(conn, item["id"])
        finally:
            conn.close()
    except Exception as e:
        return {"error": str(e), "days": 0, "first": None, "last": None}
    return {"days": len(ds), "first": ds[0] if ds else None, "last": ds[-1] if ds else None}


def fetch_state(item):
    """一个活动的取数状态（页面轮询用）。`busy` = 别的活动正在取数（取数是串行的）。"""
    st = FETCH.setdefault(item["id"], new_fetch_state())
    last = last_fetch(item)
    done = today_fetched(item)
    busy = running_activity()
    at = AUTO["at"].get(item["id"])
    return {"running": st["running"], "mode": st["mode"],
            "started": st["started"], "finished": st["finished"],
            "ok": st["ok"], "snapshot": st["snapshot"], "error": st["error"],
            "lines": list(st["lines"])[-40:],
            "activity": item["id"],
            "by": st["by"],                       # manual（页面点的）/ auto（自动刷新）
            "auto": {"minutes": AUTO["minutes"], "at": at.strftime("%H:%M:%S") if at else None,
                     "ok": st["ok"] if st["by"] == "auto" else None},
            "busy": bool(busy and busy != item["id"]),
            "busyWith": busy if busy != item["id"] else None,
            "lastFetch": last, "lastFetchTime": snap_time(last), "db": db_state(item),
            "todayDone": bool(done), "todayFetch": done,
            # 「取数」按钮看 todayDoneAll（2026-10-09 起取数是**一次刷全部活动**）：
            # 只按当前活动算的话，会出现"按钮说今天已取、其实另一个活动还没取"。
            "todayDoneAll": bool(ACTIVITIES) and today_fetched_all()}


def ended_day(activity_dir):
    """`已结束.md` 里那行「收尾日：YYYY-MM-DD」的日子。

    没有这个日期（老标记 / 手写漏了）→ `None` = 不补数、立即停：宁可不动它，
    也别一直去碰一个已经收尾的活动。
    """
    try:
        text = (Path(activity_dir) / ENDED_MARKER).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        m = ENDED_DAY_RE.search(line)
        if m:
            return m.group(1)
    return None


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


def invalidate_todo():
    """新数进库 → 待复盘清单作废（用户 2026-10-09：刷新 / 取数完角标必须跟着变）。"""
    TODO_CACHE["at"], TODO_CACHE["payload"] = 0.0, None


def running_activity():
    """当前正在取数的活动（取数串行：浏览器只有一只，所以最多一个）。"""
    for aid, st in FETCH.items():
        if st["running"]:
            return aid
    return None


def activities_payload():
    """活动登记表（页面切换器用）；顺序 = 登记顺序 = 配置路径排序，稳定不变。"""
    return {"default": DEFAULT_ID,
            "activities": [{"id": it["id"], "label": it["label"], "dir": it["activity_dir"],
                            "cfgPath": it["cfg_path"], "db": db_state(it),
                            "ended": bool(it.get("ended"))}
                           for it in ACTIVITIES.values()]}


def todo_payload():
    """**所有活动**的「到门槛 · 没复盘 · 还在投」工单（页面角标 + 弹窗）。

    为什么在服务端算：页面一次只加载一个活动（`/api/perf` 按 `?activity=` 给），
    「所有活动合计」只有服务端知道谁是全部活动。
    规则本体在 `perf_payload.todo_rows()`——与 `/api/perf` 共用同一套判定
    （`judging.py`），不在页面里另抄一份（口径抄第二遍迟早跟第一份走散）。
    算不出来的活动（库里还没数据 / YAML 坏了）**跳过并打一行**，不让一个活动拖垮整份清单。

    ⚠ 缓存（2026-10-09 修）：**取数正在跑的时候不吃缓存、也不写缓存**——那一刻库是
    "只有一部分活动是新数"的样子，缓存了会给页面看半分钟旧清单（页面角标显示 1、
    表格里明明有三条，就是这么来的）。取数线程每跑完一个活动会 `invalidate_todo()`。
    """
    now = time.time()
    running = running_activity() is not None
    if not running and TODO_CACHE["payload"] is not None and now - TODO_CACHE["at"] < TODO_TTL:
        return TODO_CACHE["payload"]
    items = []
    for item in ACTIVITIES.values():
        try:
            conn = perf_db.connect(DB_PATH)
            try:
                if not perf_db.days(conn, item["id"]):
                    continue
                rows = pp.todo_rows(pp.build_payload(item["cfg"], conn,
                                                     config_path=item["cfg_path"]))
            finally:
                conn.close()
        except Exception as e:
            print("  ! 待复盘清单：%s 跳过（%s）" % (item["id"], e), flush=True)
            continue
        items.extend(rows)
    # 攒得最满的排前面（曝光 ÷ 门槛），同样满就看工单名——顺序稳定，页面不用再排
    items.sort(key=lambda r: (-(r["exposure"] / r["threshold"]) if r["threshold"] else 0, r["task"]))
    out = {"count": len(items), "items": items,
           "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    if not running:                      # 取数中途的清单不进缓存（下一问重算就是新的）
        TODO_CACHE["at"], TODO_CACHE["payload"] = now, out
    return out


def auto_action(item, now=None):
    """自动刷新现在该干什么：`full`（还没取过数）/ `today`（刷今天）/ `None`（还没到时候）。

    - **今天没取过数** → 先跑一次「取数」：默认区间补到昨天，把昨天的终值固定下来（一天一次）；
    - 之后按 `AUTO["minutes"]` 的间隔刷「今天」的实时数（随时可点的那种，不落流水）；
    - 到没到点看 `AUTO["at"]`（**本活动上次自动跑的时刻**）——手动点过不该让自动刷新停摆；
    - **活动收尾**（根下有 `已结束.md`）→ 只在「收尾日 + 2 天」补数窗口内继续自动补，
      过了窗口不再自动刷新（2026-10-12）；
    - `AUTO["minutes"] = 0` = 关掉。
    """
    if not AUTO["minutes"] or fetch_stopped(item):
        return None
    if not today_fetched(item):
        return "full"
    last = AUTO["at"].get(item["id"])
    now = now or datetime.datetime.now()
    if last and (now - last) < datetime.timedelta(minutes=AUTO["minutes"]):
        return None
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
    """真正跑一次取数：`today`＝只查今天（不落流水）/ `full`＝默认区间补到昨天（落流水）。"""
    args = (item["cfg"], str(item["cfg_path"]), str(DB_PATH))
    if mode == "today":
        today = datetime.date.today().isoformat()
        fetch_mod.run(*args, date_from=today, date_to=today, no_archive=True,
                      note=fetch_note(item["id"]), browser=BROWSER)
    else:
        fetch_mod.run(*args, note=fetch_note(item["id"]), browser=BROWSER)


def fetch_worker():
    """取数线程：**独占**那只常驻浏览器，任务从队列里来（playwright 同步接口不能跨线程）。

    起服务时就把浏览器拉起来（用户要的：双击 start.bat 就起、关窗口才关）；拉不起来也不算完蛋——
    第一次点刷新会再试一次，出过错的浏览器不留着，直接扔掉重开。
    """
    global BROWSER
    BROWSER = fetch_mod.Browser()
    try:
        BROWSER.start()
        print("  浏览器：已就绪（常驻；刷新 / 取数都复用它，关窗口才关）", flush=True)
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
            st["snapshot"] = last_fetch(item)
        except Exception as e:
            st["ok"] = False
            st["error"] = fetch_error(e)
            BROWSER.close()                    # 出过错的浏览器不留：下一次重开一只
            traceback.print_exc()              # 详细堆栈打到服务窗口，方便回头查
        finally:
            st["running"] = False
            st["finished"] = datetime.datetime.now().strftime("%H:%M:%S")
            invalidate_todo()          # 新数进库 → 待复盘清单作废（角标别停在旧数字上）
    BROWSER.close()
    print("  浏览器：已关闭", flush=True)


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
            conn = perf_db.connect(DB_PATH)
            try:
                if not perf_db.days(conn, item["id"]):
                    self._json(503, {"activity": item["id"],
                                     "error": "台账库里还没有这个活动的数据（%s），"
                                              "点右上角「取数」跑一次 fetch_perf.py" % item["label"]})
                    return
                self._json(200, pp.build_payload(item["cfg"], conn, config_path=item["cfg_path"]))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None,
                    help="只登记这一个整活动 YAML（不给就登记 activities/*/配置/*.yaml 下的全部活动）")
    ap.add_argument("--db", default=perf_db.DEFAULT_DB, help="台账库路径（默认 activities/_db/投放数据.db）")
    ap.add_argument("--port", type=int, default=8770, help="监听端口（默认 8770）")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认只本机；0.0.0.0 = 同局域网可访问）")
    ap.add_argument("--auto", type=int, default=30,
                    help="自动刷新间隔（分钟；默认 30，**给 0 就关掉**）。每天第一次先跑一次「取数」把昨天固定下来")
    a = ap.parse_args()

    global DB_PATH, DEFAULT_ID
    DB_PATH = a.db
    AUTO["minutes"] = max(0, int(a.auto))
    skipped = []                           # 非整活动 YAML（活动定义 / 判定门槛 / *.thresholds …）的跳过明细
    try:
        found = campaign_mod.discover(REPO / "activities", only=a.config,
                                      log=skipped.append)   # 先收着，等标题打完再总结成一行
    except Exception as e:
        raise SystemExit("活动登记失败：%s" % e)
    if not found:
        raise SystemExit("没找到活动配置（activities/*/配置/*.yaml），请用 --config 指定")

    perf_db.connect(DB_PATH).close()        # 库不存在就建空库；页面上点「取数」即可有数据
    for it in found:
        d = Path(it["activity_dir"]) / "数据"
        it["data_root"] = str(d) if d.is_dir() else None
        it["ended"] = (Path(it["activity_dir"]) / ENDED_MARKER).is_file()
        it["endedDay"] = ended_day(it["activity_dir"]) if it["ended"] else None
        ACTIVITIES[it["id"]] = it
        FETCH[it["id"]] = new_fetch_state()
    # 默认活动优先挑「库里有数据的那个」：新活动刚建、还没取过数时，一打开就是个空页面
    DEFAULT_ID = next((it["id"] for it in found if db_state(it)["days"]), found[0]["id"])

    print("看板服务已启动（只读；关掉这个窗口或 Ctrl+C 就停）：", flush=True)
    print("  台账：%s" % DB_PATH, flush=True)
    for it in found:
        st = db_state(it)
        if not it.get("ended"):
            tail = ""
        elif fetch_stopped(it):
            tail = "（已收尾：不再自动取数）"
        else:
            tail = "（已收尾：自动补数到 %s）" % ended_until(it)
        print("  活动：%s（%s）—— 库内 %d 天，%s ~ %s%s%s"
              % (it["label"], it["id"], st["days"], st["first"] or "—", st["last"] or "—",
                 "（默认）" if it["id"] == DEFAULT_ID else "", tail), flush=True)
    if skipped:                             # 一行说完：别把 6 行绝对路径糊在标题前面
        names = sorted({Path(s[3:].split("：", 1)[0].strip()).name
                        for s in skipped if s.startswith("跳过 ")})
        print("  跳过：%d 个非整活动 YAML（%s）——只登记整活动 YAML"
              % (len(skipped), "、".join(names) or "明细见日志"), flush=True)
    print("  打开：http://%s:%d/    取数流水落 activities/{活动名}/数据/" % (a.host, a.port), flush=True)
    print("  接口：/api/activities、/api/perf、/api/snapshots、/api/fetch/status、POST /api/fetch"
          "（都带 ?activity=…）；/api/todo（跨活动，不带）", flush=True)
    print("  取数：常驻浏览器（起一只反复用；跨活动串行；关窗口时一起关）｜自动刷新：%s"
          % ("每 %d 分钟一次（每天第一次先「取数」固定昨天）" % AUTO["minutes"]
             if AUTO["minutes"] else "已关闭（--auto 0）"), flush=True)
    print("  " + "─" * 52 + "（下面只打：取数结果 / 自动刷新 / 出错）", flush=True)
    # 端口**先绑上、再起浏览器**（2026-10-12）：绑不上就直接退出——绝不能在端口被占的情况下
    # 还去起那只常驻浏览器，它会抢同一个 `.browser-profile`，把正在跑的那个看板搞成"浏览器起不来"。
    try:
        server = BoardServer((a.host, a.port), Handler)
    except OSError as e:
        raise SystemExit("  起不来：%s:%d 已经被占用——多半是**已经有一个看板在跑**"
                         "（去关掉那个窗口 / 结束那个进程；一个登录 profile 同时只能被一个进程用）。\n"
                         "  原始报错：%s" % (a.host, a.port, e))
    worker = threading.Thread(target=fetch_worker, name="fetch", daemon=True)
    worker.start()                 # 浏览器在它里面起来（起不来也不挡看板）
    threading.Thread(target=auto_worker, name="auto", daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  收到退出：关掉常驻浏览器，收工 …", flush=True)
    finally:
        JOBS.put(None)             # 让取数线程收工（它在里面关浏览器）
        worker.join(timeout=10)


if __name__ == "__main__":
    main()
