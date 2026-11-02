# DeepSeek 网页搜索与抓取 MCP

> 管什么：把 DeepSeek 的 Search / Fetch REST API 包装成 Codex 可调用的两个只读 MCP 工具。
> 不管什么：搜索策略、活动流程和证据判断；这些仍按 `ad_output/流程文档/CSDN广告投放自动化流程.md` 执行。
> 谁什么时候读：安装、排查或更新 DeepSeek 网页工具时。

## 工具

- `deepseek_search`：调用 `POST https://api.deepseek.com/v1/tools/search`。
- `deepseek_fetch`：调用 `POST https://api.deepseek.com/v1/tools/fetch`。

Search 默认返回 5 条并带正文，避免“先 Search 再逐页 Fetch”。需要精确页面时再调用 Fetch。

## 鉴权

优先读取 `DEEPSEEK_API_KEY`。没有该环境变量时，复用 `~/.codex/config.toml` 中：

```toml
[model_providers.deepseek]
experimental_bearer_token = "..."
```

Token 只用于请求头，不写日志、不返回给模型。

## 注册到 Codex

```powershell
```powershell
$repo = (Get-Location).Path
codex mcp add deepseek_web -- "$repo\.venv\Scripts\python.exe" "$repo\automation\scripts\deepseek_web_mcp.py"
```
```

执行后重启 Codex，用 `codex mcp list` 或 `/mcp` 确认服务及两个工具已加载。

⚠ 修改 MCP 脚本后也必须重启 Codex。Codex 会长期复用已启动的 MCP 子进程；只改文件不会自动换到新代码。

## 验证

```powershell
.venv\Scripts\python.exe -m pytest automation/tests/test_deepseek_web_mcp.py -q
```

真实联网测试由 Codex 调用 `deepseek_search` 完成。HTTP 401 / 402 / 403 / 429 会原样返回错误，不重试。
