# -*- coding: utf-8 -*-
"""看板数据装配（纯数据层，唯一实现）：**台账库 + 整活动 YAML → 看板要的 JSON**。

谁在用：
  - `visualize_perf.py`  出**数据内嵌的单文件看板**（发人 / 归档）
  - `web/app.py`         起**本地服务**，页面 `fetch /api/perf` 现拿
两边共用这里的 `build_payload()`，所以页面版和文件版数字必然一致。

数据源只有一个：`perf_db`（SQLite 台账）。**不再读快照文件夹**——快照从 2026-09-20 起
只是"取数流水"原始存档，看板不依赖它，所以一天取几次、取多窄都不会影响看板。

口径：
  - 按天事实来自 `daily` 表（一天一行：历史是终值、今天还没走完）；
  - 资源级来自 `resource_reading` 表的**最新一次读数**（累计值）；
  - 工单口径三个（`in_scope()`）：`all` 全部（含已下线）/ `investing` 只在投（状态=进行中）/
    `batch` **活动最新一批**（`currentBatch`，**不看状态**——新建工单在后台生成任务前 `workStatus` 是 `0`，
    只看 `investing` 会把当前批次整批漏掉；2026-10-08 起不再读 `判定门槛.yaml` 的 `batch`，那字段已删）。
  - **桶维度**（2026-10-08 用户定）：`bucket_view()` 把「批次 × 桶」翻成「一个桶 → 它自己的批次史」，
    每个桶有自己的 `currentBatch`（最后一次建批）/ `refBatch`（最近有量的一批），页面主表就吃它。
"""
import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign as campaign_mod  # noqa: E402
import judging  # noqa: E402
import naming  # noqa: E402
import perf_db  # noqa: E402

# 活动细则 §6 的参考基线：博客详情页底部 CTR 及格线 0.10%；「每工单 ≥30 点击再判优劣」同源
CTR_LINE = 0.10
CLICK_FLOOR = 30
GROUP_ORDER = ["对照组", "实验组1", "实验组2"]
BUCKET_COLORS = ["#1E40AF", "#3B82F6", "#60A5FA", "#D97706", "#0F766E", "#7C3AED", "#0891B2"]


def snapshots(data_root):
    """取数流水（原始存档）列表——看板不用它，它只是"我们向后台要过什么"的凭据。"""
    root = Path(data_root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir()
                  if p.is_dir() and (p / "投放数据.csv").exists())


def bucket_map(cfg):
    """桶 id → 桶名（如 D → 火山引擎MediaKit-hang-D类），按 audiences 顺序。"""
    camp = cfg["campaign"]
    return [(str(a["id"]), naming.bucket_name(camp, a)) for a in cfg["audiences"]]


def bucket_of(task_name, buckets):
    for bid, bname in buckets:
        if bname in task_name:
            return bid
    return "?"


ZERO = (0, 0, 0, 0)


def sum_cells(cells, days=None):
    """`{天: [曝光, 点击, 登录曝光, 登录点击]}` → 四元组合计。

    `days=None`＝库里全部天；给了 `days` 就只加这些天——**「合计」只有这一处实现**
    （原先网页自己再算一遍、命令行那版还只能算全区间，同一个词三个数）。
    """
    vals = list(cells.values()) if days is None else [cells.get(d, ZERO) for d in days]
    return tuple(sum(v[i] for v in vals) for i in range(4))


def active_days(cells):
    """哪些天算「有量」（四项里任一非零）——「日均曝光」的分母口径只在这里定义。"""
    return sorted(d for d, v in cells.items() if any(v))


def _stat_row(bucket, batch_id, label, start, cells):
    """批次视图的一行：某桶某批次的累计（曝光 / 点击 / 登录数 / 有量天数）。"""
    e, c, le, lc = sum_cells(cells)
    live = active_days(cells)
    return {"bucket": bucket, "batch": batch_id, "label": label, "start": start,
            "e": e, "c": c, "le": le, "lc": lc, "days": len(live),
            "first": live[0] if live else None, "last": live[-1] if live else None}


def in_scope(o, scope, current_batch=None):
    """工单口径：`all` = 全部 / `investing` = 只在投 / `batch` = **当前批次**的工单（不看状态）。

    为什么要有 `batch`：新建工单在后台还没生成任务时 `workStatus` 是 `0`（不是"进行中"），
    按 `investing` 判会把**当前正在跑的那一批整个漏掉**（2026-09-28 发现）。
    """
    if scope == "investing":
        return bool(o["investing"])
    if scope == "batch":
        return bool(current_batch) and o["batch"] == current_batch
    return True


def bucket_view(cfg, pk_buckets, colors, batches, batch_judge, specs):
    """**桶维度**（2026-10-08 用户定）：把「批次 × 桶」翻成「一个桶 → 它自己的批次史」。

    为什么要翻：各桶复盘节奏不一样——曝光大的桶早就跑到很后面的批次，曝光小的桶还停在前几批，
    所以"当前批次"不是全局概念，**每个桶有自己的当前批**。

    口径（用户 2026-10-08 定，实施时不要自行改）：
      - **桶** = 活动 YAML 的 `audiences[].id`，跨批次是同一个桶；
      - `currentBatch` = 该桶**最后一次建批**——那份 YAML 里它至少挂了 1 条资源。
        只写了 audience、没挂资源的批次不算（如七批的 E 桶，那是占位）；
      - `refBatch` = 该桶**最近一次有量**的批次；页面在"当前批还没读数"时回退显示它的数；
      - `batches` = 该桶参与过的每一批，按起投日排序（最新→最老由页面决定）。
    """
    topics = {str(a["id"]): (a.get("topic") or "") for a in cfg["audiences"]}
    cur_of = campaign_mod.bucket_current(batches)     # 每个桶的最后一次建批（口径只写一遍）
    rows = {}
    for b in batches:
        for r in (batch_judge.get(b["id"]) or []):
            rows.setdefault(r["bucket"], []).append((b, r))
    keys = ("task", "state", "exposure", "click", "threshold", "needClick", "slots",
            "ready", "pass", "keep", "drop", "newCopy", "conclusion", "groups", "action")
    out = []
    for bid, name in pk_buckets:
        items = rows.get(bid) or []
        cur = next((x for x in items if x[0]["id"] == cur_of.get(bid)), None)
        withdata = [x for x in items if (x[1].get("exposure") or 0) > 0]
        ref = withdata[-1] if withdata else None
        out.append({
            "id": bid, "name": name, "color": colors.get(bid, ""),
            "topic": topics.get(bid, ""),
            "threshold": (specs.get(bid) or {}).get("threshold"),
            "currentBatch": cur[0]["id"] if cur else None,
            "refBatch": ref[0]["id"] if ref else None,
            "batches": [dict([("batch", b["id"]), ("label", b["label"]), ("start", b["start"])] +
                             [(k, r.get(k)) for k in keys])
                        for b, r in items],
        })
    return out


def build_payload(cfg, conn, today=None, config_path=None):
    """台账库 → 看板 JSON（页面要什么这里给什么，聚合只在这一处做）。

    `config_path` 给了就顺带出**批次维度**（`batches` / `currentBatch` / `orders[].batch` / `copy`）；
    不给（例如单测里只塞一个 cfg dict）就退化成空批次表，其余字段照旧。
    """
    activity_id = cfg["campaign"]["taskGroupName"]
    buckets = bucket_map(cfg)
    colors = {bid: BUCKET_COLORS[i % len(BUCKET_COLORS)] for i, (bid, _) in enumerate(buckets)}
    today = today or datetime.date.today().isoformat()

    batches = campaign_mod.load_batches(config_path) if config_path else []
    name2batch = {n: b["id"] for b in batches for n in b["orders"].values()}
    current = campaign_mod.current_batch(batches, config_path) if batches else None

    days = perf_db.days(conn, activity_id)
    per_task = perf_db.order_cells(conn, activity_id)
    task_rows = perf_db.tasks(conn, activity_id)
    task_names = {t["task_name"] for t in task_rows}

    # 工单：区间合计 + 逐日明细（逐日明细给前端算"全部 / 仅在投"两个口径）
    orders, order_cells = [], {}
    for t in task_rows:
        series = per_task.get(t["task_id"], {})
        live = active_days(series)
        state = t["state"] or ""
        e, c, le, lc = sum_cells(series)
        orders.append({
            "id": t["task_id"], "name": t["task_name"],
            "bucket": bucket_of(t["task_name"], buckets),
            "status": state, "state_at": t["state_at"] or "",
            "investing": state == "进行中",
            "batch": name2batch.get(t["task_name"]),      # 归属批次（按工单名对齐；对不上 = None）
            "first": live[0] if live else None,
            "last": live[-1] if live else None,
            "active_days": len(live),
            "e": e, "c": c, "le": le, "lc": lc,
        })
        order_cells[t["task_name"]] = series

    # 桶级「某天的量」与「哪些天有量」：两个口径都在这一层算好——页面只做加减，不再自己拼口径
    bucket_cells, bucket_days = {}, {}
    for bid, _ in buckets:
        bucket_cells[bid], bucket_days[bid] = {}, {}
        for scope in ("all", "investing", "batch"):
            rows = [o for o in orders if o["bucket"] == bid and in_scope(o, scope, current)]
            cells = {}
            for d in days:
                vals = [order_cells[o["name"]].get(d) for o in rows]
                cells[d] = tuple(sum(v[i] for v in vals if v) for i in range(4))
            bucket_cells[bid][scope] = cells
            bucket_days[bid][scope] = active_days(cells)
    order_days = {o["name"]: active_days(order_cells[o["name"]]) for o in orders}

    # 资源级：每个 (工单, 资源) 的最新读数 = 整段累计
    readings = perf_db.latest_resource_readings(conn, activity_id)
    resources = {}
    for r in readings:
        task = r["task_name"]
        item = resources.setdefault(task, {"task": task, "bucket": bucket_of(task, buckets),
                                           "groups": [], "at": r["fetched_at"] or ""})
        item["groups"].append({"label": r["group_label"] or "", "res": r["resource_name"] or "",
                               "e": r["exposure"], "c": r["click"]})
        item["at"] = max(item["at"], r["fetched_at"] or "")
    for item in resources.values():
        item["groups"].sort(key=lambda g: (GROUP_ORDER.index(g["label"]) if g["label"] in GROUP_ORDER else 9))

    # 判定（门槛 / 达标 / 留谁下谁）：**规则在 judging.py**，这里只做装配（2026-09-28）
    # 批次之间：桶 × 批次 的累计（按天事实、全部天）——给人看"换了文案之后点击有没有变"
    batch_stats, ungrouped = [], {}
    for bid, _ in buckets:
        for b in batches:
            rows = [o for o in orders if o["bucket"] == bid and o["batch"] == b["id"]]
            if not rows:
                continue
            cells = {}
            for d in days:
                vals = [order_cells[o["name"]].get(d) for o in rows]
                cells[d] = tuple(sum(v[i] for v in vals if v) for i in range(4))
            batch_stats.append(_stat_row(bid, b["id"], b["label"], b["start"], cells))
        # 没归到任何批次的工单也要出（如 A 组正式口径那条 `测试工单-…`），否则 A 的历史会缺一块；
        # 但**完全拿不到批次信息**时（没给 config_path）不造这一行——那是"没有可比批次"，不是"未归类"
        others = [o for o in orders if o["bucket"] == bid and not o["batch"]] if batches else []
        if others:
            cells = {}
            for d in days:
                vals = [order_cells[o["name"]].get(d) for o in others]
                cells[d] = tuple(sum(v[i] for v in vals if v) for i in range(4))
            batch_stats.append(_stat_row(bid, None, "未归类（测试 / 手建工单）", "", cells))

    th = campaign_mod.load_judge_thresholds(config_path) if config_path else {}
    after = campaign_mod.load_after_actions(config_path) if config_path else {}
    copy_map = campaign_mod.copy_index(batches)

    # 批次 × 桶：**资源级读数与文案原文（没有门槛也照出）** + 有门槛时附上判定。
    # ⚠ 资源级和判定**解耦**（2026-09-28）：以前没定门槛的活动（KIRO）整块为空，页面连三条文案都看不到。
    # 判定口径仍与命令行一致——工单名以该批后缀结尾的资源读数（累计），规则本体在 judging.py。
    pass_ctr = float(th.get("passCtr", 0.003))
    specs = th.get("buckets") or {}
    # 工单按"名字后缀"归到批：有后缀的按后缀匹配；**没有后缀的首批**收下所有不匹配其它后缀的
    # （KIRO 只有首批，全靠这条；纯 `endswith("")` 会把所有工单都算给首批，所以要排除别的后缀）
    suf_list = [b["suffix"] for b in batches if b["suffix"]]
    has_first = any(not b["suffix"] for b in batches)
    by_suffix = {}
    for r in readings:
        name = r["task_name"] or ""
        key = next((s for s in suf_list if name.endswith(s)), "" if has_first else None)
        if key is None:
            continue
        by_suffix.setdefault(key, {}).setdefault(name, []).append(r)

    batch_judge = {}
    for b in batches:
        rows_out = []
        per_task = by_suffix.get(b["suffix"] or "", {})
        for bid in sorted(b["orders"]):
            tname = b["orders"][bid]
            rs = per_task.get(tname, [])
            if tname not in task_names:                # 这批这个桶还没建工单
                rows_out.append({"bucket": bid, "task": None, "batch": b["id"], "state": "",
                                 "conclusion": "", "exposure": 0, "click": 0, "threshold": None,
                                 "needClick": 0, "slots": 0, "ready": False, "pass": False,
                                 "keep": [], "drop": [], "newCopy": 0, "groups": []})
                continue
            spec = specs.get(bid)
            if spec:
                j = judging.judge_one(tname, spec, pass_ctr, rs)
                row = {"threshold": j["threshold"], "needClick": j["need_click"], "slots": j["slots"],
                       "ready": j["ready"], "pass": j["pass"], "keep": j["keep"], "drop": j["drop"],
                       "newCopy": j["new_copy"], "state": j["state"], "conclusion": j["conclusion"],
                       "exposure": j["exposure"], "click": j["click"]}
            else:                                      # 没定门槛（如 KIRO）：只出数据，不出判定
                row = {"threshold": None, "needClick": 0, "slots": len(rs), "ready": False,
                       "pass": False, "keep": [], "drop": [], "newCopy": 0, "state": "",
                       "conclusion": "", "exposure": sum(x["exposure"] for x in rs),
                       "click": sum(x["click"] for x in rs)}
            groups = []
            for x in sorted(rs, key=lambda y: -y["click"]):
                cp = copy_map.get(x["resource_name"] or "", {})
                groups.append({"label": x["group_label"] or "", "res": x["resource_name"] or "",
                               "e": x["exposure"], "c": x["click"],
                               "keep": x["resource_name"] in row["keep"],
                               "title": cp.get("title") or "", "summary": cp.get("summary") or "",
                               "highlight": cp.get("highlight") or ""})
            # 人定的调整动作（`配置/复盘动作.yaml`）：**有记录就用它顶掉规则结果**
            # （用户 2026-09-30 定：没调整显示建议动作、调整过显示调整动作）。
            # 槽位名直接对齐后台 AB 组 = 读数里的 group_label，所以保留/下的小标也一起对齐。
            ha = (after.get(b["id"]) or {}).get(bid)          # 2026-10-08 起按**批次 id**取
            if ha is None:                                     # 旧文件（后缀键）兜底一次
                ha = (after.get(b["suffix"] or "") or {}).get(bid)
            if ha:
                keep_labels = [str(x) for x in (ha.get("keep") or [])]
                for g in groups:
                    g["keep"] = g["label"] in keep_labels
                row["keep"] = [g["res"] for g in groups if g["keep"]]
                row["drop"] = [g["res"] for g in groups if not g["keep"]]
                row["newCopy"] = int(ha.get("new") or 0)
                row["action"] = {"keep": keep_labels,
                                 "drop": [str(x) for x in (ha.get("drop") or [])],
                                 "new": int(ha.get("new") or 0),
                                 "note": str(ha.get("note") or "")}
            row.update({"bucket": bid, "task": tname, "batch": b["id"], "groups": groups})
            rows_out.append(row)
        batch_judge[b["id"]] = rows_out

    # 桶维度（2026-10-08）：一个桶 → 它自己的批次史 + 它自己的当前批
    buckets_out = bucket_view(cfg, buckets, colors, batches, batch_judge, specs)

    return {
        "label": cfg["label"],
        "activityId": activity_id,       # 任务组名（= 活动 id）：页面切活动要用它，不能拿 label 比
        "source": "台账库",
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        # 今天（及更晚）那天还没走完：判定按"完整日"算，前端也要标出来
        "partialDays": [d for d in days if d >= today],
        "ctrLine": CTR_LINE,
        "clickFloor": CLICK_FLOOR,
        "buckets": buckets_out,          # [{id,name,color,topic,threshold,currentBatch,refBatch,batches}]
        "days": days,
        "orders": sorted(orders, key=lambda o: (o["bucket"], o["name"])),
        "orderCells": order_cells,
        "bucketCells": bucket_cells,     # {桶: {口径: {天: [e,c,le,lc]}}}——"一个桶当天的量"
        "bucketDays": bucket_days,       # {桶: {口径: [有量的天]}}——"日均曝光"的分母口径
        "orderDays": order_days,         # {工单: [有量的天]}
        "resources": sorted(resources.values(), key=lambda t: (t["bucket"], t["task"])),
        "batches": batches,              # [{id,label,suffix,start,end,yaml,orders,copy}] 按起投日排序
        "currentBatch": current,         # 页面默认口径 = 这一批（不看工单状态）
        "copy": copy_map,                # 资源名 → 文案原文（跨批次合并，含幸存文案）
        "thresholds": th,                # 判定门槛.yaml 原文（缺文件 = {}，页面据此降级）
        "batchJudge": batch_judge,       # {批次id: [每桶一条判定 + 三条文案]}（页面按批次切换）
        "batchStats": batch_stats,       # 桶 × 批次 的累计（给"批次之间点击变化"那个视图）
    }


def todo_rows(payload):
    """「到门槛 · 没复盘 · 还在投」的工单——`web/app.py` 的 `/api/todo` 按活动调它。

    用户 2026-09-30 定，三条**同时**满足才算待办：
      - **在投**：工单状态 = 进行中（已下线的不再是要处理的事）；
      - **到门槛**：该桶累计曝光 ≥ 门槛（判定行的 `ready`）——**达标没达标都算**，
        两种都要动手（达标转长期单、没达标换文案）；
      - **没复盘**：`配置/复盘动作.yaml` 里没有这「批次 × 桶」的记录。
        有记录 = 页面已经在写「调整动作」，说明这桶已经处理过了。

    2026-10-08 改：只看**每个桶自己的当前批**（桶独立）——各桶复盘节奏不一样，
    曝光大的桶先到门槛，就该先冒出来，不再被"全局当前批"卡住。
    没定门槛的活动（`判定门槛.yaml` 缺文件，如 KIRO）出不了 `ready`，自然是空清单。
    """
    live = {o["name"] for o in payload.get("orders") or [] if o.get("investing")}
    out = []
    for bk in payload.get("buckets") or []:
        if "batches" not in bk:                      # 兼容：老 payload 的 buckets 只有 id/name/color
            continue
        for r in bk.get("batches") or []:
            if r.get("batch") != bk.get("currentBatch"):
                continue                             # 只看该桶自己的当前批
            if not r.get("ready") or r.get("action") or not r.get("task"):
                continue
            if r["task"] not in live:
                continue
            out.append({"activity": payload["label"],            # 给人看的名字
                        "activityId": payload.get("activityId") or "",  # 切活动要用的 id
                        "batch": r.get("batch"),
                        "batchLabel": r.get("label") or "", "start": r.get("start") or "",
                        "bucket": bk.get("id"), "task": r.get("task"),
                        "exposure": r.get("exposure") or 0, "click": r.get("click") or 0,
                        "threshold": r["threshold"], "pass": bool(r.get("pass")),
                        "state": r.get("state") or "", "conclusion": r.get("conclusion") or ""})
    return out


def scope_orders(payload, bucket_id, scope="all"):
    """某口径下的工单：`all` = 全部（含已下线）/ `investing` = 只在投 / `batch` = 当前批次。"""
    return [o for o in payload["orders"]
            if o["bucket"] == bucket_id and in_scope(o, scope, payload.get("currentBatch"))]


def totals(payload, bucket_id, scope="all", days=None):
    """某桶某口径的合计：`days=None`＝库里全部天；给了 `days` 就只算这些天（跟页面所选区间同口径）。

    合计只有这一处实现（原先网页自己再算一遍、命令行那版还只能算全区间）。
    """
    cells = (payload.get("bucketCells") or {}).get(bucket_id, {}).get(scope, {})
    e, c, le, lc = sum_cells(cells, days)
    return {"e": e, "c": c, "le": le, "lc": lc,
            "orders": scope_orders(payload, bucket_id, scope)}
