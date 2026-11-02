"""
CSDN 客群 · 圈选用户 流程录制器（轮询队列版）

起一个带着登录 profile 的真实浏览器，注入脚本把用户每次真实交互
（click / input / change）写进页面全局队列，Python 侧轮询读取。
不依赖页面 console 事件转发，避免部分环境下收不到。

用法:
    .venv\\Scripts\\python.exe -u automation/scripts/record_audience.py --out automation/logs/audience_<ts>.jsonl

浏览器打开后，用户手动走一遍「圈选用户」即可（是否真建客群随用户，只要不导出到分发名单）。
结束时在 automation/logs/ 下生成对应 <ts>.stop 文件（脚本自动收尾），或直接关浏览器。
"""
import argparse
import datetime
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402

import browser_broker as broker  # noqa: E402

START_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/resource/list?channelType=page"

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
    console.log('@@REC@@' + JSON.stringify(info));
  }
  document.addEventListener('click', e => {
    const t = e.target;
    const pick = t.closest('.el-select-dropdown__item, .el-checkbox__inner, .el-radio-button__inner, .el-radio__inner, button, a, input, textarea, .el-form-item__label, .el-checkbox__label, .el-select__wrapper');
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
    ap.add_argument("--out", required=True, help="录制输出 JSONL 路径")
    ap.add_argument("--stop-after", type=float, default=None, help="可选：到点自动停止（秒）")
    args = ap.parse_args()

    out = args.out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    stop_file = os.path.splitext(out)[0] + ".stop"

    with open(out, "w", encoding="utf-8") as fh:
        fh.write("")

    def log(*a):
        print(*a, flush=True)

    count = 0

    def handle(info):
        nonlocal count
        count += 1
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(info, ensure_ascii=False) + "\n")
        if info["kind"] == "click":
            log("  >", info["label"] or "-", "|", (info["text"] or "-")[:42], "|", (info["cls"] or "-")[:36])
        elif info["kind"] in ("input", "change"):
            log("  ~", info["kind"], "|", info["label"] or "-", "|", (info["ph"] or "-")[:26], "|", (info["val"] or "-")[:42])
        elif info["kind"] == "probe":
            log("  probe:", info.get("text"))

    ctx = None
    page = None
    try:
        with sync_playwright() as p:
            # 挂公共浏览器（有窗口）——不再自己起一只抢 profile（2026-10-16 用户定）
            broker.ensure("headed")
            ctx = broker.connect(p)
            ctx.add_init_script(INIT_JS)

            def on_new_page(pg):
                try:
                    pg.set_default_timeout(8000)
                except Exception:
                    pass

            ctx.on("page", on_new_page)
            page = ctx.new_page()
            page.set_default_timeout(8000)
            page.goto(START_URL, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1500)

            probe_ok = {}
            try:
                probe_ok = page.evaluate(PROBE_JS)
            except Exception as e:
                log("probe evaluate failed:", e)
            log("探针(注入)结果:%s" % probe_ok)
            if not probe_ok or not probe_ok.get("installed"):
                log("!! 注入未生效，请检查上下文/页面。")

            log("浏览器已打开，现在可以走一遍「圈选用户」流程。")
            log("关浏览器，或在 automation/logs/ 生成对应 .stop 文件，即停止记录。")
            log("开始时间:%s | 输出:%s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), out))

            t0 = time.time()
            while True:
                for pg in list(ctx.pages):
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
        log("共记录事件:%d | 输出:%s" % (count, out))
        if ctx and page:
            try:
                page.close()      # 只关自己开的页；公共浏览器留着（别 ctx.close()）
            except Exception as e:
                log("page.close:", e)


if __name__ == "__main__":
    main()
