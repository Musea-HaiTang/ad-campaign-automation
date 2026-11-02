# -*- coding: utf-8 -*-
"""想法池 ↔ 已建批次 的一致性自检（只读、离线、秒级、不开浏览器）。

为什么有它（2026-10-16 立）：池子里的「在跑」标记是从**角度**那一维贴的，而读的人按**文案**读——
KIRO D 桶 `D2-b/D4-b/D5-b` 标着「在跑」，实际 D `-6` 建的是同角度的**直给版**；C 桶 `C9-b` 标「在跑」，
C `-9` 却根本没建它。后台资源名（`…D类 · 对照-6`）与池子行号（`D2-b`）是两套编号、
中间**没有任何自动对照**，所以错位的行能一直躺着，直到撞上。

查四条：
  ① **假在跑**：标了「在跑」，但这条文案从没被任何批次建过；
  ② **该删没删**：没标「在跑」，但这条文案已经在某批里建过（池子只放"还没上过的"）；
  ③ **存量提示**：各桶还没上过的文案条数（≤5 条 → 按口径该轮到"全桶统一补货"）；
  ④ **验证位结构**：未投角度必须有 1 条「首测」+ 1 条「补验」；一条已投掉后，允许保留单条残组等待复盘。

用法：`.venv\\Scripts\\python.exe -u automation/scripts/check_pool.py [--only 活动名]`
退出码：0 = 没有问题；1 = 有问题（只报，不改任何文件）。
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign as campaign_mod  # noqa: E402
import workspace_repo as repo  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TITLE_RE = re.compile(r"标题：`([^`]+)`")
ROLES = ("首测", "补验", "备选")
STYLES = ("对仗", "化用", "借鉴诗词")


def parse_rows(text, default_bucket="(本池)"):
    """池子文件 → 文案行（只认表格行；表头与分隔行自动跳过）。

    多产品活动的池子**一个产品一份**、表里没有「桶」列 → `default_bucket` 兜底（传文件名）。
    """
    rows, header, angle = [], None, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("### "):
            angle = line[4:].strip()
            continue
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:          # 第一行表格行 = 表头，用来定位「桶 / 一句话假设」两列
            header = cells
            continue
        if len(cells) < 3 or cells[0] in ("#", ""):
            continue
        m = TITLE_RE.search(line)
        if not m:
            continue
        bi = next((i for i, c in enumerate(header) if c == "桶"), None)
        hi = next((i for i, c in enumerate(header) if "假设" in c), None)
        hyp = cells[hi] if hi is not None and hi < len(cells) else ""
        role = next((x for x in ROLES if "**%s**" % x in hyp), None)
        style = next((x for x in STYLES if "**%s" % x in hyp), None)
        # ⚠ 只认加粗的 `**在跑**`（而不是"在跑"这两个字）——2026-10-16 踩到：
        # 说明文字里写"实际在跑的是直给版"也会被旧写法误判成在跑。
        rows.append({"id": cells[0],
                     "bucket": cells[bi] if bi is not None and bi < len(cells) else default_bucket,
                     "angle": angle,
                     "hypothesis": hyp,
                     "role": role,
                     "style": style,
                     "title": m.group(1).strip(),
                     "running": "**在跑**" in hyp or "**在跑**" in line})
    return rows


def built_titles(activity_key, db_path):
    """活动的所有批次里**新建过**的文案标题 → 资源名。"""
    conn = repo.connect(db_path)
    try:
        activity = repo.get_activity(conn, activity_key)
        if activity is None:
            return {}
        rows = conn.execute(
            "SELECT c.title, c.resource_name FROM creative c "
            "JOIN bucket_batch bb ON bb.id=c.batch_id "
            "JOIN bucket b ON b.id=bb.bucket_id WHERE b.activity_id=?",
            (activity["id"],),
        ).fetchall()
        return {
            row["title"].strip(): row["resource_name"]
            for row in rows if (row["title"] or "").strip()
        }
    finally:
        conn.close()


def check(rows, built):
    """池子行 × 已建标题 → 问题清单（①假在跑 ②该删没删）。"""
    issues = []
    for r in rows:
        hit = built.get(r["title"])
        if r["running"] and not hit:
            issues.append("① 假在跑：`%s`（%s 桶）标着「在跑」，但这条文案没有任何批次建过"
                          % (r["id"], r["bucket"]))
        if (not r["running"]) and hit:
            issues.append("② 该删没删：`%s`（%s 桶）没标「在跑」，但 `%s` 已经上过"
                          % (r["id"], r["bucket"], hit))
    return issues


def structure_issues(rows):
    """验证位结构 → 问题清单；没有任何首测/补验标记的角度按 legacy 跳过。"""
    issues = []
    groups = {}
    for row in rows:
        if row.get("angle"):
            groups.setdefault(row["angle"], []).append(row)
    for angle, group in groups.items():
        roles = [r.get("role") for r in group]
        if "首测" not in roles and "补验" not in roles:
            continue
        if len(group) == 1:
            # 池子只放没上过的：首测/补验已投掉一条后，另一条会单独留下等复盘。
            continue
        firsts = [r for r in group if r.get("role") == "首测"]
        seconds = [r for r in group if r.get("role") == "补验"]
        if len(firsts) != 1:
            issues.append("④ 验证位：`%s` 必须有且只有 1 条「首测」，当前 %d 条"
                          % (angle, len(firsts)))
        if len(seconds) != 1:
            issues.append("④ 验证位：`%s` 必须有且只有 1 条「补验」，当前 %d 条"
                          % (angle, len(seconds)))
        for row in group:
            if row.get("role") is None:
                issues.append("④ 验证位：`%s` 的 `%s` 未标「首测 / 补验 / 备选」"
                              % (angle, row["id"]))
        if len(seconds) == 1 and seconds[0].get("style") not in STYLES:
            issues.append("④ 验证位：`%s` 的补验 `%s` 不是风格文案"
                          % (angle, seconds[0]["id"]))
        if len(firsts) == 1 and len(seconds) == 1:
            a, b = firsts[0], seconds[0]
            if a.get("style") in STYLES and a.get("style") == b.get("style"):
                issues.append("④ 验证位：`%s` 首测与补验用了同一风格（%s）"
                              % (angle, a["style"]))
    return issues


def stock(rows):
    """各桶「还没上过」的条数（在跑行不计）。"""
    n = {}
    for r in rows:
        if not r["running"]:
            n[r["bucket"]] = n.get(r["bucket"], 0) + 1
    return n


def pool_files(act_dir):
    act_dir = Path(act_dir)
    one = act_dir / "物料" / "待验证想法.md"
    multi = act_dir / "物料" / "待验证想法"
    files = [one] if one.exists() else []
    if multi.is_dir():
        files += sorted(multi.glob("*.md"))
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只查某个活动（按活动名匹配）")
    ap.add_argument("--db", default=repo.V2_DB, help="数据库 v2 路径")
    args = ap.parse_args()

    total = 0
    for it in campaign_mod.discover(REPO / "activities"):
        if args.only and args.only not in it["id"]:
            continue
        files = pool_files(campaign_mod.activity_dir(it["cfg_path"]))
        if not files:
            continue
        built = built_titles(it["id"], args.db)
        print("== %s（已建文案 %d 条）" % (it["id"], len(built)))
        for f in files:
            rows = parse_rows(f.read_text(encoding="utf-8"), default_bucket=f.stem)
            if not rows:
                continue
            issues = check(rows, built) + structure_issues(rows)
            st = " ｜ ".join("%s %d 条" % (k, v) for k, v in sorted(stock(rows).items()))
            print("   %s：%d 行 ｜ 库里还没上过：%s" % (f.name, len(rows), st))
            for i in issues:
                print("     ⚠ " + i)
            total += len(issues)
    if total:
        print("\nRESULT: 有 %d 个问题（只报，不动任何文件）" % total)
        return 1
    print("\nRESULT: 池子与批次一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
