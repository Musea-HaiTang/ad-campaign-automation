# 数据报表页录制器 · `record_report.py`（开发用，只读）

> **管什么**：摸不清后台页面时，开一个带窗口的浏览器接上登录态，**用户点、脚本记**。
> **不管什么**：它只录不建 —— 真办事的是各 `run_*.py`。
> **谁什么时候读**：要给某个后台页面写脚本、又不确定选择器的时候。

猜页面结构比点一遍慢得多（试错好几轮），后台还有"必须按顺序点侧边菜单才生效""输入框有隐藏副本"这类坑——让用户真点一遍，一次录准。

## 怎么跑

```powershell
.venv\Scripts\python.exe -u automation/scripts/record_report.py
... --stop-after 900          # 到点自动停（秒）
... --start-url <url>         # 换起始页
```

录完落 `automation/_tmp/record_report_<时间戳>.jsonl`（`_tmp` 已在 .gitignore 里）。结束方式：关浏览器 / 生成同名 `.stop` 文件 / 到点自动停。

## 记什么

| 类别 | 内容 |
|---|---|
| 点击 | 元素文案、class、placeholder、所在表单标签、选中值 |
| 输入 | 输入框标签、placeholder、每次输入的值 |
| 跳转 | 每次 URL 变化（含 hash 路由） |
| 接口 | xhr/fetch 的 URL、方法、状态、请求体、响应片段 |

## 坑（都已固化）

1. **不要按域名过滤接口**：后台真正的接口在 `csdn-distadmin.csdn.net`，页面在 `mp-admin.csdn.net`——按页面域名过滤会一条都记不到。脚本按 `resource_type` 抓。
2. 注入脚本要用**轮询队列**（`window.__recQueue`）读事件，别依赖 console 转发。
3. 下拉浮层要**点击**打开，hover 打不开。
