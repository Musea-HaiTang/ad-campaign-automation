# -*- coding: utf-8 -*-
"""抓活动链接的正文文本（流程 §2「摸产品」第一步用）。

用途：用户给一个活动链接后，先把页面**存成原始 HTML**，同时打印**去标签的正文**，
方便 AI 读产品形态/能力/奖励/规则——不用在对话里粘贴整页。

用法：
    .venv\\Scripts\\python.exe -u ad_output/工具/fetch_page_text.py <url> [out.html]

输出：
    - 原始 HTML 存到 out（默认 `../../automation/_tmp/_page_raw_<时间戳>.html`，也可显式指定）
    - stdout 打印去掉 script/style/标签后的正文（一行一条，适合直接读）

⚠ 局限：只抓**静态 HTML**。若页面正文是 JS 渲染/接口加载的，这里只能拿到骨架——
   那种情况改用浏览器（Playwright 打开页面后取 innerText）。
"""
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
TMP_DIR = Path(__file__).resolve().parents[2] / "automation" / "_tmp"


def use_utf8_stdout():
    """页面正文含 emoji，Windows 控制台默认 GBK 会在 print 时崩——显式改成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def fetch_text(url, out_path=None):
    """抓 url → 返回 (去标签正文, 原始 HTML)。out_path 给了就把原始 HTML 落盘。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
    if out_path:
        Path(out_path).write_text(html, encoding="utf-8")
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", html, flags=re.S | re.I)
    body = re.sub(r"<(br|/p|/div|/h[1-6]|/li|/tr)[^>]*>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        body = body.replace(a, b)
    body = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), body)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in body.splitlines()]
    return "\n".join(ln for ln in lines if ln), html


def main():
    use_utf8_stdout()
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    url = sys.argv[1]
    if len(sys.argv) > 2:
        out = Path(sys.argv[2])
    else:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        out = TMP_DIR / ("_page_raw_%s.html" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    text, html = fetch_text(url, out)
    print("SAVED %s (%d bytes)" % (out, len(html.encode("utf-8"))))
    print("=" * 60)
    print(text)


if __name__ == "__main__":
    main()
