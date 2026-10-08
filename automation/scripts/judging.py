# -*- coding: utf-8 -*-
"""判定规则（**唯一实现**）：曝光攒到门槛才判点击；**达标 = 实际 CTR >= passCtr（千三）**。

⚠ 达标线算的是**实际点击率**（点击 ÷ 曝光），不是"门槛 × 千三"那个固定击数——
   用户 2026-09-30 定。曝光跑过门槛之后（KIRO 一批 E 桶 9,039 曝光 / 9 击 = 0.10%），
   固定击数（3,000 × 千三 = 9）会把实际不到千三的判成"达标"。

谁在用：
  - `judge_batch.py`：出「留谁 / 下谁 / 下一轮补几条新文案」的清单（命令行 / 定时巡检）；
  - `perf_payload.py`：把**同一套**结论交给看板（页面那三列：当前曝光 / 门槛 / 建议动作）。

规则只在这里写一次（2026-09-28 收口）：以前这套「门槛 → 有击留、无击下、空位补新文案」的逻辑
只活在 judge_batch 里，看板要用就得抄一遍——抄出来的第二份迟早跟第一份走散。

纯函数：不读文件、不碰库、不连后台（测试见 `tests/test_judge_batch.py`，两个入口共用一套断言）。
"""
import math
import re


def bucket_of(task_name):
    """工单名 → 桶 id（`…-A类` → `A`）；认不出来返回空串。"""
    m = re.search(r"-([A-Z])类", task_name or "")
    return m.group(1) if m else ""


def next_batch(batch):
    """批次后缀 +1：`-6` → `-7`。

    名字里的数字是"第几批"（-4 → -5 → -6，**越大越新**），所以是**绝对值 +1**、不是整数 +1——
    写成 `str(int(batch) + 1)` 会得到 `-5`（指向上一批，而且那一批已经下过线了）。
    """
    tail = str(batch or "").lstrip("-")
    if not tail.isdigit():
        return "?"
    return ("-" if str(batch or "").startswith("-") else "") + str(int(tail) + 1)


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
    keep = sorted([x for x in rows if x["click"] > 0], key=lambda x: -x["click"])[:cap]
    if out["pass"]:
        # 达标 ≠ 只留一条：留几条**看点击的实际情况**（用户 2026-09-28 定）——
        # 有点击的按点击排序取前 cap 条（A 桶 5 击 + 4 击两条都留，只有一条有击就留一条）。
        out["state"] = "**达标**（CTR ≥千三）"
        out["conclusion"] = "转长期单：留有点击的 %d 条，不补新文案" % len(keep)
    else:
        out["state"], out["conclusion"] = "过门槛 · 未达标", "有击留、无击下，补新文案"
    out["keep"] = [x["resource_name"] for x in keep]
    out["drop"] = [x["resource_name"] for x in rows if x["resource_name"] not in out["keep"]]
    out["new_copy"] = 0 if out["pass"] else slots - len(keep)
    return out
