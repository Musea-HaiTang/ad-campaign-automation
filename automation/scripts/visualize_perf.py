# -*- coding: utf-8 -*-
"""单文件版看板导出：把 `web/static` 的页面 + **台账库**里的数据烤成一个 HTML。

页面本体在 **`web/static/`**（index.html + app.css + app.js），日常看用 **服务版 `web/app.py`**；
这个脚本只管"把页面和这一份数据打包进同一个文件"——**发人 / 归档**用：双击即开、断网可看、能直接发微信。
两边的数据是同一个 `perf_payload.build_payload()`，数字必然一致。

用法：
    python -u automation/scripts/visualize_perf.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml
    ... --out 某处.html                 # 默认 activities/{活动名}/数据/看板/{生成时刻}.html
    ... --db 别的.db                    # 换台账库（默认 activities/_db/投放数据.db）

⚠ 只读：只读本地台账库和整活动 YAML，不连后台（取数那步仍归 `fetch_perf.py`）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign as campaign_mod  # noqa: E402
import perf_db  # noqa: E402
import perf_payload as pp  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "web" / "static"


def log(*a):
    print(*a, flush=True)


def build_single_html(payload):
    """页面骨架 + 内联 CSS/JS + 内嵌数据 → 一个自包含的 HTML 字符串。"""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace('<link rel="stylesheet" href="app.css">', "<style>\n%s\n</style>" % css)
    html = html.replace('<script src="app.js"></script>',
                        "<script>window.__DATA__ = %s;</script>\n<script>\n%s\n</script>" % (data, js))
    return html


def log_summary(p):
    log("---- 分桶（全区间合计：全部工单 / 仅在投）----")
    for b in p["buckets"]:
        a = pp.totals(p, b["id"], "all")
        i = pp.totals(p, b["id"], "investing")
        log("  [%s] 全部：曝光 %8s | 点击 %4d | 工单 %d   ｜ 仅在投：曝光 %8s | 点击 %4d | 工单 %d"
            % (b["id"], format(a["e"], ","), a["c"], len(a["orders"]),
               format(i["e"], ","), i["c"], len(i["orders"])))
    log("---- 三套文案（累计）----")
    for t in p["resources"]:
        log("  %s" % t["task"])
        for g in t["groups"]:
            log("    %-6s %-22s 曝光 %8s | 点击 %4d | 点击率 %.2f%%"
                % (g["label"], g["res"], format(g["e"], ","), g["c"],
                   (g["c"] / g["e"] * 100 if g["e"] else 0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="整活动 YAML（按它定位活动目录）")
    ap.add_argument("--db", default=perf_db.DEFAULT_DB, help="台账库路径（默认 activities/_db/投放数据.db）")
    ap.add_argument("--out", default=None, help="输出 HTML（默认 数据/看板/{生成时刻}.html）")
    args = ap.parse_args()

    cfg = campaign_mod.load_or_exit(args.config)
    data_root = Path(campaign_mod.activity_dir(args.config)) / "数据"
    conn = perf_db.connect(args.db)
    if not perf_db.days(conn, cfg["campaign"]["taskGroupName"]):
        raise SystemExit("台账库还没有这个活动的数据（先跑 fetch_perf.py 取数）：%s" % args.db)

    payload = pp.build_payload(cfg, conn, config_path=args.config)
    stamp = payload["generated"].replace(":", "").replace("-", "").replace(" ", "_")
    out = Path(args.out) if args.out else (data_root / "看板" / ("%s.html" % stamp))
    log("单文件看板：%s | 数据源：台账库 %s（%d 天）| 页面取自：%s"
        % (cfg["label"], args.db, len(payload["days"]), STATIC))
    log_summary(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_single_html(payload), encoding="utf-8")
    log("看板已生成：%s（%s 字节）" % (out, out.stat().st_size))
    log("RESULT: OK")


if __name__ == "__main__":
    main()
