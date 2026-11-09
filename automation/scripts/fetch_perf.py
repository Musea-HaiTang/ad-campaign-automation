# -*- coding: utf-8 -*-
"""取数（只读查询）：把后台投放数据同步到数据库 v2。

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

只落一处：`activities/_db/投放数据.db`。按天事实按 (工单, 日期) upsert；
资源读数每次取数追加一条；每次取数写一条 `fetch_run`。不再生成 CSV 流水。

两种粒度口径不同，别混着算：
  - 按天事实：一天一行，**昨天及以前是终值、今天还没走完**（看板会把今天标出来）。
  - 资源读数：一个资源一条读数，是该任务整个投放期**到取数这一刻**的累计值
    （后台那个接口不认日期参数）；要看某段时间各涨了多少，拿两条读数做差。

用法:
    python -u automation/scripts/fetch_perf.py --activity {任务组名}
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
import datetime
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import browser_broker as broker  # noqa: E402
import workspace_repo  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API = "https://csdn-distadmin.csdn.net/admin"
HDR = {"Content-Type": "application/json", "Accept": "application/json"}
PAGE_SIZE = 100


class PermanentFetchError(RuntimeError):
    """不修正配置或后台状态就不会成功的取数错误。"""


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


def query_tasks(api, task_group_name, day=None, active_only=False):
    """查任务列表；给了 day 就是"那一天的业务发生时间"，不给就是任务组全量。"""
    body = {
        "id": "", "taskName": "", "userGroupId": "", "taskGroupId": "",
        "taskGroupName": task_group_name, "channelId": [],
        "workStatus": "1" if active_only else "", "stage": "",
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
        raise PermanentFetchError(
            "后台查不到任务组 %r 下的任何任务（任务组名对不对？）" % task_group_name)
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


def fetch_day_rows(api, task_group_name, day, active_only=False):
    """某一天的工单级数据；那天没数据就返回空表。"""
    rows = []
    for t in query_tasks(api, task_group_name, day, active_only=active_only):
        rows.append([day, str(t.get("id", "")), t.get("taskName") or "",
                     status_text(t.get("workStatus")), t.get("exposure", ""),
                     t.get("click", ""), t.get("loginExposure", ""), t.get("loginClick", "")])
    return rows


def status_text(code):
    """后台的 workStatus 是**字符串**（"4" / "1"）。

    真机核对：`"0"` 显示「未审核」，`"4"` 显示「下线」，`"1"` 显示「进行中」。
    没见过的值原样带出来，不猜。
    """
    try:
        return {0: "未审核", 1: "进行中", 4: "下线"}.get(int(code), str(code))
    except (TypeError, ValueError):
        return str(code)


def single_resource_map(v2_db_path, activity_key):
    """单资源工单：**工单名 → 那条复用的资源名**。

    2026-10-13：这种工单的资源级数据后台不给（它按"实验组"返回），只能用工单级累计补读数；
    但读数上的**资源名得是真的**——看板「三套文案」那张卡是按资源名去查文案原文的。
    映射直接查 v2 的 `bucket_batch` + `creative`，不读历史 YAML。
    """
    conn = workspace_repo.connect(v2_db_path)
    try:
        activity = workspace_repo.get_activity(conn, activity_key)
        if activity is None:
            return {}
        return workspace_repo.single_resource_map(conn, activity["id"])
    finally:
        conn.close()


def _v2_slot(label, used, resource_id):
    text = str(label or "")
    preferred = (
        "experiment1" if ("实验组1" in text or "实验1" in text) else
        "experiment2" if ("实验组2" in text or "实验2" in text) else
        "control" if "对照" in text else None
    )
    if preferred and preferred not in used:
        return preferred
    if not resource_id and "single" not in used:
        return "single"
    return next((x for x in ("control", "experiment1", "experiment2", "single")
                 if x not in used), None)


def sync_v2(v2_db_path, activity_key, tasks, day_rows, res_rows,
            start, end, mode, fetched_at):
    """把一次已成功取回的数据同步到数据库 v2。"""
    conn = workspace_repo.connect(v2_db_path)
    try:
        activity = workspace_repo.get_activity(conn, activity_key)
        if activity is None:
            raise RuntimeError("数据库里没有活动：%s" % activity_key)
        active_task_ids = {
            str(task["id"]) for task in tasks if task.get("state") == "进行中"
        }
        stored_day_rows = [
            row for row in day_rows if str(row[1]) in active_task_ids
        ]
        stored_res_rows = [
            row for row in res_rows if str(row[0]) in active_task_ids
        ]
        all_days = sorted({row[0] for row in stored_day_rows if row[0]})
        started_on = all_days[0] if all_days else start
        buckets = {
            bucket["bucket_key"]: bucket
            for bucket in workspace_repo.list_buckets(conn, activity["id"])
        }

        today = datetime.date.today().isoformat()
        scope = "today" if (
            "今天" in str(mode) or "刷新" in str(mode) or
            (start == end == today)
        ) else "full"
        with conn:
            cur = conn.execute(
                "INSERT INTO fetch_run(activity_id, scope, triggered_by, requested_from, "
                "requested_to, started_at, finished_at, status, returned_days, "
                "total_exposure, total_click) VALUES(?,?,?,?,?,?,?,'ok',?,?,?)",
                (activity["id"], scope, "system", start, end, fetched_at, fetched_at,
                 len(all_days), sum(_int(r[4]) for r in stored_day_rows),
                 sum(_int(r[5]) for r in stored_day_rows)),
            )
        fetch_id = cur.lastrowid

        batch_by_task = {}
        for task in tasks:
            task_id = str(task["id"])
            row = conn.execute(
                "SELECT * FROM bucket_batch WHERE task_id=?", (task_id,)
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT bb.* FROM bucket_batch bb JOIN bucket b ON b.id=bb.bucket_id "
                    "WHERE b.activity_id=? AND bb.task_name=? "
                    "ORDER BY bb.batch_no DESC LIMIT 1",
                    (activity["id"], task.get("name") or ""),
                ).fetchone()
            if row is None:
                matches = [
                    (key, bucket) for key, bucket in buckets.items()
                    if bucket["display_name"] in str(task.get("name") or "")
                ]
                if len(matches) != 1:
                    raise RuntimeError("v2 无法判断工单属于哪个桶：%s" % task.get("name"))
                bucket = matches[0][1]
                task_days = sorted(r[0] for r in day_rows if str(r[1]) == task_id)
                status = "running" if task.get("state") == "进行中" else "closed"
                row = workspace_repo.create_bucket_batch(
                    conn, bucket["id"], task_days[0] if task_days else started_on,
                    change_reason="取数发现未登记工单", created_by="system", status=status,
                )
                with conn:
                    conn.execute(
                        "UPDATE bucket_batch SET task_id=?, task_name=?, task_state=? WHERE id=?",
                        (task_id, task.get("name") or "", task.get("state") or "", row["id"]),
                    )
                row = workspace_repo.get_bucket_batch(conn, row["id"])
            else:
                with conn:
                    conn.execute(
                        "UPDATE bucket_batch SET task_id=?, task_name=?, task_state=? WHERE id=?",
                        (task_id, task.get("name") or row["task_name"],
                         task.get("state") or "", row["id"]),
                    )
                row = workspace_repo.get_bucket_batch(conn, row["id"])
            batch_by_task[task_id] = row

        creative_by_key = {}
        for row in stored_res_rows:
            task_id = str(row[0])
            batch = batch_by_task.get(task_id)
            if batch is None:
                raise RuntimeError("v2 资源读数没有对应工单：%s" % task_id)
            resource_id = str(row[2] or "")
            resource_name = str(row[4] or "")
            creative = conn.execute(
                "SELECT * FROM creative WHERE batch_id=? AND resource_id=? LIMIT 1",
                (batch["id"], resource_id),
            ).fetchone() if resource_id else None
            if creative is None and resource_name:
                creative = conn.execute(
                    "SELECT * FROM creative WHERE batch_id=? AND resource_name=? LIMIT 1",
                    (batch["id"], resource_name),
                ).fetchone()
            if creative is None:
                used = {r["slot"] for r in conn.execute(
                    "SELECT slot FROM creative WHERE batch_id=?", (batch["id"],)
                )}
                slot = _v2_slot(row[3], used, resource_id)
                if slot is None:
                    raise RuntimeError("v2 工单资源槽位已满：%s" % batch["task_name"])
                creative = workspace_repo.add_creative(
                    conn, batch["id"], resource_id, resource_name,
                    copy_id=resource_name or resource_id or task_id,
                    title="", summary="", angle_key="", style_key="",
                    slot=slot, weight_pct=0, status="running",
                )
            creative_by_key[(task_id, resource_id or resource_name)] = creative

        for row in stored_day_rows:
            task_id = str(row[1])
            batch = batch_by_task.get(task_id)
            if batch is None:
                raise RuntimeError("v2 按天数据没有对应工单：%s" % task_id)
            workspace_repo.upsert_daily_metric(
                conn, batch["id"], row[0], _int(row[4]), _int(row[5]),
                _int(row[6]), _int(row[7]), fetch_id,
            )

        for row in stored_res_rows:
            task_id = str(row[0])
            batch = batch_by_task[task_id]
            resource_id = str(row[2] or "")
            resource_name = str(row[4] or "")
            creative = creative_by_key.get((task_id, resource_id or resource_name))
            if creative is None:
                creative = conn.execute(
                    "SELECT * FROM creative WHERE batch_id=? AND resource_name=? LIMIT 1",
                    (batch["id"], resource_name),
                ).fetchone()
            if creative is None:
                raise RuntimeError("v2 资源读数没有对应文案：%s / %s" %
                                   (batch["task_name"], resource_name))
            workspace_repo.add_resource_reading(
                conn, batch["id"], creative["id"], fetch_id, fetched_at,
                _int(row[5]), _int(row[6]),
            )
        return {
            "activity_id": activity["id"],
            "fetch_run_id": fetch_id,
            "daily_metrics": len(stored_day_rows),
            "resource_readings": len(stored_res_rows),
        }
    finally:
        conn.close()


def fetch_resource_rows(api, tasks, task_group=None, single_res=None):
    """资源级（对照/实验1/实验2）：一个任务一次请求。

    ⚠ 这个接口**不认日期参数**（真机试过 startDate/businessHappen/startTime 都不变），
    返回的是该任务整个投放期到此刻的累计值——所以它是"累计快照"，不是按天数据。
    `tasks` 用统一形状 [{"id","name","state"}]（见 `tasks_from_day_rows` / `group_tasks`）。

    2026-10-13 加兜底（起因：KIRO D 桶转长期单后看板上那条一直是 0）：**AB测试=否 的单资源工单**，
    后台这个接口是按"实验组"给的，它没有实验组 → 真机返回 `{"total": 0, "list": []}`，
    于是这条工单在判定 / 看板上等于不存在（**按天事实其实是好的**，只是没人读它）。
    这类工单改从**工单级全量查询**取累计——不给日期时返回的就是累计值（真机核对过：长投 2363/1、
    A-7 4141/6，与看板一致）——补一条单槽位读数。兜底那次查询只在真碰上时打一次。
    `single_res`（工单名 → 那条复用资源名，见 `single_resource_map`）用来给这条读数写**真资源名**：
    看板的「三套文案」是按资源名去索引文案原文的，写成工单名就只剩名字、看不到标题/摘要。
    """
    rows = []
    cum = None                      # {任务 id: (曝光, 点击)}；需要兜底时才查（1 次请求）
    # 排序：任务按 id 升序（测试工单 id 更大，自然排到最后），任务内按资源 id 升序（= 对照/实验1/实验2）
    for t in sorted(tasks, key=lambda x: x.get("id") or 0):
        task_id, task_name = t.get("id"), t.get("name") or ""
        try:
            data = call(api, "GET", "/tTaskInfo/creativeDataByTaskId?taskId=%s" % task_id) or {}
        except Exception as e:
            log("      ⚠ 任务 %s 的资源级取不到：%s" % (task_id, e))
            continue
        items = data.get("list") or []
        if not items and task_group:
            if cum is None:
                cum = {str(x.get("id")): (x.get("exposure"), x.get("click"))
                       for x in query_tasks(api, task_group)}
            e, c = cum.get(str(task_id), (None, None))
            if e is not None:
                res_name = (single_res or {}).get(task_name) or task_name
                log("      · %s：资源级返回空（单资源 / 长期单）→ 用**工单级累计** %s / %s 补一条读数"
                    % (task_name, e, c))
                rows.append([str(task_id), task_name, "", "对照组", res_name, str(e), str(c)])
                continue
        for it in sorted(items, key=lambda x: x.get("resourceId") or 0):
            rows.append([str(task_id), task_name, str(it.get("resourceId", "")),
                         it.get("experimentName") or "", it.get("resourceName") or "",
                         str(it.get("exposure", "")), str(it.get("click", ""))])
    return rows


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
    """取数用的浏览器连接：**挂到公共浏览器上**（`browser_broker`），不自己起浏览器。

    - 命令行跑一次：`with Browser() as b: …`（开 → 用 → 关）。
    - **看板服务（`web/app.py`）把它常驻**（2026-09-24 用户定）：双击 `web/start.bat` 起服务时挂上去，
      之后每次「刷新 / 取数」都复用同一条连接——省掉每次 ≈1.7 秒的起/关浏览器开销。

    ⚠ 公共浏览器是**独立进程**（2026-10-16 用户定）：本类只是"挂上去的一个连接"，`close()` 只断开
      连接、**不关浏览器**（关了会把看板、建任务脚本一起带断）。以前"一个登录 profile 只能被一个
      进程用 → 开建任务的浏览器就把看板挤掉"的问题就此消失。
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
        """挂上去（已经挂着就直接复用；连接断了就重挂）。"""
        if self._ctx is not None:
            try:
                self._ctx.pages            # 探一下：浏览器被重启 / 崩了这里会抛
                return self._ctx
            except Exception:
                self.close()               # 连接已死，扔掉重挂
        broker.ensure("headed" if self.headed else "headless")
        self._pw = sync_playwright().start()
        try:
            self._ctx = broker.connect(self._pw)
        except Exception as e:
            self.close()          # 别留半截状态：失败就当没挂过
            raise RuntimeError(
                "%s\n  挂不上公共浏览器（CDP 127.0.0.1:%d）。多半是登录态过期——跑一次"
                " automation/scripts/wait_login.py 重新登录（**不用关看板**）；"
                "还是不行就 `python automation/scripts/browser_broker.py --status` 看它怎么了。"
                % (str(e).strip().splitlines()[0], broker.PORT)
            ) from e
        return self._ctx

    def close(self):
        """**断开连接**（不是关浏览器——它是公共的，还归看板/脚本用）；本来就没挂也不报错。"""
        try:
            if self._pw is not None:
                self._pw.stop()        # 只停 playwright：一停就断开 CDP，浏览器自己活着
        except Exception:
            pass
        self._pw = self._ctx = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()


def collect(ctx, task_group, days, known_tasks=0, note=log, single_res=None,
            active_only=False):
    """取数（**网络部分**，不落盘）：按天逐日查 + 资源级只查在投的工单。

    `active_only=True` 只用于今天实时刷新：后台查询直接限定进行中，
    不下发下线工单，也不在空结果时补查任务组全量。

    返回 (tasks, day_rows, res_rows, empty_days)。落库/落流水在 `persist()`。
    """
    api = ctx.request
    note("1/3 按天取数（%d 天，一天一次查询）…" % len(days))
    day_rows, empty_days = [], []
    for i, day in enumerate(days, start=1):
        rows = fetch_day_rows(api, task_group, day, active_only=active_only)
        if rows:
            day_rows.extend(rows)
            note("      [%d/%d] %s：%d 个任务" % (i, len(days), day, len(rows)))
        else:
            empty_days.append(day)
            note("      [%d/%d] %s：无数据" % (i, len(days), day))

    # 工单清单就来自按天数据（同一批接口、同样的字段），不用再单独查一次任务组；
    # 只有「按天返回的工单比库里知道的少」（如补历史那天还没建的工单）才补查全量。
    tasks = tasks_from_day_rows(day_rows)
    if not tasks and active_only:
        note("      今天没有进行中的工单，本次无需取数")
        return [], [], [], empty_days
    if not active_only and len(tasks) < known_tasks:
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
    res_rows = fetch_resource_rows(api, to_read, task_group=task_group, single_res=single_res)
    note("      %d 行" % len(res_rows))
    return tasks, day_rows, res_rows, empty_days


def persist(v2_db_path, task_group, tasks, day_rows, res_rows, start, end,
            empty_days=(), label="", mode="", note=log):
    """把一次成功取数写入数据库 v2，并把摘要打到日志。"""
    now = datetime.datetime.now()
    fetched_at = now.strftime("%Y-%m-%d %H:%M:%S")
    span = sorted({r[0] for r in day_rows})
    report = sync_v2(
        v2_db_path, task_group, tasks, day_rows, res_rows,
        start, end, mode, fetched_at,
    )
    note("3/3 入库：按天 %d · 资源读数 %d · fetch_run %d"
         % (report["daily_metrics"], report["resource_readings"], report["fetch_run_id"]))

    note("---- 工单 × 日期 ----")
    i_name, i_exp, i_clk = 2, 4, 5
    for r in day_rows:
        note("  %s  %-46s 曝光 %6s | 点击 %4s | 登录曝光 %6s"
             % (r[0], str(r[i_name])[:46], r[i_exp], r[i_clk], r[6]))
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

    note("取数记录：数据库 v2（fetch_run #%d）" % report["fetch_run_id"])


def run(activity_key, v2_db_path=None, date_from=None, date_to=None, label="",
        headed=False, note=log, browser=None):
    """完整取一次数——**命令行和看板服务（`web/app.py`）都走这一条**。

    `browser` 给了就复用它那只常驻浏览器（看板服务传进来）；没给就自己开一只、跑完关掉（命令行）。
    成功返回一句摘要；失败抛异常（**不落任何盘**，见文件头"只读边界"）。
    """
    v2_db_path = v2_db_path or workspace_repo.V2_DB
    conn = workspace_repo.connect(v2_db_path)
    try:
        activity = workspace_repo.get_activity(conn, activity_key)
        if activity is None:
            raise RuntimeError("数据库里没有活动：%s" % activity_key)
        today = datetime.date.today().isoformat()
        last = workspace_repo.activity_last_day(conn, activity["id"])
        start, end, mode = plan_days(date_from, date_to, last,
                                     activity["started_on"], today)
        if end < start:
            raise RuntimeError("结束日 %s 早于起始日 %s（日期填反了）" % (end, start))
        days = day_range(start, end)

        note("取数：%s | 区间：%s ~ %s（%d 天）| 模式：%s | 标签：%s"
             % (activity["display_name"], start, end, len(days), mode, label or "-"))
        note("      数据库：%s（本活动 %d 个批次%s）"
             % (v2_db_path, workspace_repo.count_bucket_batches(conn, activity["id"]),
                "，数据到 %s" % last if last else "，空库 → 全量回填"))

        own = browser is None                                   # 自己开的就自己关
        by = browser if browser is not None else Browser(headed=headed)
        by.start()                                              # 常驻的那只：没起就起、起着就复用
        try:
            active_only = start == end == today
            tasks, day_rows, res_rows, empty_days = collect(
                by.ctx, activity_key, days,
                workspace_repo.count_bucket_batches(conn, activity["id"]), note,
                single_res=workspace_repo.single_resource_map(conn, activity["id"]),
                active_only=active_only)
        finally:
            if own:
                by.close()

        if not day_rows:
            if active_only:
                return "无进行中工单，本次未取数"
            raise RuntimeError("区间内所有日期都没有数据（%s ~ %s）" % (start, end))

        persist(v2_db_path, activity_key, tasks, day_rows, res_rows, start, end,
                empty_days=empty_days, label=label, mode=mode, note=note)
        return "取数完成（按天 %d 行 %s ~ %s；资源级累计 %d 行）" % (
            len(day_rows), start, end, len(res_rows))
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--activity", required=True, help="数据库里的任务组名")
    ap.add_argument("--from", dest="date_from", default=None, help="起始日 YYYY-MM-DD（默认：库里最近有数据那天）")
    ap.add_argument("--to", dest="date_to", default=None,
                    help="结束日 YYYY-MM-DD（默认昨天；要今天那半截：--from 今天 --to 今天）")
    ap.add_argument("--label", default="", help="这次取数对应哪次调整，如「调整前」")
    ap.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    ap.add_argument("--v2-db", default=workspace_repo.V2_DB, help="数据库 v2 路径")
    args = ap.parse_args()

    try:
        summary = run(args.activity, args.v2_db, args.date_from, args.date_to,
                      args.label, args.headed, log)
        log("RESULT: %s" % summary)
    except Exception as e:
        # 只读、失败不落盘：宁可什么都没有，也不要一份半截的假数据
        log("  ✗ %s" % e)
        log("RESULT: 取数失败（没有生成任何快照）")
        sys.exit(1)


if __name__ == "__main__":
    main()
