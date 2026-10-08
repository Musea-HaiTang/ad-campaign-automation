# -*- coding: utf-8 -*-
"""判定清单：读台账库 + 门槛配置 → 输出「留谁 / 下谁 / 下一轮补几条新文案」。

新判定机制（用户 2026-09-24 定）：工单级**累计曝光**攒到门槛才判点击；达标 = CTR ≥ 千三。
未达标 → 有点击的资源留下（按点击多的优先，受幸存上限约束）、零点击的下线；
幸存资源 + 新文案凑满下一轮（所以**单个资源下线 ≠ 动作**：后台只能整单下线，
实际操作是"新批上线后把老工单下掉"）。

⚠ **只读台账库 + 门槛 yaml，不碰后台、不创建 / 删除任何对象**——下线由用户手动执行。
⚠ 判定看的是「本批次的累计读数」（资源级接口给的就是累计值，最新一条 = 整段累计）。
⚠ 2026-10-08 起**桶独立**：每个桶按**它自己**的当前批（最后一次建批）判，不再有一个全局批次。
   批次选择规则只在 `campaign.bucket_current()` 里写一遍，看板用的是同一份。

用法：
    .venv\\Scripts\\python.exe -u automation/scripts/judge_batch.py --config "activities/火山引擎MediaKit/配置/火山引擎MediaKit-hang.yaml"
    ... --write     # 同时把清单追加到 {活动目录}/数据/判定/{日期}_{批次}.md
    ... --todo      # 覆盖写 {活动目录}/数据/判定/待办.md（一眼扫的那份；定时巡检用）
    # 结尾永远打印一行 `STATUS: 巡检 17:12 ｜ 批次 -7 ｜ A 0/0 · … ｜ 可判：…`
    # —— 定时巡检**原样抄这一行**当结尾状态，别再让模型自己编（2026-09-28）
"""
import argparse
import datetime
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 跟 csdn_ui / fetch_perf 一致：控制台别乱码

import campaign  # noqa: E402
import judging   # noqa: E402
import perf_db   # noqa: E402
from judging import bucket_of, next_batch   # noqa: F401（老调用方还在用 jb.bucket_of / jb.next_batch）


def load_thresholds(config):
    path = os.path.join(campaign.activity_dir(config), "配置", "判定门槛.yaml")
    if not os.path.exists(path):
        raise SystemExit("找不到门槛配置：%s" % path)
    with io.open(path, encoding="utf-8") as f:
        import yaml
        return yaml.safe_load(f)


def _by_bucket(th, rows):
    """当前读数 → {(桶, 工单名): [读数行]}；工单名取该桶**自己当前批**那个（桶独立，2026-10-08）。"""
    batches, cur = th.get("_batches") or {}, th.get("_cur") or {}
    by_name = {}
    for r in rows:
        by_name.setdefault(r["task_name"] or "", []).append(r)
    tasks = {}
    for bucket, bid in cur.items():
        tname = ((batches.get(bid) or {}).get("orders") or {}).get(bucket)
        rs = by_name.get(tname) if tname else None
        if rs:                       # 没有任何读数 = 这批这桶还没真跑起来（跟以前一样报"无在跑工单"）
            tasks[(bucket, tname)] = rs
    return tasks


def load_thresholds_with_batches(config):
    """门槛配置 + 批次索引 + 每桶当前批（都塞进 th，省得每个函数都多带两个参数）。"""
    th = load_thresholds(config)
    batches = campaign.load_batches(config)
    th["_batches"] = {b["id"]: b for b in batches}
    th["_cur"] = campaign.bucket_current(batches)
    return th


def judge(cfg, th, rows):
    """rows = 最新资源读数（本轮批次）。返回 (lines, actions, 待补新文案数)。

    **判定规则本体在 `judging.judge_one()`**（命令行清单和看板共用一份，别再各写一遍）。
    """
    pass_ctr = float(th.get("passCtr", 0.003))
    tasks = _by_bucket(th, rows)
    batches, cur = th.get("_batches") or {}, th.get("_cur") or {}

    lines = ["## 判定清单 · 各桶独立 · %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
             "",
             "| 桶 | 工单 | 曝光 | 点击 | CTR | 门槛 | 状态 | 结论 |",
             "|---|---|---|---|---|---|---|---|"]
    actions, need_new = [], 0
    for b, spec in sorted(th["buckets"].items()):
        hit = [(k, v) for k, v in tasks.items() if k[0] == b]
        if not hit:
            lines.append("| %s | — | — | — | — | %s | 无在跑工单 | — |" % (b, spec["threshold"]))
            continue
        for (_, tname), rs in hit:
            j = judging.judge_one(tname, spec, pass_ctr, rs)
            ctr = ("%.3f%%" % (j["click"] / j["exposure"] * 100)) if j["exposure"] else "—"
            lines.append("| %s | %s | %d | %d | %s | %s | %s | %s |"
                         % (b, tname, j["exposure"], j["click"], ctr, j["threshold"],
                            j["state"], j["conclusion"]))
            if not j["ready"]:
                continue
            need_new += j["new_copy"]
            actions.append("\n**%s · %s**（曝光 %d / 点击 %d）" % (b, tname, j["exposure"], j["click"]))
            for x in sorted(rs, key=lambda x: -x["click"]):
                mark = "保留" if x["resource_name"] in j["keep"] else "**下**"
                actions.append("  - %s ｜ %d 曝光 / %d 击 → %s"
                               % (x["resource_name"], x["exposure"], x["click"], mark))
            if j["pass"]:
                actions.append("  → 该桶**达标**：停测试，只留上面标「保留」的那 %d 条作长期单（整单下线后按单资源重挂）"
                               % len(j["keep"]))
            else:
                nxt = next_batch(((batches.get(cur.get(b)) or {}).get("suffix") or ""))
                actions.append("  → 下一轮（%s）＝ %d 条幸存 + **%d 条新文案**"
                               % (nxt, len(j["keep"]), j["new_copy"]))
                actions.append("  → 新批上线后再把 `%s` 下线（后台只能整单下线，先下会断流）" % tname)
    return lines, actions, need_new


def judge_rows(th, rows):
    """本批每个桶的判定结果（结构化，一行一个桶）——待办 / 状态行 / 清单都从这里出。"""
    out = []
    for b, spec in sorted(th["buckets"].items()):
        hit = [(k, v) for k, v in _by_bucket(th, rows).items() if k[0] == b]
        if not hit:
            out.append({"bucket": b, "task": None, "state": "本批没有在跑工单", "conclusion": "—"})
            continue
        for (_, tname), rs in hit:
            j = judging.judge_one(tname, spec, float(th.get("passCtr", 0.003)), rs)
            j["bucket"], j["task"] = b, tname      # 判定结果只有 task_name，这里统一补上 bucket/task
            out.append(j)
    return out


def _short(name):
    """长资源名取最后一段：`…A类 · 对照-4` → `对照-4`。"""
    return str(name).rsplit(" · ", 1)[-1]


def todo_text(th, rows):
    """「一眼扫」的待办（覆盖写 数据/判定/待办.md）：批次一行 + 每桶一行；没到门槛就写「无」。

    以前这份是**定时任务的提示词手写**的——模型一跑偏格式就乱；现在由脚本生成，谁都能跑。
    """
    out = ["各桶独立 ｜ 巡检 %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M")]
    ready = []
    for j in judge_rows(th, rows):
        if not j["task"]:
            out.append("- %s：本批没有在跑工单" % j["bucket"])
            continue
        out.append("- %s：曝光 %d / 门槛 %d · 点击 %d · %s · %s"
                   % (j["bucket"], j["exposure"], j["threshold"], j["click"],
                      j["state"].replace("**", ""), j["conclusion"]))
        if j["ready"]:
            keep = "、".join(_short(x) for x in j["keep"]) or "（都没有点击）"
            ready.append("- %s：留 %d 条（%s）；下一轮补 %d 条新文案"
                         % (j["bucket"], len(j["keep"]), keep, j["new_copy"]))
    out.append("")
    out += (["可判："] + ready) if ready else ["无（各桶都没到门槛）"]
    return "\n".join(out) + "\n"


def status_line(th, rows):
    """定时巡检结尾那一行（**机器生成**，模型原样抄，别自己编）：

    `巡检 17:12 ｜ 批次 -7 ｜ A 0/0 · B 0/0 · C 0/0 · D 0/0 · E 0/0 ｜ 可判：无`
    """
    parts, ready = [], []
    for j in judge_rows(th, rows):
        if not j["task"]:
            parts.append("%s —" % j["bucket"])
            continue
        parts.append("%s %d/%d" % (j["bucket"], j["exposure"], j["click"]))
        if j["ready"]:
            ready.append("%s（%s → %s）" % (j["bucket"], j["state"].replace("**", ""), j["conclusion"]))
    return "巡检 %s ｜ 各桶独立 ｜ %s ｜ 可判：%s" % (
        datetime.datetime.now().strftime("%H:%M"), " · ".join(parts),
        "；".join(ready) if ready else "无")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True,
                    help="活动的整活动 YAML（用来定位活动目录）；判哪个批次由脚本按每个桶的最后一次建批自己推")
    ap.add_argument("--write", action="store_true", help="把清单追加到 数据/判定/{日期}_{批次}.md")
    ap.add_argument("--todo", action="store_true",
                    help="覆盖写 数据/判定/待办.md（一眼扫的那份；定时巡检用）")
    args = ap.parse_args()

    th = load_thresholds_with_batches(args.config)
    cfg = campaign.load_or_exit(args.config)
    conn = perf_db.connect()
    rows = perf_db.latest_resource_readings(conn, cfg["campaign"]["taskGroupName"])
    lines, actions, need_new = judge(cfg, th, rows)

    text = "\n".join(lines)
    if actions:
        text += "\n\n### 逐条动作" + "\n".join(actions)
    text += "\n\n**下一轮需要新写：%d 条文案**" % need_new
    print(text)

    if args.write:
        d = os.path.join(campaign.activity_dir(args.config), "数据", "判定")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "%s_各桶.md" % datetime.date.today().isoformat())
        with io.open(p, "a", encoding="utf-8") as f:
            f.write("\n\n" + text + "\n")
        print("\n已追加：%s" % p)

    if args.todo:
        d = os.path.join(campaign.activity_dir(args.config), "数据", "判定")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "待办.md")
        with io.open(p, "w", encoding="utf-8") as f:      # 覆盖写：永远只有最新状态
            f.write(todo_text(th, rows))
        print("\n待办已覆盖写：%s" % p)

    print("\nSTATUS: %s" % status_line(th, rows))


if __name__ == "__main__":
    main()
