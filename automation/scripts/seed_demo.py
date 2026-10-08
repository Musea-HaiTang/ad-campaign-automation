# -*- coding: utf-8 -*-
"""造**假数据**把看板点亮（演示 / 新人上手用）——不连后台、不登录、不碰真实台账库。

按 `activities/_示例活动/` 的两份 YAML（首批 + 二批）生成一个**假台账库**，让看板能显示：
  - 分桶统计：一行 = 该桶**最新那个任务**（A 在二批、B 还在首批 → 演示"桶独立"）
  - 批次之间：该桶的批次史（最新 → 最老）
  - 三条文案对比弹窗：A 过门槛 → 胜出特写；B 没到门槛 → 记分卡
  - 待复盘角标：A 的当前批攒够曝光还没复盘 → 角标会出现

用法：
    .venv\\Scripts\\python.exe automation/scripts/seed_demo.py
    .venv\\Scripts\\python.exe web/app.py --db activities/_db/示例看板.db --port 8788
    浏览器打开 http://127.0.0.1:8788

⚠ 默认只写 `activities/_db/示例看板.db`（**不是**真实库 `投放数据.db`，脚本会拒绝写真实库）。
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import campaign   # noqa: E402
import perf_db    # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEMO_CFG = os.path.join(REPO, "activities", "_示例活动", "配置", "示例活动-hang.yaml")
DEMO_DB = os.path.join(REPO, "activities", "_db", "示例看板.db")

# 假数据按 (批次 id, 桶) 给：`day` = 每天(曝光, 点击)，`res` = 每条资源(曝光, 点击)。
# ⚠ 看板有**两个口径**：判定看**资源级累计**（res 之和），「批次之间」看**按天事实**（day × 天数）——
#   两边要讲同一个故事，所以这里的数是配着填的。
FAKE = {
    # A 二批：资源累计 3,350（过门槛 3,000）· 3 击 < 达标线 11 击 → 过门槛·未达标
    ("2026-01-08-二批", "A"): {"day": (560, 0), "res": [(1700, 2), (1650, 1)]},
    # A 首批：2,270，没到门槛（历史批次，页面上看得到它的点击）
    ("示例活动-hang", "A"): {"day": (380, 0), "res": [(760, 1), (750, 0), (760, 0)]},
    # B 首批：620 < 门槛 1,000 → 未到门槛（弹窗走「记分卡」）
    ("示例活动-hang", "B"): {"day": (105, 0), "res": [(320, 0), (300, 1)]},
}
FALLBACK = {"day": (100, 0), "res": [(300, 0)]}
NDAYS = 6
SLOTS = ["对照组", "实验组1", "实验组2"]
D0 = datetime.date(2026, 1, 5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEMO_CFG, help="示例活动的整活动 YAML（默认 _示例活动/配置）")
    ap.add_argument("--out", default=DEMO_DB, help="假台账库写到哪（默认 activities/_db/示例看板.db）")
    args = ap.parse_args()

    if os.path.abspath(args.out) == os.path.abspath(perf_db.DEFAULT_DB):
        raise SystemExit("别往真实台账库写！换个 --out（默认就是 示例看板.db）")
    cfg = campaign.load(args.config)
    aid = cfg["campaign"]["taskGroupName"]
    batches = campaign.load_batches(args.config)
    if not batches:
        raise SystemExit("这份 YAML 没扫出批次：%s" % args.config)
    cur = campaign.bucket_current(batches)          # 每个桶的最后一次建批（跟看板同一份口径）

    if os.path.exists(args.out):
        os.remove(args.out)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    conn = perf_db.connect(args.out)
    perf_db.upsert_activity(conn, aid, os.path.basename(os.path.dirname(os.path.dirname(args.config))),
                            cfg.get("label") or aid)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tasks, daily, readings = [], [], []
    for bi, b in enumerate(batches):
        for bucket_id, tname in sorted((b.get("orders") or {}).items()):
            tid = str(9000000 + bi * 100 + ord(bucket_id[0]))
            tasks.append({"id": tid, "name": tname,
                          "state": "进行中" if cur.get(bucket_id) == b["id"] else "下线"})
            fake = FAKE.get((b["id"], bucket_id), FALLBACK)
            day_e, day_c = fake["day"]
            for k in range(NDAYS):
                day = (D0 + datetime.timedelta(days=k)).isoformat()
                e = day_e + (k % 3) * 9                     # 别每天一模一样，看着像真数据
                daily.append((tid, day, e, day_c, int(e * 0.6), int(day_c * 0.6), now))
            names = [nm for nm, item in (b.get("copy") or {}).items()
                     if str(item.get("bucket")) == bucket_id]
            for ri, rname in enumerate(names):
                re_, rc = (fake["res"][ri] if ri < len(fake["res"]) else (300, 0))
                readings.append((tid, "%s-%d" % (tid, ri), now, aid, tname,
                                 SLOTS[ri % 3], rname, re_, rc))
    perf_db.upsert_tasks(conn, aid, tasks, now)
    perf_db.upsert_daily(conn, daily)
    perf_db.add_resource_readings(conn, readings)
    conn.commit()
    print("假数据已写入：%s" % args.out)
    print("  活动 %s ｜ 工单 %d 条 ｜ 按天 %d 行 ｜ 资源读数 %d 条" %
          (aid, len(tasks), len(daily), len(readings)))
    print("  起看板：.venv\\Scripts\\python.exe web/app.py --db \"%s\" --port 8788" % args.out)


if __name__ == "__main__":
    main()
