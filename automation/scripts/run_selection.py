# -*- coding: utf-8 -*-
"""圈选博文（新数据平台那条路 · 执行层第 3 步的另一种走法）——**只导出 CSV，不建名单**。

在 data.csdn.net（CSDN Data BI 对话式取数）里按「口径提示词 + 关键词组」取数，
让它 COUNT 后走异步全量导出，我们把 CSV 抓下来落成本地文件。

**导出完先看数量**：满意再跑 `run_distribution_ids.py` 把博文 id 灌进分发名单。
两条命令分开，就是为了让你在中间能喊停。

用法：
    .venv\\Scripts\\python.exe -u automation/scripts/run_selection.py ^
        --config "<当前执行 YAML>" ^
        --only D --headed              # 彩排（默认）：只到「导出卡片出现」为止
    ... 同上 + --submit                 # 真导出，落 CSV
    ... 同上 + --refresh                # 本地已有当天 CSV 也强制重取

口径提示词见本文件 `PROMPT`（`--prompt-file` 可换成自己的那份）。
断点账本：activities/{活动}/日志/selection_progress.json（键 = 任务组|桶）。
"""
import csv
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bucket_runner  # noqa: E402
import cli  # noqa: E402
import csdn_ui as ui  # noqa: E402
import workspace_repo as repo  # noqa: E402

CHAT = "https://data.csdn.net/chat"
EXPORT_API = "https://data.csdn.net/api"

# 输入框选择器：SPA 改版时按顺序兜底
COMPOSER = ["div.chat-center-input textarea", "div.chat-composer textarea",
            "div.chat-center-input [contenteditable=true]", "textarea"]
CARD_TIMEOUT_MS = 600000     # 等模型出「确认导出」卡片
JOB_POLL_S = 5               # 轮询导出任务
# 下载超时：大导出（几十万行 / 100MB+）要几分钟才拉完，Playwright 默认 30 秒**必挂**
# （2026-09-29 实测：39.9 万行 105 秒、93.7 万行 165 秒 → 当天两次都是手工按任务号重下的）。
DOWNLOAD_TIMEOUT_MS = 1800000   # 30 分钟
DOWNLOAD_ATTEMPTS = 3           # 失败重试次数；每次重试前重新取任务状态（签名链接会过期）

# 口径提示词（用户 2026-09-21 给的「已验证口径 · 修正版」；--prompt-file 可覆盖）
PROMPT = """## 关键词圈选博文任务（已验证口径 · 修正版）

【表】csdn_dw.dws_media_blog_article_df_v（ClickHouse）

【输出四列】博文id、title、url、点击数（= last_30_days_pv，最近30天PV）

【字段映射】（重要：务必按表中真实列名写 SQL）
| 输出列 | 表字段（真实列名） | 类型 |
|--------|-------------------|------|
| 博文id | article_id | Int64 |
| title  | title | Nullable(String) |
| url    | article_url | Nullable(String) |
| 点击数 | last_30_days_pv | Int64 |

⚠️ 注意：URL 字段的真实列名是 `article_url`，**不是** `url`。
写错会报 `Unknown expression identifier 'url'`（Code: 47）。

【参数区】
- 状态：status = 1（审核通过）
- 流量阈值：last_30_days_pv > 1
- 唯一性：article_id 唯一，无需去重

【命中范围】（任一命中即入选）
- title（标题）
- keyword_ai（关键词）
- intent_tag（意图标签）
- category_one_name / category_two_name / category_three_name（分类标签）

【匹配规则】
- 英文忽略大小写（用 (?i)）
- 中文为子串包含匹配
- 特殊字符转义：. 写成 [.]（如 h[.]264）、- 需转义（如 ffmpeg-python）

【执行流程】
1. 先 COUNT 估量
2. >1000 行 → create_export_job 异步导出（四列固定）；否则 execute_sql 直接取
3. 导出文件名：{主题}_YYYYMMDD

【标准 SQL 模板】
```sql
SELECT article_id, title, article_url, last_30_days_pv
FROM csdn_dw.dws_media_blog_article_df_v
WHERE status = 1
  AND last_30_days_pv > 1
  AND multiMatchAny(
        concat_ws('|', title, keyword_ai, intent_tag, category_one_name, category_two_name, category_three_name),
        ['关键词1', '关键词2', '...'])
ORDER BY last_30_days_pv DESC
```

【兜底】若字段名对不上，先 describe_table 核对再执行，不要硬跑。
"""


def keywords_of(aud):
    """桶的 keywords 字段（逗号分隔一行）→ 列表。"""
    raw = (aud.get("keywordGroup") or {}).get("keywords") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def prompt_of(args):
    """口径提示词：给了 `--prompt-file` 就用它，否则用脚本内的标准口径。"""
    return open(args.prompt_file, encoding="utf-8").read() if args.prompt_file else PROMPT


def csv_path(out_dir, prefix):
    return os.path.join(out_dir, "%s圈选博文_%s.csv" % (prefix, time.strftime("%Y%m%d")))


def summarize(text):
    """CSV 文本 → (博文数, 总点击数, 平均点击数)。

    必须用 csv 模块读：标题里可能带换行，按行切会把一条记录算成两条。
    """
    rows = csv.reader(io.StringIO(text))
    head = next(rows, None)
    if not head:
        return 0, 0, 0.0
    col = head.index("last_30_days_pv") if "last_30_days_pv" in head else len(head) - 1
    n = total = 0
    for row in rows:
        if not row or not row[0].strip():
            continue
        n += 1
        try:
            total += int(row[col])
        except (IndexError, ValueError):
            pass
    return n, total, (total / n if n else 0.0)


def record_selection(activity_key, bucket_key, when, kw_count, n, total, db_path):
    """把一次圈选结果写入数据库。"""
    conn = repo.connect(db_path)
    try:
        activity = repo.get_activity(conn, activity_key)
        if activity is None:
            raise RuntimeError("数据库里没有活动：%s" % activity_key)
        return repo.save_selection_run(
            conn, activity["id"], str(bucket_key), when, kw_count, n, total)
    finally:
        conn.close()


def ask_question(page, keywords, prompt):
    """开一轮对话并发问（不点导出卡片）。抽出来是为了多页并发时复用。"""
    question = (prompt.strip() + "\n\n请严格按上面的口径执行，圈出下面这一组关键词命中的博文：\n"
                + ",".join(keywords))
    ui.goto(page, CHAT)
    box = None
    for sel in COMPOSER:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=15000)
            box = loc
            break
        except Exception:
            continue
    if box is None:
        raise RuntimeError("对话页找不到输入框（当前 url=%s）——data.csdn.net 的登录态会过期，"
                           "先跑 `automation/scripts/wait_login.py --site databi` 重登再来" % page.url)
    box.fill(question)
    send = page.locator("button.chat-send-btn").first
    if send.count():
        send.click()
    else:
        box.press("Enter")
    ui.log("  已发问（%d 个关键词，%d 字）" % (len(keywords), len(question)))


def confirm_and_job(page, s):
    """等「确认导出」卡片 → 点它 → 返回导出任务 id；彩排只等到卡片、不点，返回 None。"""
    confirm = page.locator("text=确认导出").first
    try:
        confirm.wait_for(state="visible", timeout=CARD_TIMEOUT_MS)
    except Exception:
        ui.shot(s, "selection_timeout.png")
        raise RuntimeError("等不到「确认导出」卡片（模型没按口径走？看截图）")
    ui.log("  卡片已出现")
    if s.dry_run:
        ui.log("  彩排：不点确认导出")
        return None

    with page.expect_response(
            lambda r: "/api/export-jobs" in r.url and r.request.method == "POST",
            timeout=120000) as resp:
        confirm.click()
    body = resp.value.json()
    st = body.get("data") if isinstance(body.get("data"), dict) else body
    jid = st.get("id") or st.get("job_id")
    if not jid:
        raise RuntimeError("导出任务响应里没有 id：%s" % str(body)[:200])
    ui.log("  导出任务 %s，等它跑完…" % jid)
    return jid


def job_status(page, jid):
    """查导出任务状态（走页面上下文里的登录态）。"""
    st = page.context.request.get("%s/export-jobs/%s" % (EXPORT_API, jid)).json()
    return st.get("data") if isinstance(st.get("data"), dict) else st


def retry_fetch(fetch, attempts=DOWNLOAD_ATTEMPTS, log=ui.log, what="下载"):
    """跑 `fetch()`；出错就重试，全挂抛 RuntimeError。纯函数（fetch 自己注入），好单测。"""
    for i in range(1, attempts + 1):
        try:
            return fetch()
        except Exception as e:                      # noqa: BLE001 —— 超时/断流都值得重试
            log("  ⚠ 第 %d/%d 次%s失败：%s" % (i, attempts, what, cli.first_line(e)))
            if i == attempts:
                raise RuntimeError("%s失败（已重试 %d 次）：%s" % (what, attempts, e))


def download_csv(page, st, path):
    """按签名链接抓 CSV，落成 UTF-8 带 BOM（Excel 才不乱码）。返回文本。

    超时/断流会**重试**（见 `DOWNLOAD_TIMEOUT_MS` / `retry_fetch`）；重试前重新取一次任务状态，
    因为签名链接会过期。仍失败就报错，提示用 `--job <任务号> --out <路径>` 重下（不重新导出）。
    """
    def fetch():
        if st.get("id"):
            fresh = job_status(page, st["id"])
            if fresh.get("download_url"):
                st["download_url"] = fresh["download_url"]
        return page.context.request.get(st["download_url"], timeout=DOWNLOAD_TIMEOUT_MS).body()

    raw = retry_fetch(fetch)
    text = raw.decode("utf-8-sig")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(text)
    lines = text.splitlines()
    n, total, _ = summarize(text)
    ui.log("  CSV 已落盘：%s" % path)
    ui.log("  表头：%s" % lines[0][:100])
    ui.log("  博文数 %s ｜ 总点击数 %s ｜ 平均 %s"
           % ("{:,}".format(n), "{:,}".format(total), "{:.1f}".format(avg)))
    return text


def export_csv(s, keywords, prompt, path):
    """对话式取数 → 异步导出 → 抓 CSV（UTF-8 带 BOM）。彩排只到卡片出现为止。"""
    page = s.page
    ask_question(page, keywords, prompt)
    jid = confirm_and_job(page, s)
    if jid is None:
        return None

    while True:
        st = job_status(page, jid)
        ui.log("    [%s] %s 行数=%s" % (time.strftime("%H:%M:%S"), st.get("status"), st.get("row_count")))
        if st.get("status") in ("done", "failed", "error"):
            break
        time.sleep(JOB_POLL_S)
    if st.get("status") != "done":
        raise RuntimeError("导出任务失败：%s" % str(st)[:200])
    download_csv(page, st, path)
    return path


def run_parallel(s, auds, args, out_dir, prompt, parallel, activity_key, v2_db):
    """一次开 N 个对话页并发跑（用户 2026-09-28 提：一次开三个没问题）。

    并发的是**等模型出「确认导出」卡片**那一段（单桶实测 40~150 秒）：先把 N 个问题都发出去，
    再轮流看每页卡片出现没有 → 卡片齐了统一点确认 → 交错轮询导出任务 → 各自抓 CSV。
    断点跟串行一致：**本地已有当天 CSV 就跳过**（除非 --refresh），中断后重跑只补缺的桶。
    """
    todo = []
    for a in auds:
        kws = keywords_of(a)
        prefix = args.prefix or "%s_%s桶%d词_" % (time.strftime("%Y-%m-%d"), a["id"], len(kws))
        path = csv_path(out_dir, prefix)
        if os.path.exists(path) and not args.refresh:
            ui.log("[%s] 本地已有 CSV，跳过导出（要重取加 --refresh）" % a["id"])
            continue
        todo.append((a, kws, path))
    if not todo:
        ui.log("没有要导出的桶（当天 CSV 都在了）")
        return []
    done = []
    for i in range(0, len(todo), parallel):
        done += _parallel_chunk(s, todo[i:i + parallel], prompt, activity_key, v2_db)
    return done


def _close_pages(pages):
    for p in pages.values():
        try:
            p.close()
        except Exception:
            pass


def _parallel_chunk(s, chunk, prompt, activity_key, v2_db):
    """一批：N 个桶同时发问 → 重叠等卡片 → 逐页点确认 → 交错轮询导出 → 抓 CSV。"""
    pages = {}
    ui.log("---- 并发批（%d 桶）：%s ----"
           % (len(chunk), "、".join(str(a["id"]) for a, _, _ in chunk)))
    for a, kws, path in chunk:
        aid = str(a["id"])
        page = s.page.context.new_page()
        page.set_default_timeout(ui.DEFAULT_TIMEOUT_MS)
        pages[aid] = page
        ui.log("[%s] %d 个关键词 → %s" % (aid, len(kws), path))
        try:
            ask_question(page, kws, prompt)
        except Exception as e:
            ui.log("[%s] ✗ 发问失败:%s" % (aid, cli.first_line(e)))

    t0 = time.time()
    deadline = t0 + CARD_TIMEOUT_MS / 1000.0
    waiting = [aid for aid in pages]
    while waiting and time.time() < deadline:
        for aid in list(waiting):
            if pages[aid].locator("text=确认导出").first.is_visible():
                ui.log("[%s] 卡片已出现（并发等待 %.0f 秒）" % (aid, time.time() - t0))
                waiting.remove(aid)
        if waiting:
            time.sleep(4)
    for aid in waiting:
        ui.log("[%s] ✗ 等不到「确认导出」卡片（其他桶继续）" % aid)

    if s.dry_run:
        ui.log("  彩排：不点确认导出（%d/%d 张卡片已出现）" % (len(pages) - len(waiting), len(pages)))
        _close_pages(pages)
        return []

    jobs = {}
    for a, kws, path in chunk:
        aid = str(a["id"])
        if aid in waiting:
            continue
        try:
            jid = confirm_and_job(pages[aid], s)
            if jid:
                jobs[aid] = (a, kws, path, jid)
        except Exception as e:
            ui.log("[%s] ✗ 点确认导出失败:%s" % (aid, cli.first_line(e)))

    done = []
    while jobs:
        for aid in list(jobs):
            a, kws, path, jid = jobs[aid]
            try:
                st = job_status(pages[aid], jid)
            except Exception as e:
                ui.log("[%s] ✗ 查导出任务失败:%s" % (aid, cli.first_line(e)))
                del jobs[aid]
                continue
            if st.get("status") not in ("done", "failed", "error"):
                ui.log("[%s] [%s] %s 行数=%s"
                       % (aid, time.strftime("%H:%M:%S"), st.get("status"), st.get("row_count")))
                continue
            if st.get("status") == "done":
                text = download_csv(pages[aid], st, path)
                n, total, avg = summarize(text)
                record_selection(activity_key, aid, time.strftime("%Y-%m-%d %H:%M"),
                                 len(kws), n, total, v2_db)
                ui.log("[%s] 圈选结果已写入数据库" % aid)
                ui.log("[%s] ✅ 建名单：run_distribution_ids.py --csv \"%s\" --config <同一个 YAML> "
                       "--only %s --submit" % (aid, path, aid))
                done.append(aid)
            else:
                ui.log("[%s] ✗ 导出任务失败：%s" % (aid, str(st)[:160]))
            del jobs[aid]
        if jobs:
            time.sleep(JOB_POLL_S)
    _close_pages(pages)
    return done


def do_one(s, camp, aud, args, out_dir, prefix, v2_db):
    aid = str(aud.get("id"))
    kws = keywords_of(aud)
    path = csv_path(out_dir, prefix)
    ui.log("[%s] %d 个关键词 → %s" % (aid, len(kws), path))

    if os.path.exists(path) and not args.refresh:
        ui.log("  本地已有 CSV，跳过导出（要重取加 --refresh）")
        ui.log("  ⚠ 想换一份就加 --refresh；数量不满意就改词再来")
        return bucket_runner.steps_status([("圈选", "ok")])

    prompt = prompt_of(args)
    got = export_csv(s, kws, prompt, path)
    if got is None:
        return bucket_runner.steps_status([("圈选", "ok")])
    text = open(path, encoding="utf-8-sig").read()
    n, total, avg = summarize(text)
    record_selection(camp["taskGroupName"], aid, time.strftime("%Y-%m-%d %H:%M"),
                     len(kws), n, total, v2_db)
    ui.log("  圈选结果已写入数据库")
    ui.log("  ✅ 数量满意的话，跑这一条建名单：")
    ui.log("     run_distribution_ids.py --csv \"%s\" --config <同一个 YAML> --only %s --suffix -N --submit"
           % (path, aid))
    return bucket_runner.steps_status([("圈选", "ok")])


def main():
    ap = cli.parser("真导出（默认彩排：只到卡片出现）", only=True)
    ap.add_argument("--keywords", default="", help="直接给词表（逗号分隔），盖过配置里的；临时试词表用")
    ap.add_argument("--out-dir", default="", help="CSV 落哪（默认 活动/数据/圈选）")
    ap.add_argument("--prefix", default="", help="CSV 文件名前缀（默认 日期_桶名）")
    ap.add_argument("--prompt-file", default="", help="口径提示词文件（默认用脚本内 PROMPT）")
    ap.add_argument("--refresh", action="store_true", help="本地已有当天 CSV 也强制重取")
    ap.add_argument("--job", default="", metavar="导出任务号",
                    help="只重下**已经导出完**的任务（不重新导出）；要配 --out，可选 --only 记台账")
    ap.add_argument("--out", default="", help="--job 模式的 CSV 落盘路径")
    ap.add_argument("--parallel", type=int, default=1,
                    help="一次并发开几个对话页（默认 1 = 串行；用户 2026-09-28：一次开三个没问题）")
    ap.add_argument("--v2-db", default=repo.V2_DB, help="数据库 v2 路径")
    args = ap.parse_args()

    ctx = cli.context(args, shots="selection_shots", progress="selection_progress.json")
    camp = ctx.cfg["campaign"]
    out_dir = args.out_dir or os.path.join(ctx.act_dir, "数据", "圈选")
    auds = ctx.auds
    if args.keywords:
        kws_cli = [k.strip() for k in args.keywords.split(",") if k.strip()]
        ui.log("用命令行词表：%d 个关键词（盖过配置）" % len(kws_cli))
        auds = [dict(a, keywordGroup={"keywords": ",".join(kws_cli)}) for a in auds]

    if args.job:
        # 下载超时 / 会话中途断开的兜底：导出任务已经跑完了，别再导一遍（大查询要几分钟）
        if not args.out:
            raise SystemExit("--job 模式要同时给 --out <CSV 落盘路径>")
        try:
            with ctx.session(args) as s:
                st = job_status(s.page, args.job)
                ui.log("任务 %s：状态=%s 行数=%s" % (args.job, st.get("status"), st.get("row_count")))
                if st.get("status") != "done":
                    raise RuntimeError("任务不是 done（%s），先别下" % st.get("status"))
                text = download_csv(s.page, st, args.out)
                if args.only and auds:
                    n, total, _ = summarize(text)
                    record_selection(
                        camp["taskGroupName"], str(auds[0]["id"]),
                        time.strftime("%Y-%m-%d %H:%M"),
                        len(keywords_of(auds[0])), n, total, args.v2_db)
                    ui.log("  圈选结果已写入数据库")
        except Exception as e:
            cli.fatal(ctx, e)
        ui.log("RESULT: OK")
        sys.exit(0)

    try:
        with ctx.session(args) as s:
            if args.parallel > 1:
                t0 = time.time()
                done = run_parallel(
                    s, auds, args, out_dir, prompt_of(args), args.parallel,
                    camp["taskGroupName"], args.v2_db)
                ui.log("并发导出完成：成功 %d / 共 %d 桶 ｜ 用时 %.1f 秒"
                       % (len(done), len(auds), time.time() - t0))
                cli.exit_with("OK" if len(done) == len(auds) else "HAS_WARN（部分桶没导出，重跑可补）",
                              0 if len(done) == len(auds) else 1)
            ctx.report = bucket_runner.run_buckets(
                auds,
                lambda a: do_one(s, camp, a, args, out_dir,
                                 args.prefix or "%s_%s桶%d词_" % (time.strftime("%Y-%m-%d"),
                                                                  a["id"], len(keywords_of(a))),
                                 args.v2_db),
                key_of=lambda a: "%s|%s" % (camp["taskGroupName"], a["id"]),
                describe=lambda a: "[%s] %s" % (a["id"], a.get("topic") or a.get("taskName")),
                progress=ctx.progress,
                on_item_fail=lambda a: ui.dismiss_dialogs(s.page),
                log=ui.log,
                dry_run=not args.submit,
                unit="桶", rest="桶")
    except Exception as e:
        cli.fatal(ctx, e)
    cli.finish(ctx.report)


if __name__ == "__main__":
    main()
