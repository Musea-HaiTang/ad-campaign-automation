# -*- coding: utf-8 -*-
"""CSDN 后台 · 数据报表页 录制器（只读勘察用）。

为什么要它：新功能「取数」得先把后台的报表页摸清——菜单在哪、日期控件怎么点、
表格有哪些列、粒度到哪一级、查询走的是哪个接口。自己试要好几轮，让用户点一遍最快。

它记三样东西（全程只读，不点任何创建/修改/删除）：
  1. 每次 click / input / change（元素文案、class、placeholder、输入值）
  2. 每次页面跳转（含 hash 路由变化）
  3. 后台的 XHR/JSON 请求（URL、方法、参数、响应片段）—— 找接口的关键

用法:
    .venv\\Scripts\\python.exe -u automation/scripts/record_report.py
    ... --stop-after 900        # 到点自动停（秒）
    ... --start-url <url>       # 换起始页

结束方式：关浏览器窗口 / 生成同名 .stop 文件 / 到点自动停。
输出：automation/_tmp/record_report_<时间戳>.jsonl（_tmp 已在 .gitignore 里）
"""
import argparse
import datetime
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"D:\playwright-browsers")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILE = os.path.join(REPO, ".browser-profile")
TMP_DIR = os.path.join(REPO, "automation", "_tmp")
DEFAULT_START = "https://mp-admin.csdn.net/silkroad-dist/#/"
SKIP_EXT = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
            ".woff", ".woff2", ".ttf", ".ico", ".map")

INIT_JS = r"""(() => {
  if (window.__rec_installed) return;
  window.__rec_installed = true;
  if (!window.__recQueue) window.__recQueue = [];
  const esc = s => (s == null ? '' : String(s)).replace(/\s+/g, ' ').trim().slice(0, 120);
  function findLabel(el) {
    let node = el;
    while (node && node !== document.documentElement) {
      if (node.classList && node.classList.contains('el-form-item')) {
        const l = node.querySelector('.el-form-item__label');
        return l ? esc(l.innerText) : '';
      }
      node = node.parentElement;
    }
    return '';
  }
  function dump(kind, el) {
    if (!el) return;
    const info = {
      t: Date.now(),
      kind: kind,
      tag: el.tagName,
      text: esc(el.innerText || el.value || ''),
      ph: (el.getAttribute && (el.getAttribute('placeholder') || '')) || '',
      name: (el.getAttribute && (el.getAttribute('name') || '')) || '',
      cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 140) : '',
      role: (el.getAttribute && (el.getAttribute('role') || '')) || '',
      aria: (el.getAttribute && (el.getAttribute('aria-label') || '')) || '',
      label: findLabel(el),
      val: (el.value !== undefined && el.value !== null) ? esc(el.value) : '',
      checked: el.checked === true ? true : (el.checked === false ? false : null),
      selText: (el.selectedOptions && el.selectedOptions[0]) ? esc(el.selectedOptions[0].textContent) : ''
    };
    window.__recQueue.push(info);
  }
  document.addEventListener('click', e => {
    const t = e.target;
    const pick = t.closest('.el-select-dropdown__item, .el-checkbox__inner, .el-radio-button__inner, .el-radio__inner, button, a, input, textarea, .el-form-item__label, .el-checkbox__label, .el-select__wrapper, .el-date-editor, .el-picker-panel td');
    dump('click', pick || t);
  }, true);
  ['input', 'change'].forEach(et => {
    document.addEventListener(et, e => {
      const el = e.target;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) dump(et, el);
    }, true);
  });
})();
"""

DRAIN_JS = "() => { const q = window.__recQueue || []; window.__recQueue = []; return q; }"
PROBE_JS = "() => ({ installed: !!window.__rec_installed, queueLen: (window.__recQueue || []).length })"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="录制输出 JSONL 路径（默认 automation/_tmp/record_report_<时间戳>.jsonl）")
    ap.add_argument("--start-url", default=DEFAULT_START, help="起始页")
    ap.add_argument("--stop-after", type=float, default=None, help="到点自动停止（秒）")
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.out or os.path.join(TMP_DIR, "record_report_%s.jsonl" % stamp)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    stop_file = os.path.splitext(out)[0] + ".stop"
    if os.path.exists(stop_file):
        os.remove(stop_file)

    with open(out, "w", encoding="utf-8") as fh:
        fh.write("")

    def log(*a):
        print(*a, flush=True)

    stats = {"click": 0, "input": 0, "change": 0, "nav": 0, "xhr": 0}

    def handle(info):
        kind = info.get("kind", "?")
        stats[kind] = stats.get(kind, 0) + 1
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(info, ensure_ascii=False) + "\n")
        if kind == "click":
            log("  点击 |", (info.get("label") or "-")[:16], "|", (info.get("text") or "-")[:44],
                "|", (info.get("cls") or "-")[:34])
        elif kind in ("input", "change"):
            log("  输入 |", (info.get("label") or "-")[:16], "|", (info.get("ph") or "-")[:26],
                "=>", (info.get("val") or "-")[:40])
        elif kind == "nav":
            log("  跳转 |", info.get("url", ""))
        elif kind == "xhr":
            log("  接口 |", info.get("method", "?"), info.get("status", "?"),
                "|", (info.get("url") or "")[:110], "| 响应 %d 字节" % len(info.get("body") or ""))

    def on_response(resp):
        """只记后台自己的接口：JSON 响应，或 /api 路径；静态资源一律跳过。"""
        try:
            url = resp.url
            if "mp-admin.csdn.net" not in url:
                return
            low = url.lower().split("?")[0]
            if low.endswith(SKIP_EXT):
                return
            headers = {}
            try:
                headers = resp.headers or {}
            except Exception:
                pass
            ctype = str(headers.get("content-type", "")).lower()
            is_json = "json" in ctype
            if not is_json and "/api" not in url.lower():
                return
            req = resp.request
            post = ""
            try:
                post = req.post_data or ""
            except Exception:
                pass
            body = ""
            if is_json:
                try:
                    body = resp.text()[:4000]
                except Exception as e:
                    body = "<读响应失败: %s>" % e
            entry = {
                "t": int(time.time() * 1000),
                "kind": "xhr",
                "method": req.method,
                "status": resp.status,
                "url": url,
                "post": post[:2000],
                "body": body,
            }
            handle(entry)
        except Exception as e:
            log("  (响应记录跳过:", e, ")")

    ctx = None
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE,
                channel="msedge",
                headless=False,
                viewport={"width": 1680, "height": 1000},
            )
            ctx.add_init_script(INIT_JS)
            ctx.on("response", on_response)
            for pg in list(ctx.pages):
                try:
                    pg.set_default_timeout(8000)
                except Exception:
                    pass

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(8000)
            page.goto(args.start_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1500)

            try:
                probe = page.evaluate(PROBE_JS)
            except Exception as e:
                probe = {"err": str(e)}
            log("探针(注入)结果:%s" % probe)
            if not probe.get("installed"):
                log("!! 注入未生效，页面上的点击可能录不到（接口仍会记录）。")

            log("")
            log("浏览器已打开，请走一遍「取数」这条路：")
            log("  1) 点侧边菜单进数据/报表页")
            log("  2) 选活动/任务组（如果有这一项）")
            log("  3) 选年份 + 月份（比如 2026 年 5 月）")
            log("  4) 点「查询」，等表格出来")
            log("  5) 表格出来后停手几秒（我要记下响应）")
            log("")
            log("演示完就关掉浏览器窗口；或者跟我说一声，我这边停。")
            log("开始时间:%s | 输出:%s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), out))

            t0 = time.time()
            last_urls = {}
            while True:
                for pg in list(ctx.pages):
                    try:
                        cur = pg.url
                    except Exception:
                        continue
                    key = id(pg)
                    if last_urls.get(key) != cur:
                        last_urls[key] = cur
                        if cur and not cur.startswith("about:"):
                            handle({"t": int(time.time() * 1000), "kind": "nav", "url": cur})
                    try:
                        batch = pg.evaluate(DRAIN_JS)
                    except Exception:
                        continue
                    if isinstance(batch, list):
                        for info in batch:
                            handle(info)
                if os.path.exists(stop_file):
                    log("检测到 stop 文件，停止记录。")
                    break
                if args.stop_after and time.time() - t0 >= args.stop_after:
                    log("到点自动停止记录。")
                    break
                time.sleep(0.4)
    finally:
        log("---- 统计 ----")
        log("点击 %d | 输入 %d | 跳转 %d | 接口 %d" %
            (stats.get("click", 0), stats.get("input", 0) + stats.get("change", 0),
             stats.get("nav", 0), stats.get("xhr", 0)))
        log("输出:%s" % out)
        if ctx:
            try:
                ctx.close()
            except Exception as e:
                log("ctx.close:", e)


if __name__ == "__main__":
    main()
