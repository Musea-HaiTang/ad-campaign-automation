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
from datetime import date

import yaml

# ---------- 契约：各层的字段白名单 ----------
TOP = {"version", "adType", "label", "controls", "campaign", "audiences", "taskOrder"}
CAMPAIGN = {"brand", "owner", "namePrefix", "phase", "taskGroupName", "activityLink",
            "status", "endedAt", "rehearsal"}
CAMPAIGN_STATUSES = {"active", "ended"}
CONTROLS = {"channelType", "channel", "materialPath", "defaults", "fields", "username"}
CONTROLS_DEFAULTS = {"businessLine", "isPopup", "adClient", "closeBtnColor"}
FIELD_SPEC = {"placeholder", "type"}
FIELDS = {"title", "summary", "link", "username"}
REQUIRED_FIELDS = {"title", "summary", "link"}
AUDIENCE = {"id", "topic", "target", "taskName", "subBusinessLine", "keywordGroup",
            "resources", "clickThreshold", "exposureThreshold",
            "reviewThresholdExposure",
            "abGroups", "abTest", "distributionList", "nameSuffix"}
KEYWORD_GROUP = {"keywords"}
PRESENTATION_TYPES = {"disguised_post", "direct_marketing"}
STYLE_KEYS = {"regular", "antithesis", "adaptation", "poetry_reference"}
VALIDATION_SLOTS = {"first_test", "retest", "backup", "anchor"}
RESOURCE = {
    "role", "name", "title", "summary", "link",
    "angleKey", "presentationType", "styleKey", "validationSlot",
}
LEGACY_RESOURCE = {"highlight"}  # 历史 YAML 仍可装载，但运行时忽略
# abTest（2026-10-12 加）：true = AB测试=是；false = 单资源、不跑 AB。
# 每个桶可以单独覆盖 taskOrder.abTest，支持同一活动里混合 1 / 2 / 3 资源。
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


def resolve_ab_test(audience, task_order):
    """解析一个桶的 AB 模式：桶级优先，其次全局兜底，最后按资源数推导。"""
    audience = audience or {}
    task_order = task_order or {}
    if "abTest" in audience:
        return audience["abTest"]
    if "abTest" in task_order:
        return task_order["abTest"]
    groups = audience.get("abGroups") or task_order.get("abGroups") or []
    resources = audience.get("resources") or []
    count = len(resources) or len(groups)
    return count != 1


def is_rehearsal(cfg):
    """彩排配置禁止进入真实提交路径。"""
    return bool((cfg.get("campaign") or {}).get("rehearsal", False))


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
    status = camp.get("status", "active")
    if status not in CAMPAIGN_STATUSES:
        e.add("campaign.status 只能是 active 或 ended，实际是 %r" % status)
    ended_at = camp.get("endedAt")
    if ended_at and status != "ended":
        e.add("campaign.endedAt 只用于 status: ended 的活动")
    if ended_at:
        try:
            date.fromisoformat(str(ended_at))
        except ValueError:
            e.add("campaign.endedAt 要写成 YYYY-MM-DD，实际是 %r" % ended_at)
    if "rehearsal" in camp and not isinstance(camp["rehearsal"], bool):
        e.add("campaign.rehearsal 必须是 true / false")

    ctrl = data.get("controls")
    if not isinstance(ctrl, dict):
        e.add("缺少必填段 controls（类型固定项）")
        ctrl = {}
    e.keys("controls", ctrl, CONTROLS)
    for k in ("channel", "materialPath"):
        e.need("controls", ctrl, k)
    material_path = ctrl.get("materialPath") or []
    dynamic_ad = bool(material_path) and material_path[0] == "动态广告"
    if dynamic_ad:
        e.need("controls", ctrl, "username")
    e.keys("controls.defaults", ctrl.get("defaults"), CONTROLS_DEFAULTS)
    e.need("controls.defaults", ctrl.get("defaults"), "businessLine")
    e.keys("controls.fields", ctrl.get("fields"), FIELDS)
    for k in sorted(FIELDS):
        spec = (ctrl.get("fields") or {}).get(k)
        if k not in REQUIRED_FIELDS and not spec:
            continue
        e.keys("controls.fields.%s" % k, spec, FIELD_SPEC)
        e.need("controls.fields.%s" % k, spec, "placeholder")
    if dynamic_ad:
        e.need("controls.fields", ctrl.get("fields"), "username")

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
        if "abTest" in (a or {}) and not isinstance(a["abTest"], bool):
            e.add("%s.abTest 必须是 true / false" % p)
        review_threshold = (a or {}).get("reviewThresholdExposure")
        if review_threshold is not None:
            try:
                if int(review_threshold) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                e.add("%s.reviewThresholdExposure 必须是正整数" % p)
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
        if len(res) > 3:
            e.add("%s.resources 最多 3 条，当前是 %d 条" % (p, len(res)))
        for j, r in enumerate(res):
            rp = "%s.resources[%d]" % (p, j)
            e.keys(rp, r, RESOURCE | LEGACY_RESOURCE)
            for k in ("role", "name", "title", "summary"):
                e.need(rp, r, k)
            for key, allowed, label in (
                ("presentationType", PRESENTATION_TYPES, "呈现类型"),
                ("styleKey", STYLE_KEYS, "风格"),
                ("validationSlot", VALIDATION_SLOTS, "验证位"),
            ):
                value = r.get(key)
                if value not in (None, "") and value not in allowed:
                    e.add("%s.%s 的%s不合法：%s（可选 %s）" % (
                        rp, key, label, value, " / ".join(sorted(allowed))))
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

    for i, a in enumerate(auds):
        p = "audiences[%d]" % i
        a = a or {}
        mode = resolve_ab_test(a, t)
        own_resources = a.get("resources") or []
        own_groups = a.get("abGroups") or t.get("abGroups") or []
        if mode is True:
            if len(own_resources) == 1 or len(own_groups) == 1:
                e.add("%s 只有 1 个资源，必须使用 abTest: false（AB测试=否）" % p)
            elif own_groups and len(own_groups) not in (2, 3):
                e.add("%s 的 abGroups 只能是 2 或 3 组（AB测试=是）" % p)
        elif mode is False:
            if len(own_resources) > 1:
                e.add("%s 配置了 abTest: false，但 resources 有 %d 条" % (p, len(own_resources)))
            if len(own_groups) > 1:
                e.add("%s 配置了 abTest: false，但 abGroups 有 %d 条" % (p, len(own_groups)))
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
    for a in data.get("audiences") or []:
        a.setdefault("abTest", resolve_ab_test(a, t))
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
    """活动目录：整活动 YAML 可能放在 `活动/`、`活动/配置/` 或 `活动/批次/` 下。

    `数据/`（取数快照、看板）与 `日志/`（断点账本、截图）**始终挂在活动目录下**，与 YAML 放在哪一层无关，
    所以各脚本一律用这个函数拿活动目录，不要各自 `dirname(config)`——否则 YAML 一挪，账本和快照就写错地方。
    """
    d = os.path.dirname(os.path.abspath(config))
    if os.path.basename(d) in ("配置", "批次"):
        d = os.path.dirname(d)
    return d


def discover(root="activities", only=None, log=None):
    """扫活动目录 → 「能过契约」的整活动 YAML 清单（看板多活动用，2026-09-28）。

    筛选靠**能不能装载**（`load()`），不靠文件名——所以生成器输入 `活动定义.yaml`
    等非整活动 YAML 自然排除。

    - **只扫 `{活动}/配置/*.yaml`**：`批次/` 下那些批次 YAML
      是同一个任务组的重投批次，**不入册**，否则一个活动会冒出好几份。
    - **下划线开头的目录不入册**（2026-10-08 定）：`activities/_示例活动/`、`activities/_彩排借用对象/`
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
        camp = cfg["campaign"]
        ended_at = camp.get("endedAt")
        if isinstance(ended_at, date):
            ended_at = ended_at.isoformat()
        out.append({"id": tid, "label": cfg.get("label") or tid,
                    "status": camp.get("status", "active"), "endedAt": ended_at,
                    "cfg": cfg, "cfg_path": p, "activity_dir": activity_dir(p)})
    return out
