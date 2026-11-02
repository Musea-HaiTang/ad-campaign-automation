# -*- coding: utf-8 -*-
"""判定规则（**唯一实现**）：曝光攒到门槛才判点击；**达标 = 实际 CTR >= passCtr（千三）**。

⚠ 达标线算的是**实际点击率**（点击 ÷ 曝光），不是"门槛 × 千三"那个固定击数——
   用户 2026-09-30 定。曝光跑过门槛之后（KIRO 一批 E 桶 9,039 曝光 / 9 击 = 0.10%），
   固定击数（3,000 × 千三 = 9）会把实际不到千三的判成"达标"。

⚠ 未达标时"留谁"：**点击多的优先**（幸存上限：3 资源桶 2 条 / 2 资源桶 1 条）；
   **点击并列时看点击率，再并列看曝光**——用户 2026-10-09 定。以前并列时按读数顺序，
   等于让后台列表谁排前面谁留下（出现过"1 击 / 0.08% 的被下、1 击 / 0.07% 的留下"）。

⚠ 2026-10-21 起，脚本只判断"谁有击、谁可判"；具体走首测 / 补验还是
  摘要小改，由复盘按 `想法池与1000曝光复盘流程.md` 和 `小改流程.md` 决定。

谁在用：
  - `judge_batch.py`：出「留谁 / 下谁 / 下一轮补几条新文案」的清单（命令行 / 定时巡检）；
  - `workspace_payload.py`：把**同一套**结论交给看板（页面那三列：当前曝光 / 门槛 / 建议动作）。

规则只在这里写一次（2026-09-28 收口）：以前这套「门槛 → 有击留、无击下、空位补新文案」的逻辑
只活在 judge_batch 里，看板要用就得抄一遍——抄出来的第二份迟早跟第一份走散。

纯函数：不读文件、不碰库、不连后台（测试见 `tests/test_judging.py`）。
"""
import math


def _rank(x):
    """保留排序键：点击多的优先。**点击并列时看点击率**（用户 2026-10-09 定），再并列看曝光。

    点击率才是判定口径（千三），所以点击打平时该让"同样击数里曝光少的"（= 点击率高的）留下；
    以前并列时保持读数原始顺序，等于让后台列表顺序替人做决定（真实出现过 0.08% 被下、0.07% 留下）。
    """
    exp = x["exposure"] or 0
    return (-x["click"], -(x["click"] / exp if exp else 0.0), -exp)


def judge_one(task_name, spec, pass_ctr, rows):
    """一个桶（一条本批工单）的判定：`rows` = 这条工单的**资源级最新读数**。

    返回字典（键名给页面和清单共用）：
      `exposure` / `click` / `threshold` / `need_click` / `slots`
      `ready`（到门槛没）/ `pass`（达标没）/ `keep` / `drop` / `new_copy`
      `state` / `conclusion`（给人看的两句话，命令行清单直接抄这两句）
    """
    threshold = int(spec["threshold"])
    slots = int(spec["resources"])
    exp = sum(x["exposure"] for x in rows)
    clk = sum(x["click"] for x in rows)
    # 达标点击数按**当次实际曝光**折算（向上取整）；没曝光时退回门槛口径（只是给页面一个数）
    # 用户 2026-09-30 定：达标 = CTR ≥ 千三，固定用"门槛 × 千三"会跟实际曝光脱钩
    need_click = math.ceil(exp * pass_ctr) if exp else math.ceil(threshold * pass_ctr)
    out = {"task_name": task_name, "exposure": exp, "click": clk,
           "threshold": threshold, "slots": slots, "need_click": need_click,
           "ready": False, "pass": False, "keep": [], "drop": [], "new_copy": 0,
           "state": "", "conclusion": ""}
    if exp < threshold:
        out["state"] = "未到门槛（差 %d）" % (threshold - exp)
        out["conclusion"] = "继续观察"                    # 没到门槛只有一个结论：什么都别动
        return out
    out["ready"] = True
    out["pass"] = clk >= need_click
    cap = 2 if slots >= 3 else 1                        # 幸存上限：3 资源桶留 2、2 资源桶留 1
    keep = sorted([x for x in rows if x["click"] > 0], key=_rank)[:cap]
    if out["pass"]:
        # 达标 ≠ 只留一条：留几条**看点击的实际情况**（用户 2026-09-28 定）——
        # 有点击的按点击排序取前 cap 条（A 桶 5 击 + 4 击两条都留，只有一条有击就留一条）；
        # 并列时看点击率（2026-10-09）。
        out["state"] = "**达标**（CTR ≥千三）"
        out["conclusion"] = "转长期单：留有点击的 %d 条，不补新文案" % len(keep)
    else:
        out["state"], out["conclusion"] = "过门槛 · 未达标", "按首测 / 补验 / 摘要小改流程处理"
    out["keep"] = [x["resource_name"] for x in keep]
    out["drop"] = [x["resource_name"] for x in rows if x["resource_name"] not in out["keep"]]
    out["new_copy"] = 0 if out["pass"] else slots - len(keep)
    return out
