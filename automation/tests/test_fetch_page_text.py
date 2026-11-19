# -*- coding: utf-8 -*-
"""活动页面正文提取器必须按 HTML 结构过滤，不能依赖易绕过的正则。"""
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "ad_output" / "工具"))

import fetch_page_text  # noqa: E402


class FetchPageTextTest(unittest.TestCase):
    def test_提取正文并跳过脚本样式和注释(self):
        html = """
        <html><body>
          <h1>产品标题</h1>
          <script>alert('bad')</script>
          <style>.bad { color: red; }</style>
          <!-- 隐藏注释 -->
          <p>第一段 &amp; 第二段</p>
          <p>甲&nbsp;乙</p>
          <br>
          <div>下一行</div>
        </body></html>
        """

        text = fetch_page_text.html_to_text(html)

        self.assertIn("产品标题", text)
        self.assertIn("第一段 & 第二段", text)
        self.assertIn("甲 乙", text)
        self.assertIn("下一行", text)
        self.assertNotIn("alert", text)
        self.assertNotIn("color: red", text)
        self.assertNotIn("隐藏注释", text)

    def test_未闭合脚本不会泄漏后续内容(self):
        text = fetch_page_text.html_to_text(
            "<body>之前<script>alert('bad')<p>之后</p></body>"
        )
        self.assertEqual(text, "之前")


if __name__ == "__main__":
    unittest.main()
