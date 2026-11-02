# -*- coding: utf-8 -*-
"""命令外壳：七个 `run_*.py` 共用的那套架子（2026-09-23 架构体检 候选 2）。

为什么要它
----------
原先每个脚本各写一遍同一套骨架：同名开关、`--only` 的未知桶校验（4 处逐字相同）、
装载三件套（读 YAML → 活动目录 → 截图目录）、进度文件名、`ui.session(...)` 包装、
「RESULT: … + 退出码」收尾。规则要改就得改七遍，漏一处就出现"两个脚本说法不一样"。

它只做五件事，业务动作仍留在各脚本里：
    parser()            建带共用开关的 parser
    context()           读配置 → 算目录 → 按 --only 过滤桶 →（可选）开断点账本
    Ctx.session(args)   开浏览器会话（headed / dry_run / shot_dir 一处定）
    fatal(ctx, exc)     循环外挂掉：打一行 ✗ + 标 fatal
    finish() / exit_with()   打 RESULT 行 + 定退出码

边界（别越界）
--------------
- 不认页面、不认桶的业务含义、**不创建任何后台对象**——建东西仍归各 `run_*.py`；
- 结果三态与退出码只有 `finish()` 一处；`--only` 的报错文案只有 `only_buckets()` 一处。

不开浏览器就能单测：见 `automation/tests/test_cli.py`。
"""
import argparse
import os
import sys

import bucket_runner
import campaign
import csdn_ui as ui

CONFIG_HELP = "整活动 YAML（activities/{活动名}/配置/{品牌}{负责人}.yaml）"
HEADED_HELP = "显示浏览器"
RESET_HELP = "清空断点进度，重新全跑"
ONLY_HELP = "只跑指定桶，逗号分隔（如 A 或 A,C）；默认全部"


def parser(submit_help, *, config=True, only=False, reset_progress=True):
    """带共用开关的 parser；各脚本自己再加专属开关。

    submit_help    `--submit` 的说明（各脚本措辞不同，必须传）
    config         False 时不加 `--config`（`run_distribution_ids` 的 config 是可选的，自己加）
    only           True 时加 `--only`（先校验再过滤，见 `only_buckets`）
    reset_progress False 时不加 `--reset-progress`（不记账本的命令用不上）
    """
    ap = argparse.ArgumentParser()
    if config:
        ap.add_argument("--config", required=True, help=CONFIG_HELP)
    ap.add_argument("--submit", action="store_true", help=submit_help)
    ap.add_argument("--headed", action="store_true", help=HEADED_HELP)
    if reset_progress:
        ap.add_argument("--reset-progress", action="store_true", help=RESET_HELP)
    if only:
        ap.add_argument("--only", default="", help=ONLY_HELP)
    return ap


def only_buckets(raw, auds):
    """`--only` 原始串 → 桶 id 列表（统一大写）；给了不存在的桶当场报错，不静默跑空。

    桶 id 大小写不敏感。报错文案只有这一处——各命令提示必须一模一样。
    """
    only = [x.strip().upper() for x in (raw or "").split(",") if x.strip()]
    if not only:
        return []
    known = [str(a["id"]).upper() for a in auds]
    unknown = [x for x in only if x not in known]
    if unknown:
        raise SystemExit("--only 里有不存在的桶：%s（本活动可选：%s）"
                         % (", ".join(unknown), ", ".join(known)))
    return only


def keep_buckets(auds, only):
    """按 `--only` 过滤；空列表表示不过滤。"""
    if not only:
        return auds
    return [a for a in auds if str(a["id"]).upper() in only]


def progress_path(act_dir, name):
    """账本文件路径：`{活动}/日志/<name>`——这个约定只有这一处拼。"""
    return os.path.join(act_dir, "日志", name)


def open_progress(act_dir, name, *, reset=False, strict=False):
    """开一个断点账本；账本名要按运行时算的命令（`run_audience --name-suffix`）用这个。"""
    try:
        return bucket_runner.Progress(progress_path(act_dir, name),
                                      reset=reset, strict=strict)
    except ValueError as e:
        print(str(e))
        raise SystemExit(2)


class Context:
    """一趟运行要用到的东西：配置、三个目录、这一趟要跑的桶、断点账本、结果。"""

    def __init__(self, cfg, act_dir, shot_dir, auds, only, progress=None):
        self.cfg = cfg
        self.act_dir = act_dir
        self.shot_dir = shot_dir
        self.auds = auds
        self.only = only
        self.progress = progress
        self.report = bucket_runner.RunReport()

    def session(self, args, *, dry_run=None):
        """开浏览器会话：headed 跟 `--headed` 走，dry_run 默认＝"不是真提交"。"""
        return ui.session(headed=args.headed,
                          dry_run=(not args.submit) if dry_run is None else dry_run,
                          shot_dir=self.shot_dir)


def context(args, *, shots, progress=None):
    """读配置 → 算目录 → 按 --only 过滤桶 →（可选）开账本。

    shots     截图子目录名（`{活动}/日志/` 下面那层）：多数命令是 "<命令>_shots"，
              `run_ads` 历史上叫 "shots"，照旧不动（动了历史截图就找不着了）。
    progress  账本文件名，如 "ads_progress.json"；不给就不记账本。
              账本名要按运行时算的（`run_audience --name-suffix` 那种）不传这里，
              拿到 ctx 后自己调 `open_progress(ctx.act_dir, name, reset=...)` 塞回 `ctx.progress`。
    """
    cfg = campaign.load_or_exit(args.config)
    act_dir = campaign.activity_dir(args.config)
    shot_dir = os.path.join(act_dir, "日志", shots)
    only = only_buckets(getattr(args, "only", ""), cfg["audiences"])
    ctx = Context(cfg, act_dir, shot_dir, keep_buckets(cfg["audiences"], only), only)
    if progress:
        ctx.progress = open_progress(act_dir, progress,
                                     reset=getattr(args, "reset_progress", False),
                                     strict=getattr(args, "submit", False))
    return ctx


def first_line(exc, limit=160):
    """异常 → 一行摘要：playwright 的调用日志很长，别把整屏刷掉。"""
    text = str(exc).splitlines()
    return (text[0] if text else str(exc))[:limit]


def fatal(ctx, exc):
    """循环外挂掉：打一行 ✗ + 标 fatal。收尾仍走 `finish`（退出码 1）。"""
    ui.log("  ✗ 失败:%s" % first_line(exc))
    ctx.report.fatal = True


def finish(report):
    """收尾：RESULT 行 + 退出码（只有这一处）。"""
    ui.log("RESULT: %s | 总用时 %.1f 秒" % (report.status, report.seconds))
    sys.exit(report.exit_code())


def exit_with(text, code):
    """不走 RunReport 的命令的收尾（`run_distribution_ids` 那种两态结果）。"""
    ui.log("RESULT: %s" % text)
    sys.exit(code)
