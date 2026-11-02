# -*- coding: utf-8 -*-
"""等登录：登录态失效时，开个浏览器让用户重新登录，**真的恢复了**才返回。

为什么要它：CSDN 广告后台的登录态会**按模块**失效。2026-09-16 那天 `/admin/export/*`
整块返回 `code=400600 无权限`、页面提示「无权访问，请重新登录」，而任务列表接口同时仍然正常——
光看"页面能打开"根本判断不出来。这个脚本把判断变成事实：每 5 秒探一次接口权限，恢复才算数。

用法:
    .venv\\Scripts\\python.exe -u automation/scripts/wait_login.py
    ... --minutes 20          # 最多等多少分钟（默认 15）
    ... --url <页面>           # 打开哪个页面等你登录（不给就按 --site 取默认）
    ... --site databi         # 等**数据平台**（data.csdn.net）的登录，见下

两个站（`--site`）：

  - `admin`（默认）· CSDN **广告后台** `mp-admin.csdn.net`：判定口径 = `GET /admin/export/tasks/meta`
    返回 `code=200`。
  - `databi` · **数据平台** `data.csdn.net`（`run_selection.py` 取数用的那个）：判定口径 =
    打开 `…/chat` 是否被踢到 `/login` + 对话输入框在不在。**它的登录态独立于广告后台**，
    2026-09-29 就是它过期导致圈选报「对话页找不到输入框」。

退出码：恢复 0 / 未恢复（超时或窗口被关）1。

⚠ 只读：只发只读探测（GET 接口 / 打开对话页），不点页面上任何按钮、不下载、不创建。
⚠ 窗口用**最大化**打开：固定视口（如 1680×1000）在比它小的屏幕上会把右侧挤出屏幕，
  用户就点不到登录入口了（2026-09-16 踩过）。
⚠ 挂的是**公共浏览器**（2026-10-16 起）：不用再关看板——它自己会把公共浏览器切成"有窗口"
  给你登录，看板取数下次自动挂回同一只（登录态是同一份 profile）。
"""
import argparse
import os
import sys
import time
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402

import browser_broker as broker  # noqa: E402
import csdn_ui as ui  # noqa: E402

DEFAULT_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/distApplyOrder/list"
DATABI_URL = "https://data.csdn.net/chat"
DATABI_COMPOSER = "div.chat-center-input textarea"


def log(*a):
    print(*a, flush=True)


def probe_admin(page):
    """广告后台：MPToken + MPUser + 当前用户名都到位才算登录成功。"""
    info = ui.login_identity(page)
    ok = bool(info["userName"] and info["hasToken"] and info["hasUser"])
    return ok, "MPToken=%s | MPUser=%s | userName=%r" % (
        info["hasToken"], info["hasUser"], info["userName"])


def probe_databi(page, navigate=True):
    """数据平台：打开对话页，被踢到 /login 或没有输入框 = 没恢复。(ok, 说明)。

    独立 wait_login 用另一个标签页探测；doctor 直接检查用户正在操作的标签页，
    这时传 navigate=False，避免反复刷新把正在填写的登录表单清空。
    """
    try:
        if navigate:
            page.goto(DATABI_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1200)
        url = page.url
        box = page.locator(DATABI_COMPOSER).count()
        parsed = urlparse(url)
        logged_in = parsed.hostname == "data.csdn.net" and "/login" not in parsed.path
        if parsed.path.startswith("/chat"):
            logged_in = logged_in and box > 0
        return logged_in, "url=%s 输入框=%s" % (url, box)
    except Exception as e:
        return False, "请求异常: %s" % str(e).splitlines()[0][:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=15.0, help="最多等多少分钟")
    ap.add_argument("--site", choices=["admin", "databi"], default="admin",
                    help="admin = CSDN 广告后台（默认）｜ databi = 数据平台 data.csdn.net")
    ap.add_argument("--url", default="", help="打开哪个页面等你登录（不给按 --site 取默认）")
    args = ap.parse_args()
    url = args.url or (DEFAULT_URL if args.site == "admin" else DATABI_URL)

    with sync_playwright() as p:
        # 挂到**公共浏览器**上（有窗口模式）：不用再关看板——它和看板取数共用同一只浏览器、
        # 各开各的标签页（2026-10-16 用户定）。
        broker.ensure("headed")
        ctx = broker.connect(p)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        probe_page = ctx.new_page() if args.site == "databi" else page
        probe_page.set_default_timeout(20000)

        log("浏览器已打开（公共浏览器切到有窗口）。请你在窗口里重新登录 %s。"
            % ("CSDN 广告后台" if args.site == "admin" else "数据平台 data.csdn.net"))
        log("我每 5 秒探一次登录态，恢复后关掉我开的这两个标签页（公共浏览器留着）。")
        log("----")

        deadline = time.time() + args.minutes * 60
        ok, n = False, 0
        while time.time() < deadline:
            ok, why = (probe_admin(page) if args.site == "admin"
                       else probe_databi(probe_page))
            n += 1
            log("[%s] 第 %d 次探测：%s （%s）"
                % (time.strftime("%H:%M:%S"), n, "✅ 已恢复" if ok else "还没恢复", why))
            if ok:
                break
            if not ctx.pages:
                log("浏览器窗口被关掉了，停止等待。")
                break
            time.sleep(5)

        try:
            page.close()
            if probe_page:
                probe_page.close()
        except Exception as e:
            log("page.close:", e)
        log("RESULT: 登录态%s" % ("已恢复" if ok else "未恢复"))
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
