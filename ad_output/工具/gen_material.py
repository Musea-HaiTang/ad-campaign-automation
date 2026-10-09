# -*- coding: utf-8 -*-
"""从「活动定义 YAML」生成投放物料 HTML（套书卷墨色模板）。

用法:
    python gen_material.py --def activities/{活动}/活动定义.yaml [--out ...]

⚠ **只在活动首投用**（用户 2026-10-09 定）：HTML 的用途是"给人看一版排好版的文案稿"，
  只有新活动第一次定桶与文案时才出；**复盘重投不再出 HTML**（交付 = 复盘报告里的定稿文案 +
  `物料/文案自审/文案自审记录-{日期}.md`）。复盘批次若历史上出过 HTML，归 `物料/投放物料/` 存档。

数据/代码分离：活动内容（标题/分桶/关键词/文案）全部来自活动定义 YAML，
本脚本只做「套模板 + 填空 + 占位符校验」，不含任何活动内容。
名字（桶名/物料文件名）不在这里拼，一律问 naming 模块要（`automation/scripts/naming.py`）。

桶数由数据决定：模板里只有**一个**桶块（`<!-- BUCKET:START -->`…`<!-- BUCKET:END -->`），
本脚本按 `len(buckets)` 复制 N 份 → 4–7 类都成立（不再要求恰好 7 类）。
"""
import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]           # ad_management/
sys.path.insert(0, str(ROOT / "automation" / "scripts"))

import naming  # noqa: E402

TPL = ROOT / "ad_output" / "投放物料" / "模板" / "书卷墨色投放物料模板.html"

# 模板里的桶块：生成器把这一整段（含标记）换成「按桶数复制 N 份」的成品
BUCKET_BLOCK = re.compile(r"<!-- BUCKET:START[^>]*-->[ \t]*\n?(.*?)<!-- BUCKET:END[^>]*-->", re.S)

# 纪律条 = 全局红线（固定注入）+ 用户给的活动特例。
# 全局红线只有这一条，权威源是 流程文档/CSDN广告投放自动化流程.md §0。
GLOBAL_REDLINE = "忌「翻墙」字样（合规红线，全部文案通用）"


def build_rule_text(act):
    """纪律条内容：全局红线 + `activity.ruleText`（= 用户给的活动特例，可空）。

    活动特例只由用户给出（流程文档 §3）：这里不做任何揣测、不塞默认文案，
    用户没给就只渲染红线。
    """
    extra = (act.get("ruleText") or "").strip().rstrip("。")
    return ("%s；%s。" % (GLOBAL_REDLINE, extra)) if extra else GLOBAL_REDLINE + "。"


def render_bucket(block, camp, b, i):
    """把模板桶块渲染成第 i 个桶（{{GP}} = G1/G2/…，其余占位符不带序号）。"""
    m = {
        "GP": "G%d" % i,
        "LETTER": b["id"],
        "NAME": b["name"],
        "AUDIENCE": b["audience"],
        "TASKNAME": naming.bucket_name(camp, b),
        "KEYWORDS": b["keywords"],
        "KW_NOTE": b.get("kwNote", ""),
    }
    for c, suff in zip(b["copies"], ["A", "B", "C"]):
        m["TITLE_" + suff] = c["title"]
        m["DESC_" + suff] = c["summary"]
        m["HOOK_%s_KEY" % suff] = c.get("hookKey", "")
        m["HOOK_%s_NOTE" % suff] = c.get("hookNote", "")
    for k, v in m.items():
        block = block.replace("{{%s}}" % k, str(v))
    return block


def build(d, out_path):
    act = d["activity"]
    camp = d["campaign"]
    name_prefix = naming.require_prefix(camp)
    buckets = d["buckets"]

    html = TPL.read_text(encoding="utf-8")
    head = {
        "ACTIVITY_TITLE": act["title"],
        "ACTIVITY_SUBTITLE": act["subtitle"],
        "TASK_GROUP_NAME": name_prefix,
        "ACTIVITY_RULE_TEXT": build_rule_text(act),
        "END_SEAL": act.get("endSeal", ""),
    }
    for k, v in head.items():
        html = html.replace("{{%s}}" % k, str(v))

    m = BUCKET_BLOCK.search(html)
    if not m:
        raise SystemExit("模板缺少桶块标记：需要 <!-- BUCKET:START --> … <!-- BUCKET:END -->")
    rendered = "".join(render_bucket(m.group(1), camp, b, i) for i, b in enumerate(buckets, 1))
    html = html[:m.start()] + rendered + html[m.end():]

    # 校验：剔除 HTML 注释后不得有残留占位符
    no_comment = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    leftovers = re.findall(r"\{\{[^}]+\}\}", no_comment)
    if leftovers:
        raise SystemExit("未替换占位符: " + ", ".join(sorted(set(leftovers))))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--def", required=True, dest="def_path", help="活动定义 YAML")
    ap.add_argument("--out", default=None,
                    help="输出 HTML（默认 activities/{活动}/物料/投放物料/{前缀}-{N}类投放物料.html）")
    a = ap.parse_args()

    d = yaml.safe_load(Path(a.def_path).read_text(encoding="utf-8"))
    if a.out:
        out = Path(a.out)
    else:
        # 定义文件通常落在 `配置/`：上跳一层才是活动目录（老实现少跳一层，会把成品写进 `配置/物料/`）
        defp = Path(a.def_path).resolve()
        act_dir = defp.parent.parent if defp.parent.name == "配置" else defp.parent
        out = act_dir / "物料" / "投放物料" / \
            naming.material_file_name(d["campaign"], len(d["buckets"]))
    p = build(d, out)
    print("OK wrote", p)


if __name__ == "__main__":
    main()
