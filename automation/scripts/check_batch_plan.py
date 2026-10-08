# -*- coding: utf-8 -*-
"""批次 YAML 计划自检（**离线**：只读 YAML + naming，不碰后台、不开浏览器）。

为什么有它——2026-10-08 火山九批 / KIRO 四批真实踩到三条，全在**2 资源桶**上：
  ① **权重按资源数算**：生成器按 3 资源的 `34/33/33` 给 2 资源桶填了 `34/33`（= 67%），
     后台直接拒：`资源流量占比累计为67%，请将流量占比总量调整为100%`；2 资源桶正确值是 **50/50**。
  ② **AB 行位次不能跳**：后台要求从 `对照组 → 实验组1 → 实验组2` 顺序填满，
     2 资源桶只能 `对照组 + 实验组1`；把实验组1 留空会报 `实验组1资源ID不能为空`。
  ③ **资源名的角色段要和它所在的 AB 行一致**（`对照` / `实验1` / `实验2`）——复盘靠名字认谱系，
     名字与槽位错位会让跨批对比看错对象。

用法：
    .venv\\Scripts\\python.exe -u automation/scripts/check_batch_plan.py --config activities/火山引擎MediaKit/调整/2026-10-08-九批.yaml
退出码：0 = 全过；1 = 有错（错**全列出来**，不早退——一次看全比来回跑省事）。
"""
import argparse
import datetime
import io
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 控制台别乱码（跟 judge_batch / fetch_perf 一致）

import naming  # noqa: E402

LABELS = ["对照组", "实验组1", "实验组2"]
ROLE_OF_LABEL = {"对照组": "对照", "实验组1": "实验1", "实验组2": "实验2"}
ROLE_OF_FIELD = {"control": "对照", "experiment1": "实验1", "experiment2": "实验2"}
WEIGHTS = {2: [50, 50], 3: [34, 33, 33]}          # 按资源条数算，别用固定序列


def role_of(name):
    """资源名 `…A类 · 实验1-9` → `实验1`（取最后一段、认前缀）。"""
    tail = str(name or "").split(" · ")[-1]
    for role in ("对照", "实验1", "实验2"):
        if tail.startswith(role):
            return role
    return ""


def check_audience(a, camp):
    """一个桶：返回错误列表（空 = 过）。"""
    errs = []
    bid = a.get("id", "?")
    abg = a.get("abGroups") or []
    if not abg:
        return ["%s 桶：abGroups 为空（工单的 AB 组没写，会回落到全局兜底）" % bid]

    expect_labels = LABELS[:len(abg)]
    got_labels = [g.get("label") for g in abg]
    if got_labels != expect_labels:
        errs.append("%s 桶：AB 行位次必须是 %s（不能跳行），现在是 %s"
                    % (bid, "/".join(expect_labels), "/".join(str(x) for x in got_labels)))

    want_w = WEIGHTS.get(len(abg))
    got_w = [g.get("weightPct") for g in abg]
    if want_w and got_w != want_w:
        total = sum(x for x in got_w if isinstance(x, int))
        errs.append("%s 桶：%d 条资源的流量占比必须是 %s（合计 100），现在是 %s（合计 %d）"
                    % (bid, len(abg), "/".join(map(str, want_w)),
                       "/".join(str(x) for x in got_w), total))
    elif not want_w:
        errs.append("%s 桶：AB 组数 %d 不支持（只能 2 或 3）" % (bid, len(abg)))

    for g in abg:                                  # 名字的角色段 ↔ 所在 AB 行
        want_role = ROLE_OF_LABEL.get(g.get("label"), "")
        got_role = role_of(g.get("resource"))
        if want_role and got_role != want_role:
            errs.append("%s 桶：AB 行「%s」绑的是 `%s`（角色 `%s`）——名字角色段要和槽位一致"
                        % (bid, g.get("label"), g.get("resource"), got_role or "认不出"))

    if not a.get("nameSuffix"):
        errs.append("%s 桶：缺 nameSuffix（重投批次必须带后缀，否则后台重名建不了）" % bid)
        return errs

    want_task = naming.bucket_name(camp, a)        # 名字只认 naming（唯一实现）
    if (a.get("taskName") or "").strip() != want_task:
        errs.append("%s 桶：taskName 应为 `%s`，现在是 `%s`" % (bid, want_task, a.get("taskName")))

    new_names = []
    for r in a.get("resources") or []:
        role = ROLE_OF_FIELD.get(r.get("role"), "")
        if not role:
            errs.append("%s 桶：资源 `%s` 的 role=%r 不认识" % (bid, r.get("name"), r.get("role")))
            continue
        want = naming.resource_name(camp, a, role)
        if r.get("name") != want:
            errs.append("%s 桶：新建资源名应为 `%s`，现在是 `%s`" % (bid, want, r.get("name")))
        new_names.append(r.get("name"))

    refs = [g.get("resource") for g in abg]
    for n in new_names:                            # 新建的必须被引用，否则是孤儿
        if n not in refs:
            errs.append("%s 桶：新建资源 `%s` 没被任何 AB 行引用（会变成孤儿资源）" % (bid, n))
    row_role = {g.get("resource"): ROLE_OF_LABEL.get(g.get("label"), "") for g in abg}
    for r in a.get("resources") or []:             # role 字段要和它所在行一致
        want_role = row_role.get(r.get("name"), "")
        if want_role and ROLE_OF_FIELD.get(r.get("role")) != want_role:
            errs.append("%s 桶：资源 `%s` 的 role=%s 与槽位「%s」不符"
                        % (bid, r.get("name"), r.get("role"), want_role))
    return errs


def check_task_order(t):
    errs = []
    price = t.get("price")
    if not isinstance(price, int) or price <= 0:
        errs.append("taskOrder.price 必须由用户当轮给出（正整数），现在是 %r" % (price,))
    dd = t.get("deliveryDate") or {}
    for k in ("start", "end"):
        try:
            datetime.date.fromisoformat(str(dd.get(k)))
        except Exception:
            errs.append("taskOrder.deliveryDate.%s 不是 YYYY-MM-DD：%r" % (k, dd.get(k)))
    if dd.get("start") and dd.get("end") and str(dd["start"]) > str(dd["end"]):
        errs.append("taskOrder.deliveryDate 起点晚于终点：%s → %s" % (dd["start"], dd["end"]))
    if dd.get("timeStart") is None or dd.get("timeEnd") is None:
        errs.append("taskOrder.deliveryDate 缺时段（timeStart/timeEnd）")
    if not t.get("taskGroup"):
        errs.append("taskOrder.taskGroup 缺失（后台要按它选任务组）")
    return errs


def check_doc(d):
    camp = d["campaign"]
    errs = check_task_order(d.get("taskOrder") or {})
    for a in d.get("audiences") or []:
        errs += check_audience(a, camp)
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="批次 YAML（activities/{活动}/调整/*.yaml）")
    args = ap.parse_args()
    with io.open(args.config, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    for a in d.get("audiences") or []:
        abg = a.get("abGroups") or []
        print("  %s 桶：%d 条资源 ｜ 槽位 %s ｜ 占比 %s"
              % (a.get("id"), len(abg), "/".join(g.get("label", "?") for g in abg),
                 "/".join(str(g.get("weightPct")) for g in abg)))
    errs = check_doc(d)
    if errs:
        print("\n✗ 自检不通过（%d 条）：" % len(errs))
        for e in errs:
            print("  - %s" % e)
        return 1
    print("\n✓ 自检通过：权重 / 位次 / 名字↔槽位 / 工单字段 都没问题（%d 桶）"
          % len(d.get("audiences") or []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
