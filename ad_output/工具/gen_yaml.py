# -*- coding: utf-8 -*-
"""从「活动定义 YAML」生成整活动 YAML（供 automation 执行层脚本消费）。

用法:
    python gen_yaml.py --def activities/{活动}/活动定义.yaml [--out ...]

产出遵循 automation/campaigns/README.md 的字段规范；活动内容全部来自活动定义 YAML，
本脚本只做「装配」，名字一律问 naming 模块要（`automation/scripts/naming.py`，命名规则的唯一实现），
不含任何活动内容。
"""
import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]           # ad_management/
sys.path.insert(0, str(ROOT / "automation" / "scripts"))

import naming  # noqa: E402
import campaign  # noqa: E402

# 类型固定项（controls）：同一广告位类型基本不变
CONTROLS = {
    "channelType": "页面类",
    "channel": "PC-博客-详情页-相关推荐T0",
    "materialPath": ["静态广告", "信息流", "文本"],
    "defaults": {"businessLine": "企业服务事业部", "isPopup": False,
                 "adClient": "广告", "closeBtnColor": "浅色"},
    "fields": {
        "title": {"placeholder": "请输入广告标题"},
        "summary": {"placeholder": "请输入广告摘要", "type": "textarea"},
        "link": {"placeholder": "请输入点击链接"},
    },
}


def build(d):
    camp = d["campaign"]
    sub = d["subBusinessLine"]
    t = d["taskOrder"]
    naming.require_prefix(camp)   # 命名前缀必填，缺了在这里就炸，别带着错名字往下走

    audiences = []
    for b in d["buckets"]:
        resources = []
        for c in b["copies"]:
            r = {
                "role": c["role"],
                "name": naming.resource_name(camp, b, c["label"]),
                "title": c["title"],
                "summary": c["summary"],
            }
            # 飘红词（可选；字段契约见 automation/campaigns/README.md 的 RESOURCE.highlight）：
            # 只能填一个表达，必须字面出现在标题或摘要里——没写就不飘红。
            if c.get("highlight"):
                r["highlight"] = c["highlight"]
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
        # 逐桶覆盖项：本桶的 AB 三组资源 / 本桶的用户名单（不写则执行层回落到 taskOrder）
        if b.get("abGroups"):
            a["abGroups"] = b["abGroups"]
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
        "controls": CONTROLS,
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
    ap.add_argument("--out", default=None, help="输出 YAML（默认 activities/{活动}/{前缀}.yaml）")
    a = ap.parse_args()

    d = yaml.safe_load(Path(a.def_path).read_text(encoding="utf-8"))
    out = Path(a.out) if a.out else Path(a.def_path).resolve().parent / ("%s.yaml" % naming.require_prefix(d["campaign"]))
    data = build(d)
    # 产出即验证：同一个契约检查器，坏 YAML 根本进不了 activities/
    errs = campaign.validate(data)
    if errs:
        raise SystemExit("生成的整活动 YAML 不合契约（未写出）：\n  - " + "\n  - ".join(errs))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("OK wrote", out)


if __name__ == "__main__":
    main()
