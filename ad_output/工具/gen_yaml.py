# -*- coding: utf-8 -*-
"""从「活动定义 YAML」生成整活动 YAML（供 automation 执行层脚本消费）。

用法:
    python gen_yaml.py --def activities/{活动}/活动定义.yaml [--username <用户名>] [--out ...]

产出遵循 automation/campaigns/README.md 的字段规范；活动内容全部来自活动定义 YAML，
本脚本只做「装配」，名字一律问 naming 模块要（`automation/scripts/naming.py`，命名规则的唯一实现），
不含任何活动内容。

跳转链接（2026-10-13 加）：**桶级 `link`** → 该桶每条资源都带上它（同一个产品共用一个链接）；
单条 copy 自己写了 `link` 就以它为准；两者都没有 → 执行层回落到 `campaign.activityLink`（老口径）。
契约见 automation/scripts/campaign.py 的 `RESOURCE.link`，落地在 run_ads.py（`res.get("link") or camp["activityLink"]`）。
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]           # ad_management/
OPERATOR_CONFIG = ROOT / ".local" / "operator.json"
sys.path.insert(0, str(ROOT / "automation" / "scripts"))

import naming  # noqa: E402
import campaign  # noqa: E402

# 类型固定项（controls）：同一广告位类型基本不变
CONTROLS = {
    "channelType": "页面类",
    "channel": "PC博客详情页-新模版-T0",
    "materialPath": ["动态广告", "其它"],
    "defaults": {"businessLine": "企业服务事业部", "isPopup": False,
                 "adClient": "广告", "closeBtnColor": "浅色"},
    "fields": {
        "link": {"placeholder": "请输入URL解析"},
        "title": {"placeholder": "解析自动生成标题"},
        "username": {"placeholder": "解析自动生成用户名"},
        "summary": {"placeholder": "解析自动生成描述", "type": "textarea"},
    },
}

# AB 槽位：role → 后台行名（后台要从对照组往下填满、不能跳行）+ 流量占比（按资源条数，合计必须 100%）
ROLE_ORDER = [("control", "对照组"), ("experiment1", "实验组1"), ("experiment2", "实验组2")]
WEIGHT_BY_COUNT = {3: [34, 33, 33], 2: [50, 50]}
COPY_META_FIELDS = ("angleKey", "presentationType", "styleKey", "validationSlot")


def derive_ab_groups(resources, ab_test=True):
    """首投：按本桶新建的 `resources` 派生 AB 三组（名字直接取 resources 里的 name，与 naming 同源）。

    为什么要有它（2026-10-12 用户定）：以前 `abGroups[].resource` 是**手写**在活动定义里的，
    和 `resources`（naming 算出来的名字）是两个出处——改命名规则那天手写的那份没跟着变，
    于是生成出「新建资源没被任何 AB 行引用」（自检拦住了；没拦住就是工单挂不上资源）。
    认不出的组合（条数不是 2/3、role 重复）返回空列表，**不猜**，留给桶里手写。

    `taskOrder.abTest: false` 时走单资源路径：1 条资源自动派生「对照组」，不带流量占比。
    """
    if ab_test is False:
        if len(resources) == 1:
            return [{"label": ROLE_ORDER[0][1], "resource": resources[0]["name"]}]
        return []
    by_role = {r["role"]: r for r in resources}
    roles = [(role, label) for role, label in ROLE_ORDER if role in by_role]
    weights = WEIGHT_BY_COUNT.get(len(roles))
    if not weights or len(roles) != len(resources):
        return []
    return [{"label": label, "resource": by_role[role]["name"], "weightPct": w}
            for (role, label), w in zip(roles, weights)]


def resolve_username(cli_username=None):
    """命令行显式指定优先，否则读取首次登录后保存的当前操作者用户名。"""
    if cli_username is not None:
        username = str(cli_username).strip()
        if not username:
            raise SystemExit("--username 不能为空。")
        return username
    if not OPERATOR_CONFIG.is_file():
        raise SystemExit(
            "缺少 .local/operator.json。先运行 README 中的 AI 一键部署，"
            "再运行 .venv\\Scripts\\python.exe scripts\\doctor.py --login 保存登录用户名。")
    try:
        data = json.loads(OPERATOR_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("无法读取 .local/operator.json：" + str(exc)) from exc
    username = str((data or {}).get("ad_username") or "").strip()
    if not username:
        raise SystemExit(
            "操作者配置里没有 ad_username。先运行 "
            ".venv\\Scripts\\python.exe scripts\\doctor.py --login 保存当前登录用户名。")
    return username


def build(d, username):
    camp = d["campaign"]
    sub = d["subBusinessLine"]
    t = d["taskOrder"]
    global_ab_test = t.get("abTest")
    naming.require_prefix(camp)   # 命名前缀必填，缺了在这里就炸，别带着错名字往下走

    audiences = []
    for b in d["buckets"]:
        copies = b.get("copies") or []
        if len(copies) > 3:
            raise SystemExit("桶 %s 最多 3 份 copies，当前是 %d 份。" % (
                b["id"], len(copies)))
        explicit_ab_test = b.get("abTest") if "abTest" in b else global_ab_test
        if explicit_ab_test is not None and not isinstance(explicit_ab_test, bool):
            raise SystemExit("桶 %s 的 abTest 必须是 true / false。" % b["id"])
        if len(copies) == 1:
            if explicit_ab_test is True:
                raise SystemExit("桶 %s 只有 1 份 copies，不能配置 abTest: true。" % b["id"])
            ab_test = False
        elif len(copies) in (2, 3):
            if explicit_ab_test is False:
                raise SystemExit(
                    "桶 %s 配置了 abTest: false（单资源），但 copies 不是正好 1 份，当前是 %d 份。"
                    % (b["id"], len(copies))
                )
            ab_test = True
        else:
            manual_groups = b.get("abGroups") or t.get("abGroups") or []
            ab_test = explicit_ab_test
            if ab_test is None:
                ab_test = len(manual_groups) != 1
        resources = []
        for index, c in enumerate(copies, 1):
            missing = [key for key in COPY_META_FIELDS if not c.get(key)]
            if missing:
                raise SystemExit(
                    "桶 %s 第 %d 条文案缺少分类字段：%s"
                    % (b["id"], index, ", ".join(missing))
                )
            r = {
                "role": c["role"],
                "name": naming.resource_name(camp, b, c["label"]),
                "title": c["title"],
                "summary": c["summary"],
            }
            for source in COPY_META_FIELDS:
                target = source
                value = str(c.get(source) or "").strip()
                r[target] = value
            # 跳转链接（可选；契约见 RESOURCE.link）——桶级给整桶打底，单条优先。
            link = c.get("link") or b.get("link")
            if link:
                r["link"] = link
            resources.append(r)
        a = {
            "id": b["id"],
            "topic": b["topic"],
            "target": b["audience"],
            "taskName": naming.bucket_name(camp, b),
            "subBusinessLine": sub,
            "keywordGroup": {"keywords": b["keywords"]},
            "resources": resources,
        }
        if b.get("reviewThresholdExposure"):
            a["reviewThresholdExposure"] = int(b["reviewThresholdExposure"])
        # AB 三组：**首投自动派生**（2026-10-12 用户定）——名字跟 resources 同源，不会再出现"改了命名、
        # 手写的 abGroups 还是旧名字"。桶里显式写了 abGroups 就用手写的（复盘重投 = 复用老资源、只挂 1~2 条）。
        abg = b.get("abGroups") or derive_ab_groups(resources, ab_test=ab_test)
        if ab_test is False and len(abg) > 1:
            raise SystemExit("桶 %s 是单资源模式，但 abGroups 有 %d 条。" % (
                b["id"], len(abg)))
        if ab_test is True and abg and len(abg) not in (2, 3):
            raise SystemExit("桶 %s 是 AB 模式，但 abGroups 不是 2 或 3 条。" % b["id"])
        if not abg and not t.get("abGroups"):
            raise SystemExit("桶 %s 没有可用的 abGroups。" % b["id"])
        a["abTest"] = ab_test
        if abg:
            a["abGroups"] = abg
        if b.get("distributionList"):
            a["distributionList"] = b["distributionList"]
        audiences.append(a)

    first = d["buckets"][0]
    order = {
        "businessLine": t["businessLine"],
        "taskGroup": t["taskGroup"],
        "taskName": naming.audience_task_name(camp, first),
        "channel": t["channel"],
        "channelSizeId": t["channelSizeId"],
    }
    if t.get("abGroups"):
        order["abGroups"] = t["abGroups"]
    if "abTest" in t:
        order["abTest"] = t["abTest"]
    if not t.get("price"):
        raise SystemExit(
            "活动定义缺 price：**计费价格不再固定**（2026-09-22 定），"
            "写 YAML 前先问用户当期计费价格，填进活动定义后再跑生成器。")
    order["price"] = t["price"]
    order["deliveryDate"] = t["deliveryDate"]
    if t.get("distributionList"):
        order["distributionList"] = t["distributionList"]
    order["exposureCaps"] = t["exposureCaps"]
    return {
        "version": 1,
        "adType": "blog-page-t0",
        "label": naming.campaign_label(camp, len(d["buckets"])),
        "controls": dict(CONTROLS, username=username),
        "campaign": {
            "brand": camp["brand"],
            "owner": camp["owner"],
            "namePrefix": camp["namePrefix"],
            "taskGroupName": camp["taskGroupName"],
            "activityLink": camp["activityLink"],
        },
        "audiences": audiences,
        "taskOrder": order,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--def", required=True, dest="def_path", help="活动定义 YAML")
    ap.add_argument(
        "--username",
        default=None,
        help="资源用户名；省略时读取 .local/operator.json 中的 ad_username",
    )
    ap.add_argument("--out", default=None, help="输出 YAML（默认 activities/{活动}/{前缀}.yaml）")
    a = ap.parse_args()

    d = yaml.safe_load(Path(a.def_path).read_text(encoding="utf-8"))
    out = Path(a.out) if a.out else Path(a.def_path).resolve().parent / ("%s.yaml" % naming.require_prefix(d["campaign"]))
    data = build(d, username=resolve_username(a.username))
    # 产出即验证：同一个契约检查器，坏 YAML 根本进不了 activities/
    errs = campaign.validate(data)
    if errs:
        raise SystemExit("生成的整活动 YAML 不合契约（未写出）：\n  - " + "\n  - ".join(errs))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("OK wrote", out)


if __name__ == "__main__":
    main()
