# -*- coding: utf-8 -*-
"""取数（只读快照）：把后台的投放数据抓成一份只增不改的快照。

数据全部来自**只读查询接口**，不碰后台的「导出」模块：
  1. `POST /tTaskInfo/taskPageList`（按**每天**查一次）→ 工单 × 日期的曝光/点击/登录曝光/登录点击
     ——返回的行里带工单名 / 状态 / taskGroupId，**它就是本组当前的工单清单**，所以不再单独查一次任务组
     （2026-09-24 起：省掉一次请求 ≈0.5s；只有"按天没把工单返回来"，例如补历史那天还没建的工单，
      才补查一次任务组全量）
  2. `GET  /tTaskInfo/creativeDataByTaskId?taskId=…` → 任务 × 资源的累计（对照/实验1/实验2）
     ——**只查状态＝进行中的工单**：下线工单的读数不再累计（多轮上下线会留一堆带残留数据的
      下线工单，用户 2026-09-24 定"就只刷在投的"）

为什么不用后台的「按天导出」excel（2026-09-16 定，全部真机踩过）：
  - **导出模块会整块失效**：那天 `/admin/export/*` 全部返回 code=400600 无权限，
    页面自己提示「无权访问，请重新登录」，重新登录才恢复；
  - **后端按参数复用旧导出**：同样的 `9/14~9/15`，今天提交会拿回**昨天上午**生成的文件，
    那时 9/15 才刚开始 —— 快照里 9/15 合计 267，实际 1951，差 7 倍且**静默**；
  - 导出是异步任务（要轮询等）、还有提交频率限制（连提几次报「提交过于频繁」）；
  - 而我们本来就要走 `creativeDataByTaskId` 拿资源级，顺路把工单级也走接口即可，
    还能多拿两列导出没有的 **登录曝光 / 登录点击**。

代价（明说）：按天数据要**一天查一次**，N 天 = N 次请求（30 天约 30 次）；资源级**每个在投工单一次**
（本活动现在 5 条，远少于"全组 26 个工单逐个查"）。

落在两处（2026-09-20 改成「库 + 取数流水」）：

  ① 台账库（**唯一真相**，看板只读它）：`activities/_db/投放数据.db`（见 `perf_db.py`）
     - 按天事实按 (工单, 日期) upsert：历史是终值、写了不动；**今天那行每次刷新覆盖**。
     - 资源读数每次取数追加一条（资源级接口给的是累计值，天然是读数序列）。
  ② 取数流水（**原始存档**，可 diff）：`activities/{活动名}/数据/{YYYY-MM-DD_HHMM}[_{标签}]/`
     落这次**实际取回来**的那几天的 CSV —— 它是"我们哪天向后台要过什么"的凭据，
     不再是看板的数据源。所以一天取几次都无所谓（以前"一天只留一份"的规矩已退休）。

两种粒度口径不同，别混着算：
  - 按天事实：一天一行，**昨天及以前是终值、今天还没走完**（看板会把今天标出来）。
  - 资源读数：一个资源一条读数，是该任务整个投放期**到取数这一刻**的累计值
    （后台那个接口不认日期参数）；要看某段时间各涨了多少，拿两条读数做差。

用法:
    python -u automation/scripts/fetch_perf.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml
    # 默认（＝看板上的「取数」）：库里最近有数据那天 ~ **昨天**，把昨天的数固定下来
    #   （昨天一天一次就够，它不会再变）；空库则从活动投放开始日全量回填
    ... --from 2026-09-20 --to 2026-09-20      # 只取今天 = 看板上「刷新」干的事（今天的实时数）
    ... --from 2026-09-14 --to 2026-09-15      # 显式区间：补历史 / 修复后台改过的数（幂等）
    ... --label 调整前                          # 只进流水文件夹名
    ... --headed                               # 想看浏览器时加

⚠ 只读边界：只调用上面三个查询接口，绝不创建、修改、暂停后台任何投放对象。
⚠ 导出结束日默认「昨天」：当天的数据只有几小时，会把曲线拽下去。
"""
import argparse
import csv
import datetime
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"D:\playwright-browsers")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign as campaign_mod  # noqa: E402
import perf_db  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILE = os.path.join(REPO, ".browser-profile")
API = "https://csdn-distadmin.csdn.net/admin"
HDR = {"Content-Type": "application/json", "Accept": "application/json"}
PAGE_SIZE = 100
DAY_COLUMNS = ["曝光时间", "任务ID", "任务名称", "状态", "曝光", "点击", "登录曝光", "登录点击"]
RES_COLUMNS = ["任务ID", "任务名称", "资源ID", "组别", "资源名称", "曝光次数", "点击次数"]
README = """# 数据（取数流水 + 台账库）

真相在**台账库**里，这里放的是**原始存档**（2026-09-20 起）。

| 位置 | 是什么 |
|---|---|
| `../_db/投放数据.db`（SQLite） | **唯一真相**：按天事实 + 资源读数 + 工单状态，看板只读它 |
| `{YYYY-MM-DD_HHMM}[_标签]/投放数据.csv` | 这次**实际取回来**的那几天的工单级数据（原始返回） |
| `{YYYY-MM-DD_HHMM}[_标签]/资源级累计.csv` | 这次取数那一刻的资源级累计值（读数） |
| `看板/*.html` | 由 `visualize_perf.py` 渲染的单文件看板（可随时重渲染，不是取数产出） |

## 口径

- 数据来自后台的**只读查询接口**（任务列表 + 任务资源明细），**以后台为准**。
- **按天事实**：一天一行，只含有数据出现的日期；**昨天及以前是终值，今天还没走完**
  （看板会把今天标出来，"日均曝光"等判定按完整日算）。
- **资源级**：一个资源一行，是**累计值**——覆盖该任务整个投放期到取数这一刻，所以含当天。
  想看"某段时间里三套文案各涨了多少"，拿两条读数做差。
- 取数时刻和标签在**文件夹名**里（`2026-09-20_0939`、`2026-09-20_1430_调整前`）。
  一天取几次就有几个文件夹——**它们是流水，不是"最新一份才是真相"**。
  **「刷新今天」不落流水**（数据直接进台账库，`--no-archive`），所以一天最多一份流水 = 当天的「取数」（2026-09-20 起）。
- `测试工单-火山引擎MediaKit-hang-A类…` 是 A 组的**正式口径**（正版 A 组时间设错、2026-09-14 后已无数据）：
  **分析 A 组只看这一条**（2026-09-17 用户定）；9/14 那天两条并存、数据混杂，不当基线用。
"""


def log(*a):
    print(*a, flush=True)


def decode(resp):
    """后台两种编码都见过：带 Accept: json 是 UTF-8，不带是 GBK。"""
    raw = resp.body()
    txt = raw.decode("utf-8", errors="replace")
    if "\ufffd" in txt:
        txt = raw.decode("gb18030", errors="replace")
    return txt


def call(api, method, path, payload=None):
    """统一发请求 + 拆 JSON 外壳；失败抛 RuntimeError（调用方决定怎么报）。"""
    if method == "POST":
        r = api.post(API + path, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                     headers=HDR)
    else:
        r = api.get(API + path, headers=HDR)
    txt = decode(r)
    if r.status != 200:
        raise RuntimeError("HTTP %s：%s" % (r.status, txt[:200]))
    try:
        body = json.loads(txt)
    except ValueError:
        raise RuntimeError("返回不是 JSON（可能是登录态失效，跳转了登录页）：%s" % txt[:200])
    if body.get("code") != 200:
        raise RuntimeError("接口返回 code=%s message=%s" % (body.get("code"), body.get("message")))
    return body.get("data")


def query_tasks(api, task_group_name, day=None):
    """查任务列表；给了 day 就是"那一天的业务发生时间"，不给就是任务组全量。"""
    body = {
        "id": "", "taskName": "", "userGroupId": "", "taskGroupId": "",
        "taskGroupName": task_group_name, "channelId": [], "workStatus": "", "stage": "",
        "createType": "", "channelType": "0",
        "needPage": 1, "pageNumber": 1, "pageSize": PAGE_SIZE,
    }
    if day:
        body["businessHappenStartDate"] = day + " 00:00:00"
        body["businessHappenEndDate"] = day + " 23:59:59"
    data = call(api, "POST", "/tTaskInfo/taskPageList", body) or {}
    rows = data.get("list") or []
    if data.get("total", 0) > len(rows):
        raise RuntimeError("任务数 %s 超过单页 %d 条，脚本还没做翻页——先跟人说一声再取"
                           % (data.get("total"), PAGE_SIZE))
    return rows


def group_tasks(api, task_group_name):
    """任务组全量清单（id / 名称 / 状态）——**只在兜底时用**，见 `tasks_from_day_rows`。"""
    rows = query_tasks(api, task_group_name)
    if not rows:
        raise RuntimeError("后台查不到任务组 %r 下的任何任务（任务组名对不对？）" % task_group_name)
    return [{"id": t.get("id"), "name": t.get("taskName") or "",
             "state": status_text(t.get("workStatus"))} for t in rows]


def tasks_from_day_rows(day_rows):
    """按天数据里出现过的工单 = 本组当前的工单清单（`fetch_day_rows` 已把状态翻成文字）。

    后台"按天查"返回的就是工单行，字段和"全量查"一样，所以没必要再单独查一次任务组；
    只有按天没把工单返回来（例如补历史那天还没建的工单）才回去补查全量。
    """
    seen = {}
    for r in day_rows:
        seen.setdefault(str(r[1]), {"id": r[1], "name": r[2], "state": r[3]})
    return list(seen.values())


def tasks_to_read(tasks):
    """资源级读哪些工单：**只读状态＝进行中的**（2026-09-24 用户定）。

    用户口径：刷新只刷在投的工单；**不看"今天有没有量"**——以后会有多轮上线下线，
    下线工单在"跑了大半天才下线"的那天照样有量（实测 A 类-4 今天 2591 曝光），按"有量"筛
    等于把带残留数据的下线工单又全捞回来，省不下来。所以这里只认状态。

    代价（明说）：下线工单的**累计读数**停在最后一次读到它的那一刻；**按天的数不受影响**
    （按天查询本来就是全量、每个工单都取），所以图表/表格里的曝光点击照常更新，
    只有看板「三套文案」那张卡的累计数会停在下线那一刻。
    """
    return [t for t in tasks if t["state"] == "进行中"]


def fetch_day_rows(api, task_group_name, day):
    """某一天的工单级数据；那天没数据就返回空表。"""
    rows = []
    for t in query_tasks(api, task_group_name, day):
        rows.append([day, str(t.get("id", "")), t.get("taskName") or "",
                     status_text(t.get("workStatus")), t.get("exposure", ""),
                     t.get("click", ""), t.get("loginExposure", ""), t.get("loginClick", "")])
    return rows


def status_text(code):
    """后台的 workStatus 是**字符串**（"4" / "1"）。

    真机核对：A 类 `"4"` 在后台显示「下线」，测试工单 `"1"` 显示「进行中」。
    没见过的值原样带出来，不猜。
    """
    try:
        return {1: "进行中", 4: "下线"}.get(int(code), str(code))
    except (TypeError, ValueError):
        return str(code)


def fetch_resource_rows(api, tasks):
    """资源级（对照/实验1/实验2）：一个任务一次请求。

    ⚠ 这个接口**不认日期参数**（真机试过 startDate/businessHappen/startTime 都不变），
    返回的是该任务整个投放期到此刻的累计值——所以它是"累计快照"，不是按天数据。
    `tasks` 用统一形状 [{"id","name","state"}]（见 `tasks_from_day_rows` / `group_tasks`）。
    """
    rows = []
    # 排序：任务按 id 升序（测试工单 id 更大，自然排到最后），任务内按资源 id 升序（= 对照/实验1/实验2）
    for t in sorted(tasks, key=lambda x: x.get("id") or 0):
        task_id, task_name = t.get("id"), t.get("name") or ""
        try:
            data = call(api, "GET", "/tTaskInfo/creativeDataByTaskId?taskId=%s" % task_id) or {}
        except Exception as e:
            log("      ⚠ 任务 %s 的资源级取不到：%s" % (task_id, e))
            continue
        for it in sorted(data.get("list") or [], key=lambda x: x.get("resourceId") or 0):
            rows.append([str(task_id), task_name, str(it.get("resourceId", "")),
                         it.get("experimentName") or "", it.get("resourceName") or "",
                         str(it.get("exposure", "")), str(it.get("click", ""))])
    return rows


def write_csv(columns, rows, path):
    """utf-8 带 BOM：Excel 双击打开中文不乱码。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        w.writerows(rows)


def day_range(start, end):
    d, last = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
    days = []
    while d <= last:
        days.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return days


def _int(v):
    try:
        return int(str(v).strip() or 0)
    except ValueError:
        return 0


def plan_days(date_from, date_to, last_day, campaign_start, today):
    """取数区间 + 模式。默认（＝看板上的「取数」）只补到**昨天**。

    用户 2026-09-20 的分工：**取数把"昨天"的数固定下来**（一天一次就够，昨天不会再变）；
    **今天的实时数**归看板上的「刷新」管（它单独跑 `--from 今天 --to 今天`）。

    起点取「库里最近有数据那天」是为了**自己补洞**：那天取的时候它还是半截的今天，
    隔天重取一遍才是终值；中间断过几天也不会漏。库里最后一天已经是今天（被刷新写过）时
    退回昨天，免得起点跑到终点后面。空库（首次）则从活动投放开始日全量回填。

    2026-10-12 修：**活动开投第一天**（起始日 = 今天）也要能取——这时"昨天"还没有，
    原来的「起始日 ~ 昨天」区间是反的，会抛"日期填反了"（腾讯云产品 10-12 开投当天
    每 30 分钟自动取数一次、次次失败就是这么来的）。首日就只取当天那一格。
    """
    yesterday = (datetime.date.fromisoformat(today) - datetime.timedelta(days=1)).isoformat()
    if date_from or date_to:
        return (date_from or last_day or campaign_start), (date_to or yesterday), "指定区间"
    if not last_day:
        if campaign_start > today:                 # 还没开投：别去查一段未来的空区间，说清楚就行
            raise RuntimeError("活动还没开始投放（起始日 %s，今天 %s）——开投后再取数"
                               % (campaign_start, today))
        if campaign_start > yesterday:
            return campaign_start, campaign_start, "首次回填（开投首日）"
        return campaign_start, yesterday, "首次回填"
    return min(last_day, yesterday), yesterday, "增量"


class Browser:
    """浏览器会话：playwright + 这个仓库的持久登录 profile（`REPO/.browser-profile`）。

    - 命令行跑一次：`with Browser() as b: …`（开 → 用 → 关）。
    - **看板服务（`web/app.py`）把它常驻**（2026-09-24 用户定）：双击 `web/start.bat` 起服务时开一只，
      之后每次「刷新 / 取数」都复用同一个浏览器、同一条后台连接，关窗口才关——省掉每次
      ≈1.7 秒的起/关浏览器开销。

    ⚠ **一个 profile 同时只能被一个浏览器进程用**（系统会锁 profile 文件夹），所以同一时刻只许有一只
      `Browser`；要手动跑命令行脚本、或重新登录（`wait_login.py`），先把看板窗口关掉。
    ⚠ playwright 的**同步接口不能跨线程**：谁 `start()` 的，就只能在那个线程里用（看板那边因此
      专门起了一个取数线程）。
    """

    def __init__(self, headed=False):
        self.headed = headed
        self._pw = None
        self._ctx = None

    @property
    def ctx(self):
        return self._ctx

    def start(self):
        """没开就开（已经开着就是空操作，直接复用）。"""
        if self._ctx is not None:
            return self._ctx
        try:
            self._pw = sync_playwright().start()
            self._ctx = self._pw.chromium.launch_persistent_context(
                user_data_dir=PROFILE, channel="msedge", headless=not self.headed,
                no_viewport=True, args=["--start-maximized"],
            )
        except Exception as e:
            self.close()          # 别留半截状态：失败就当没开过
            # 起不来最常见的两种原因，直接给人话，别甩一大坨 playwright 日志
            raise RuntimeError(
                "%s\n  浏览器起不来。多半是：① 看板（web/app.py）正开着——一个登录 profile 同时只能被"
                "一个进程用，先关掉那个窗口再跑命令行（或直接用看板上的「刷新 / 取数」）；"
                "② 登录态过期——跑 automation/scripts/wait_login.py 重新登录。" % str(e).strip().splitlines()[0]
            ) from e
        return self._ctx

    def close(self):
        """关浏览器 + 停 playwright；本来就没开也不报错。"""
        for closer in (lambda: self._ctx and self._ctx.close(),
                       lambda: self._pw and self._pw.stop()):
            try:
                closer()
            except Exception:
                pass
        self._pw = self._ctx = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()


def collect(ctx, task_group, days, known_tasks=0, note=log):
    """取数（**网络部分**，不落盘）：按天逐日查 + 资源级只查在投的工单。

    返回 (tasks, day_rows, res_rows, empty_days)。落库/落流水在 `persist()`。
    """
    api = ctx.request
    note("1/3 按天取数（%d 天，一天一次查询）…" % len(days))
    day_rows, empty_days = [], []
    for i, day in enumerate(days, start=1):
        rows = fetch_day_rows(api, task_group, day)
        if rows:
            day_rows.extend(rows)
            note("      [%d/%d] %s：%d 个任务" % (i, len(days), day, len(rows)))
        else:
            empty_days.append(day)
            note("      [%d/%d] %s：无数据" % (i, len(days), day))

    # 工单清单就来自按天数据（同一批接口、同样的字段），不用再单独查一次任务组；
    # 只有「按天返回的工单比库里知道的少」（如补历史那天还没建的工单）才补查全量。
    tasks = tasks_from_day_rows(day_rows)
    if len(tasks) < known_tasks:
        note("      按天只返回 %d 个工单（库里已知 %d 个）→ 补查任务组全量 …"
             % (len(tasks), known_tasks))
        tasks = group_tasks(api, task_group)
    if not tasks:
        raise RuntimeError("后台查不到任务组 %r 下的任何任务（任务组名对不对？）" % task_group)
    note("      该组下 %d 个工单" % len(tasks))

    note("2/3 取资源级累计（每个在投的工单一次查询）…")
    to_read = tasks_to_read(tasks)
    if len(to_read) < len(tasks):
        note("      跳过 %d 个不在投的工单（只停它的累计读数；按天的数照常取）"
             % (len(tasks) - len(to_read)))
    res_rows = fetch_resource_rows(api, to_read)
    note("      %d 行" % len(res_rows))
    return tasks, day_rows, res_rows, empty_days


def persist(conn, cfg, cfg_path, task_group, tasks, day_rows, res_rows, start, end,
            empty_days=(), label="", no_archive=False, note=log):
    """落盘：台账库（唯一真相）+ 取数流水（原始存档），并把这次取回的数打到日志里。"""
    activity_dir = campaign_mod.activity_dir(cfg_path)
    data_root = os.path.join(activity_dir, "数据")
    now = datetime.datetime.now()
    folder = now.strftime("%Y-%m-%d_%H%M") + (("_" + label) if label else "")
    snap_dir = os.path.join(data_root, folder)

    note("3/3 落盘（台账库 + 取数流水）…")
    fetched_at = now.strftime("%Y-%m-%d %H:%M:%S")

    # ① 台账库（唯一真相）：工单维度先落，按天事实与资源读数随后 upsert/追加
    perf_db.upsert_activity(conn, task_group, os.path.basename(activity_dir), cfg["label"])
    perf_db.upsert_tasks(conn, task_group, tasks, fetched_at)
    perf_db.upsert_daily(conn, [(str(r[1]), r[0], _int(r[4]), _int(r[5]), _int(r[6]), _int(r[7]),
                                 fetched_at) for r in day_rows])
    perf_db.add_resource_readings(conn, [(str(r[0]), str(r[2]), fetched_at, task_group, r[1], r[3],
                                          r[4], _int(r[5]), _int(r[6])) for r in res_rows])
    conn.commit()
    db_days = perf_db.days(conn, task_group)
    note("      台账：%d 条按天事实 · %d 条资源读数 · 活动共 %d 天（%s ~ %s）"
         % (len(day_rows), len(res_rows), len(db_days), db_days[0], db_days[-1]))

    # ② 取数流水（原始存档，可 diff）：落这次实际取回来的那几天
    #    no_archive（看板「刷新今天」）跳过：刷新是可重复的查询，数据已进台账库，
    #    不必一天堆一堆文件夹（用户 2026-09-20 定）
    if no_archive:
        note("      流水：--no-archive，跳过（只写台账库）")
    else:
        os.makedirs(snap_dir, exist_ok=True)
        write_csv(DAY_COLUMNS, day_rows, os.path.join(snap_dir, "投放数据.csv"))
        write_csv(RES_COLUMNS, res_rows, os.path.join(snap_dir, "资源级累计.csv"))
    if not os.path.exists(os.path.join(data_root, "README.md")):
        with open(os.path.join(data_root, "README.md"), "w", encoding="utf-8") as fh:
            fh.write(README)

    # 工单级：按天×任务打出来（含登录曝光/登录点击）
    note("---- 工单 × 日期 ----")
    i_name, i_exp, i_clk = 2, 4, 5
    for r in day_rows:
        note("  %s  %-46s 曝光 %6s | 点击 %4s | 登录曝光 %6s"
             % (r[0], str(r[i_name])[:46], r[i_exp], r[i_clk], r[6]))
    span = sorted({r[0] for r in day_rows})
    # 这行是「**本次取回**的那几天」的合计，不是看板上的合计（看板合计＝库里全部天）——写明白，别混
    note("  本次取回 %d 天（%s ~ %s）合计：曝光 %d | 点击 %d"
         % (len(span), span[0] if span else "—", span[-1] if span else "—",
            sum(int(r[i_exp] or 0) for r in day_rows),
            sum(int(r[i_clk] or 0) for r in day_rows)))
    if empty_days:
        note("  （无数据的日期：%s）" % "、".join(empty_days))

    note("---- 资源级累计（对照 / 实验1 / 实验2）----")
    for r in res_rows:
        note("  %-44s %-8s 曝光 %6s | 点击 %4s" % (str(r[1])[:44], r[3], r[5], r[6]))

    if no_archive:
        note("取数流水：未落盘（--no-archive）")
    else:
        note("取数流水目录：%s" % snap_dir)
        note("  投放数据.csv（%d 行）" % len(day_rows))
        note("  资源级累计.csv（%d 行）" % len(res_rows))


def run(cfg, cfg_path, db_path, date_from=None, date_to=None, label="", no_archive=False,
        headed=False, note=log, browser=None):
    """完整取一次数——**命令行和看板服务（`web/app.py`）都走这一条**。

    `browser` 给了就复用它那只常驻浏览器（看板服务传进来）；没给就自己开一只、跑完关掉（命令行）。
    成功返回一句摘要；失败抛异常（**不落任何盘**，见文件头"只读边界"）。
    """
    task_group = cfg["campaign"]["taskGroupName"]
    conn = perf_db.connect(db_path)
    try:
        today = datetime.date.today().isoformat()
        last = perf_db.last_day(conn, task_group)
        start, end, mode = plan_days(date_from, date_to, last,
                                     cfg["taskOrder"]["deliveryDate"]["start"], today)
        if end < start:
            raise RuntimeError("结束日 %s 早于起始日 %s（日期填反了）" % (end, start))
        days = day_range(start, end)

        note("取数：%s | 任务组：%s | 区间：%s ~ %s（%d 天）| 模式：%s | 标签：%s"
             % (cfg["label"], task_group, start, end, len(days), mode, label or "-"))
        note("      台账：%s（本活动 %s）"
             % (db_path, ("库里已有 %d 天" % len(perf_db.days(conn, task_group))) if last
                else "空库 → 全量回填"))

        own = browser is None                                   # 自己开的就自己关
        by = browser if browser is not None else Browser(headed=headed)
        by.start()                                              # 常驻的那只：没起就起、起着就复用
        try:
            tasks, day_rows, res_rows, empty_days = collect(
                by.ctx, task_group, days, len(perf_db.tasks(conn, task_group)), note)
        finally:
            if own:
                by.close()

        if not day_rows:
            raise RuntimeError("区间内所有日期都没有数据（%s ~ %s）" % (start, end))

        persist(conn, cfg, cfg_path, task_group, tasks, day_rows, res_rows, start, end,
                empty_days=empty_days, label=label, no_archive=no_archive, note=note)
        return "取数完成（按天 %d 行 %s ~ %s；资源级累计 %d 行）" % (
            len(day_rows), start, end, len(res_rows))
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="整活动 YAML")
    ap.add_argument("--from", dest="date_from", default=None, help="起始日 YYYY-MM-DD（默认：库里最近有数据那天）")
    ap.add_argument("--to", dest="date_to", default=None,
                    help="结束日 YYYY-MM-DD（默认昨天；要今天那半截：--from 今天 --to 今天）")
    ap.add_argument("--label", default="", help="这次取数对应哪次调整，如「调整前」")
    ap.add_argument("--no-archive", action="store_true",
                    help="不落取数流水（只写台账库）——看板上的「刷新今天」用它，免得一天堆一堆文件夹")
    ap.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    ap.add_argument("--db", default=perf_db.DEFAULT_DB, help="台账库路径（默认 activities/_db/投放数据.db）")
    args = ap.parse_args()

    cfg = campaign_mod.load_or_exit(args.config)
    try:
        summary = run(cfg, args.config, args.db, args.date_from, args.date_to, args.label,
                      args.no_archive, args.headed, log)
        log("RESULT: %s" % summary)
    except Exception as e:
        # 只读、失败不落盘：宁可什么都没有，也不要一份半截的假数据
        log("  ✗ %s" % e)
        log("RESULT: 取数失败（没有生成任何快照）")
        sys.exit(1)
        log("4/4 落盘（台账库 + 取数流水）…")
        fetched_at = now.strftime("%Y-%m-%d %H:%M:%S")

        # ① 台账库（唯一真相）：工单维度先落，按天事实与资源读数随后 upsert/追加
        perf_db.upsert_activity(conn, task_group, os.path.basename(activity_dir), cfg["label"])
        perf_db.upsert_tasks(conn, task_group, tasks, fetched_at)
        perf_db.upsert_daily(conn, [(str(r[1]), r[0], _int(r[4]), _int(r[5]), _int(r[6]), _int(r[7]),
                                     fetched_at) for r in day_rows])
        perf_db.add_resource_readings(conn, [(str(r[0]), str(r[2]), fetched_at, task_group, r[1], r[3],
                                              r[4], _int(r[5]), _int(r[6])) for r in res_rows])
        conn.commit()
        db_days = perf_db.days(conn, task_group)
        log("      台账：%d 条按天事实 · %d 条资源读数 · 活动共 %d 天（%s ~ %s）"
            % (len(day_rows), len(res_rows), len(db_days), db_days[0], db_days[-1]))

        # ② 取数流水（原始存档，可 diff）：落这次实际取回来的那几天
        #    --no-archive（看板「刷新今天」）跳过：刷新是可重复的查询，数据已进台账库，
        #    不必一天堆一堆文件夹（用户 2026-09-20 定）
        if args.no_archive:
            log("      流水：--no-archive，跳过（只写台账库）")
        else:
            os.makedirs(snap_dir, exist_ok=True)
            write_csv(DAY_COLUMNS, day_rows, os.path.join(snap_dir, "投放数据.csv"))
            write_csv(RES_COLUMNS, res_rows, os.path.join(snap_dir, "资源级累计.csv"))
        if not os.path.exists(os.path.join(data_root, "README.md")):
            with open(os.path.join(data_root, "README.md"), "w", encoding="utf-8") as fh:
                fh.write(README)

        # 工单级：按天×任务打出来（含登录曝光/登录点击）
        log("---- 工单 × 日期 ----")
        i_name, i_exp, i_clk = 2, 4, 5
        for r in day_rows:
            log("  %s  %-46s 曝光 %6s | 点击 %4s | 登录曝光 %6s"
                % (r[0], str(r[i_name])[:46], r[i_exp], r[i_clk], r[6]))
        span = sorted({r[0] for r in day_rows})
        # 这行是「**本次取回**的那几天」的合计，不是看板上的合计（看板合计＝库里全部天）——写明白，别混
        log("  本次取回 %d 天（%s ~ %s）合计：曝光 %d | 点击 %d"
            % (len(span), span[0] if span else "—", span[-1] if span else "—",
               sum(int(r[i_exp] or 0) for r in day_rows),
               sum(int(r[i_clk] or 0) for r in day_rows)))
        if empty_days:
            log("  （无数据的日期：%s）" % "、".join(empty_days))

        log("---- 资源级累计（对照 / 实验1 / 实验2）----")
        for r in res_rows:
            log("  %-44s %-8s 曝光 %6s | 点击 %4s" % (str(r[1])[:44], r[3], r[5], r[6]))

        if args.no_archive:
            log("取数流水：未落盘（--no-archive）")
        else:
            log("取数流水目录：%s" % snap_dir)
            log("  投放数据.csv（%d 行）" % len(day_rows))
            log("  资源级累计.csv（%d 行）" % len(res_rows))
        log("RESULT: 取数完成（按天 %d 行 %s ~ %s；资源级累计 %d 行）"
            % (len(day_rows), start, end, len(res_rows)))
    except Exception as e:
        # 只读、失败不落盘：宁可什么都没有，也不要一份半截的假数据
        log("  ✗ %s" % e)
        log("RESULT: 取数失败（没有生成任何快照）")
        sys.exit(1)


if __name__ == "__main__":
    main()
