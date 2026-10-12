# -*- coding: utf-8 -*-
"""整活动 YAML 的装载：解析 + 校验 + 补默认值（唯一入口）。

为什么要有它：以前每个脚本各自 `.get("字段", 默认值)` 兜底，字段名打错或漏填都不报错——
`exposureCap` 少写个 s，三个曝光框就静默用 100000/500000/500000 一路填到后台，
跑到浏览器第 3 步才发现。现在四个执行脚本都从 `campaign.load(path)` 装载：
**启动那一刻**把问题一次列全。

契约（字段白名单、必填项、默认值）见 `../campaigns/README.md`，本文件是它的代码化身，
改契约要两边一起改（项目改动纪律）。
"""
import difflib
import glob
import os
import re

import yaml

import naming      # 命名规则的唯一实现（桶名 / 工单名），批次索引靠它算工单名

# ---------- 契约：各层的字段白名单 ----------
TOP = {"version", "adType", "label", "controls", "campaign", "audiences", "taskOrder"}
CAMPAIGN = {"brand", "owner", "namePrefix", "phase", "taskGroupName", "activityLink"}
CONTROLS = {"channelType", "channel", "materialPath", "defaults", "fields"}
CONTROLS_DEFAULTS = {"businessLine", "isPopup", "adClient", "closeBtnColor"}
FIELD_SPEC = {"placeholder", "type"}
FIELDS = {"title", "summary", "link"}
AUDIENCE = {"id", "topic", "target", "taskName", "subBusinessLine", "keywordGroup",
            "resources", "clickThreshold", "exposureThreshold",
            "abGroups", "distributionList", "nameSuffix"}   # 逐桶覆盖：工单挂本桶的 3 资源 / 本桶的用户名单 / 重投名字后缀（-2）
KEYWORD_GROUP = {"keywords"}
# highlight = 飘红词（2026-09-24 加）：**可选**，留空 = 不飘红；填了就选「是否飘红=是」并写入该词。
# 后台机制（用户实测）：只能填一个表达，正则最长匹配，标题 + 摘要里所有出现处都会标红。
RESOURCE = {"role", "name", "title", "summary", "link", "highlight"}
# abTest（2026-10-12 加）：true / 缺省 = 老路（AB测试=是，逐组挂资源）；
#   false = **单资源长期单**（AB测试=否，只挂 abGroups 的第一条、没有流量占比）——D 桶转长期单用。
TASK_ORDER = {"businessLine", "taskGroup", "taskName", "channel", "channelSizeId", "abGroups",
              "abTest", "price", "deliveryDate", "distributionList", "exposureCaps"}
DELIVERY_DATE = {"mode", "start", "end", "timeStart", "timeEnd"}
AB_GROUP = {"label", "resource", "weightPct"}

# 业务约定的默认值，只在这里定义一次，脚本不再各自兜底
# ⛔ 计费价格（`price`）**故意不在这里**（用户 2026-09-22 定）：它不再是固定数值，
#    写 YAML 前必须问用户当期价格 → 所以它是必填字段（见 validate），
#    缺了直接报错，**不允许**静默套用某个历史价（如 20/30）。
DEFAULTS = {
    "deliveryDate": {"mode": "set_time", "timeStart": 8, "timeEnd": 23},
    "exposureCaps": {"daily": 100000, "weekly": 500000, "total": 500000},
}


def _p(path):
    return (path + ".") if path else ""


class _Errs:
    def __init__(self):
        self.items = []

    def add(self, msg):
        self.items.append(msg)

    def keys(self, path, data, allowed):
        """未知字段要报错，带一句「是不是想写 X」的提示。"""
        if not isinstance(data, dict):
            self.add("%s 应该是一个字典，实际是 %s" % (path or "顶层", type(data).__name__))
            return
        for k in data:
            if k not in allowed:
                near = difflib.get_close_matches(str(k), sorted(allowed), n=1)
                hint = "，是不是想写 %s？" % near[0] if near else ""
                self.add("未知字段 %s%s%s（不在契约里）" % (_p(path), k, hint))

    def need(self, path, data, key):
        if not isinstance(data, dict) or key not in data or data[key] in (None, "", []):
            self.add("缺少必填字段 %s%s" % (_p(path), key))
            return False
        return True


def validate(data):
    """只检查不改数据，返回问题清单（空列表 = 合格）。"""
    e = _Errs()
    if not isinstance(data, dict):
        return ["整活动 YAML 顶层应该是一个字典"]
    e.keys("", data, TOP)

    camp = data.get("campaign")
    if not isinstance(camp, dict):
        e.add("缺少必填段 campaign")
        camp = {}
    e.keys("campaign", camp, CAMPAIGN)
    for k in ("taskGroupName", "activityLink"):
        e.need("campaign", camp, k)

    ctrl = data.get("controls")
    if not isinstance(ctrl, dict):
        e.add("缺少必填段 controls（类型固定项）")
        ctrl = {}
    e.keys("controls", ctrl, CONTROLS)
    for k in ("channel", "materialPath"):
        e.need("controls", ctrl, k)
    e.keys("controls.defaults", ctrl.get("defaults"), CONTROLS_DEFAULTS)
    e.need("controls.defaults", ctrl.get("defaults"), "businessLine")
    e.keys("controls.fields", ctrl.get("fields"), FIELDS)
    for k in sorted(FIELDS):
        spec = (ctrl.get("fields") or {}).get(k)
        e.keys("controls.fields.%s" % k, spec, FIELD_SPEC)
        e.need("controls.fields.%s" % k, spec, "placeholder")

    auds = data.get("audiences")
    if not isinstance(auds, list) or not auds:
        e.add("缺少必填段 audiences（至少 1 个桶）")
        auds = []
    has_prefix = bool((camp.get("namePrefix") or "").strip())
    for i, a in enumerate(auds):
        p = "audiences[%d]" % i
        e.keys(p, a, AUDIENCE)
        for k in ("id", "subBusinessLine"):
            e.need(p, a, k)
        e.keys(p + ".keywordGroup", (a or {}).get("keywordGroup"), KEYWORD_GROUP)
        e.need(p + ".keywordGroup", (a or {}).get("keywordGroup"), "keywords")
        if not has_prefix and not (a or {}).get("taskName"):
            e.add("%s 没有命名来源：campaign.namePrefix 没写，这个桶也没有 taskName" % p)
        res = (a or {}).get("resources")
        if not isinstance(res, list):
            # 允许空列表 = 本桶本轮没有新建资源、全部复用现有资源
            # （2026-09-29：E 桶「3 条全留、0 条新写」的第一个实例，见 调整/2026-09-29-七批.yaml）
            e.add("%s.resources 要写成列表（空列表 = 本桶本轮没有新建资源）" % p)
            res = []
        for j, r in enumerate(res):
            rp = "%s.resources[%d]" % (p, j)
            e.keys(rp, r, RESOURCE)
            for k in ("role", "name", "title", "summary"):
                e.need(rp, r, k)
        own = (a or {}).get("abGroups")
        if own is not None:
            if not isinstance(own, list) or not own:
                e.add("%s.abGroups 至少要 1 组（不写就回落到 taskOrder.abGroups）" % p)
            else:
                for j, g in enumerate(own):
                    e.keys("%s.abGroups[%d]" % (p, j), g, AB_GROUP)

    t = data.get("taskOrder")
    if not isinstance(t, dict):
        e.add("缺少必填段 taskOrder")
        return e.items
    e.keys("taskOrder", t, TASK_ORDER)
    for k in ("businessLine", "taskGroup", "channel", "price"):
        e.need("taskOrder", t, k)
    if "abTest" in t and not isinstance(t["abTest"], bool):
        e.add("taskOrder.abTest 必须是 true / false（false = 单资源、不跑 AB）")
    dd = t.get("deliveryDate")
    e.keys("taskOrder.deliveryDate", dd, DELIVERY_DATE)
    for k in ("start", "end"):     # 日期不猜：写死默认日期最容易跑错
        e.need("taskOrder.deliveryDate", dd, k)
    groups = t.get("abGroups")
    if not isinstance(groups, list) or not groups:
        if groups:
            e.add("taskOrder.abGroups 应该是非空列表")
        no_own = [str((a or {}).get("id", "?")) for a in auds
                  if not (isinstance(a, dict) and a.get("abGroups"))]
        if no_own:
            e.add("缺少 abGroups：桶 %s 没写自己的 abGroups，taskOrder.abGroups 兜底也没给"
                  % "、".join(no_own))
    else:
        for j, g in enumerate(groups):
            e.keys("taskOrder.abGroups[%d]" % j, g, AB_GROUP)
    caps = t.get("exposureCaps")
    if caps is not None:
        e.keys("taskOrder.exposureCaps", caps, set(DEFAULTS["exposureCaps"]))
    return e.items


def apply_defaults(data):
    """把业务约定的默认值填进去（只补缺，不覆盖写过的值）。"""
    t = data.setdefault("taskOrder", {})
    for k, v in DEFAULTS.items():
        if isinstance(v, dict):
            sub = t.setdefault(k, {})
            for kk, vv in v.items():
                if isinstance(sub, dict):
                    sub.setdefault(kk, vv)
        else:
            t.setdefault(k, v)
    return data


def load(path):
    """读整活动 YAML → 校验 → 补默认值。有问题一次性抛 ValueError（列全部问题）。"""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    errs = validate(data)
    if errs:
        raise ValueError("整活动 YAML 不合契约（%s）：\n  - %s" % (path, "\n  - ".join(errs)))
    return apply_defaults(data)


def load_or_exit(path):
    """CLI 脚本用：装不进去就打印问题清单并退出（退出码 2），不甩一堆 traceback。"""
    try:
        return load(path)
    except ValueError as e:
        print(str(e))
        raise SystemExit(2)


def activity_dir(config):
    """活动目录：整活动 YAML 可能放在 `活动/`、`活动/配置/` 或 `活动/调整/` 下（2026-09-17 起的归类）。

    `数据/`（取数快照、看板）与 `日志/`（断点账本、截图）**始终挂在活动目录下**，与 YAML 放在哪一层无关，
    所以各脚本一律用这个函数拿活动目录，不要各自 `dirname(config)`——否则 YAML 一挪，账本和快照就写错地方。
    """
    d = os.path.dirname(os.path.abspath(config))
    if os.path.basename(d) in ("配置", "调整"):
        d = os.path.dirname(d)
    return d


def discover(root="activities", only=None, log=None):
    """扫活动目录 → 「能过契约」的整活动 YAML 清单（看板多活动用，2026-09-28）。

    筛选靠**能不能装载**（`load()`），不靠文件名——所以生成器输入 `活动定义.yaml`、
    圈选阈值 `*.thresholds.yaml`、`判定门槛.yaml` 都被自然排除。

    - **只扫 `{活动}/配置/*.yaml`**：`调整/` 下那些批次 YAML（如 `2026-09-29-七批.yaml`）
      是同一个任务组的重投批次，**不入册**，否则一个活动会冒出好几份。
    - **下划线开头的目录不入册**（2026-10-08 定）：`activities/_示例活动/`、`activities/_验证数据/`
      这类是示例 / 彩排 / 工具目录，照样能用 `--config` 显式点名，只是不混进看板的活动下拉。
    - **按 `campaign.taskGroupName` 去重**：撞车直接报错并列路径，不静默挑一个
      （任务组名就是后台对象的分组键，两个活动同名 = 数据会混在一起）。
    - `only` 指定单个 YAML 时**装不上就报错**（用户显式点名，不静默跳过）。
    - `log` 给了就把跳过的文件逐条报出去（看板启动时打给人看），不给就安静跳过。

    返回 `[{"id", "label", "cfg", "cfg_path", "activity_dir"}]`，顺序 = 路径排序（稳定）。
    """
    if only:
        cands = [os.path.abspath(only)]
    else:
        cands = sorted(p for p in glob.glob(os.path.join(os.path.abspath(root), "*", "配置", "*.yaml"))
                       if not os.path.basename(os.path.dirname(os.path.dirname(p))).startswith("_"))
    out, seen = [], {}
    for p in cands:
        try:
            cfg = load(p)
        except Exception as e:
            if only:
                raise
            if log:
                log("跳过 %s：%s" % (p, str(e).splitlines()[0]))
            continue
        tid = cfg["campaign"]["taskGroupName"]
        if tid in seen:
            raise ValueError("两个活动的 taskGroupName 撞车（%s），先改一个：\n  - %s\n  - %s"
                             % (tid, seen[tid], p))
        seen[tid] = p
        out.append({"id": tid, "label": cfg.get("label") or tid,
                    "cfg": cfg, "cfg_path": p, "activity_dir": activity_dir(p)})
    return out


def load_batches(config, log=None):
    """扫 `配置/*.yaml` + `调整/*.yaml` → 批次索引（看板按批次复盘用，2026-09-28）。

    **一批 = 一份整活动 YAML**：`配置/…-hang.yaml` 是首批，`调整/2026-09-24-六批.yaml` 是后续批。
    名字后缀（`-2` / `-6`）**不是批次身份**——后台为了不重名，09-17 的 D 桶和 09-18 的 B/C 桶
    共用 `-2`；后缀只用来按 `naming.order_task_name()` 算工单名，再跟台账里的工单名对齐。

    每批给出 `{id, label, suffix, start, end, yaml, orders, copy}`：
      - `orders`：桶 id → 工单名（用它给台账里的工单归批）；
      - `copy`：本轮**新建**资源名 → 文案原文（标题 / 描述 / 飘红词 / 出处批次）——
        幸存文案不在本轮 `resources` 里，靠 `copy_index()` 跨批次找。
    顺序 = 投放开始日、再按 id；装载不过契约的文件用 `log` 报一句后跳过
    （`活动定义.yaml` / `*.thresholds.yaml` / `判定门槛.yaml` 都自然被排除）。
    """
    root = activity_dir(config)
    cands = (sorted(glob.glob(os.path.join(root, "配置", "*.yaml"))) +
             sorted(glob.glob(os.path.join(root, "调整", "*.yaml"))))
    out = []
    for p in cands:
        try:
            c = load(p)
        except Exception as e:
            if log:
                log("批次索引跳过 %s：%s" % (p, str(e).splitlines()[0]))
            continue
        camp = c["campaign"]
        dd = (c.get("taskOrder") or {}).get("deliveryDate") or {}
        bid = os.path.splitext(os.path.basename(p))[0]
        m = re.match(r"\d{4}-(\d{2})-(\d{2})-(.+)$", bid)
        label = ("%s-%s %s" % (m.group(1), m.group(2), m.group(3))) if m else "首批"
        copy = {}
        for a in c["audiences"]:
            for r in (a.get("resources") or []):
                copy[r["name"]] = {"title": r.get("title") or "",
                                   "summary": r.get("summary") or "",
                                   "highlight": r.get("highlight") or "",
                                   "bucket": str(a["id"]), "role": r.get("role") or "",
                                   "batch": label}
        # 全局兜底的 AB 组（`taskOrder.abGroups`）——和 `run_taskorder` 的取法**一模一样**：
        # 桶自己没写 abGroups 时用它。下面判"这批会给哪些桶建工单"必须跟着同一个规则走。
        top_groups = (c.get("taskOrder") or {}).get("abGroups")
        out.append({"id": bid, "label": label,
                    "suffix": next((naming.name_suffix(a) for a in c["audiences"]
                                    if naming.name_suffix(a)), ""),
                    "start": dd.get("start") or "", "end": dd.get("end") or "",
                    "yaml": os.path.relpath(p, root).replace("\\", "/"),
                    "orders": {str(a["id"]): naming.order_task_name(camp, a)
                               for a in c["audiences"]},
                    # 这一个批次**会给哪些桶建工单**——`bucket_current()` 要用：判据 = 这个桶有资源可挂
                    # （自己写的 abGroups，或回落到 taskOrder.abGroups），跟 `run_taskorder` 取 groups 的规则一致。
                    # 复用老资源的"长期单"批次 `resources` 是空的，但 abGroups 有，照样算这个桶的当前批次。
                    # ⚠ 必须是 **list 不能是 set**：整份批次索引会进看板 payload（`perf_payload` 的 `batches`），
                    #   set 过不了 `json.dumps`（2026-10-12 真踩到：页面 "Failed to fetch"）。
                    "abBuckets": sorted({str(a["id"]) for a in c["audiences"]
                                         if a.get("abGroups") or top_groups}),
                    "copy": copy})
    return sorted(out, key=lambda b: (b["start"], b["id"]))


def copy_index(batches):
    """资源名 → 文案原文（跨批次合并）。同名取**最早出现**的那批——就是它被写出来的那批。"""
    out = {}
    for b in batches:
        for name, item in b["copy"].items():
            out.setdefault(name, item)
    return out


def bucket_current(batches):
    """{桶 id: 该桶**最后一次建批**的批次 id}——2026-10-08 用户定，桶独立的核心口径。

    一个批次对这个桶**有交代**才算：**要么新建了资源**（`copy` 里有），**要么写了 `abGroups`**
    （= 这个批次会给它建工单）——**2026-10-12 补**：复用老资源的"长期单"批次 `resources: []`，
    但 `abGroups` 有，所以照样算（不然 D 的当前批次会一直停在下线了的老工单上）。
    两者都没有的**纯占位**批次不算（如七批的 E 桶只是占位）；
    一个桶在任何批次里都没被交代过时，回落到"最后一个提到它的批次"。
    看板（`perf_payload.bucket_view`）和巡检（`judge_batch`）都用这一份，别各写一遍。
    """
    has_res = {}
    for b in batches:
        got = set()
        for item in (b.get("copy") or {}).values():
            bid = str(item.get("bucket") or "")
            if bid:
                got.add(bid)
        has_res[b["id"]] = got | set(b.get("abBuckets") or ())
    cur, last_any = {}, {}
    for b in batches:
        for bid in (b.get("orders") or {}):
            last_any[bid] = b["id"]
            if bid in has_res[b["id"]]:
                cur[bid] = b["id"]
    for bid, bid_last in last_any.items():
        cur.setdefault(bid, bid_last)
    return cur


def current_batch(batches, config):
    """当前批次 = **活动最新的一批**（`load_batches` 已按「投放开始日 + id」排序，取最后一个）。

    ⚠ **2026-10-12 改**：以前读 `配置/判定门槛.yaml` 的 `batch` 字段，那个字段已经删了——
    它是"**桶独立**"（2026-10-08）之前留下的**全局批次号**，跟现在的口径冲突：现在**每个桶**看
    **自己最后一次建批**（规则在 `bucket_current()`，看板与巡检都用它）。`config` 参数保留只为兼容调用方。

    这个全局值现在只喂看板的历史口径（`perf_payload` 的 `currentBatch`）。
    """
    if not batches:
        return None
    return batches[-1]["id"]


def load_judge_thresholds(config):
    """读 `配置/判定门槛.yaml`（当前批次号 + 各桶门槛 + 达标线）；**没有就返回 {}**。

    看板用它显示「当前曝光 / 门槛 / 达标」，缺这份文件的活动（比如门槛还没定的 KIRO）自动降级。
    判定脚本 `judge_batch.py` 读的是同一份文件——它缺文件会报错退出，那是命令行该有的行为。
    """
    path = os.path.join(activity_dir(config), "配置", "判定门槛.yaml")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def after_actions_path(config):
    return os.path.join(activity_dir(config), "配置", "复盘动作.yaml")


def load_after_actions(config):
    """读 `配置/复盘动作.yaml`（**人定的调整动作**）→ {批次 id: {桶 id: {keep,drop,new,at,readings,note}}}。

    看板「文案 / 动作」列靠它分两种写法（用户 2026-09-30 定）：
      **有记录** = 这桶已经调整过 → 页面显示**调整动作**（人定的）；
      **没记录** = 还没动 → 页面回落 `judging.py` 算出来的**建议动作**。
    键从"批次后缀"改成"批次 id"（2026-10-08，用户定）：后缀在同一活动里不唯一
    （09-17 的 D 桶和 09-18 的 B/C 桶都是 `-2`），而且同一批里各桶后缀可以不同（09-21 五桶重投）。
    **键 = 被判过的那一批**（2026-10-12，用户定）：`note` 里引的是哪一批的数据，键就写哪一批——建批时
    写下的动作属于**上一批**的结论，不能挂在下一批名下（挂错了看板就会拿旧结论顶掉新批的规则结果，
    KIRO D 桶五批被顶了三天）。每条记录还要带 `at`（判定依据的取数时间）和 `readings`（当时逐槽位的
    `[曝光, 点击]`），看板据此区分"刚判的"和"几天前判的"（见 `perf_payload.human_action`）。
    旧文件（`batches:` + 后缀键）仍能读，`perf_payload` 取不到新键时会按后缀兜底一次。
    没有这份文件 / 文件坏了都返回 `{}`（页面全走规则，行为跟改造前一致）。
    """
    path = after_actions_path(config)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        d = d.get("buckets", d.get("batches", d))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# ---------- 同目录的 thresholds 文件（圈选调优结果），一并归这里管 ----------
THRESHOLD_FIELDS = ("click", "exposure", "count", "status", "base")


def thresholds_path(config):
    return os.path.splitext(config)[0] + ".thresholds.yaml"


def threshold_record(r):
    """一份调优落点 → 记录（栏位只在这里列一次，2026-09-23 收口）。

    吃两种形状：策略结果对象（`r.click`）或记录字典（`r["click"]`）。
    原先两条写回路径各列一遍栏位、取值方式还各一种，加一栏要改三处、还容易只改一边。
    """
    get = (lambda k: r.get(k)) if isinstance(r, dict) else (lambda k: getattr(r, k, None))
    return {k: get(k) for k in THRESHOLD_FIELDS}


def load_thresholds(config):
    """读调优结果 {桶id: {click, exposure, count, status, base}}；没有/坏了都返回 {}。"""
    p = thresholds_path(config)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        d = d.get("audiences", d)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_thresholds(config, by_id):
    with open(thresholds_path(config), "w", encoding="utf-8") as f:
        yaml.safe_dump({"audiences": by_id}, f, allow_unicode=True, sort_keys=False)
