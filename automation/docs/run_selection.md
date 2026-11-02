# 圈选博文 → CSV · `run_selection.py`（执行层第 3 步 · B 路径）

> **管什么**：怎么从数据平台导出一份圈选博文 CSV、导出前后怎么核对。
> **不管什么**：A 路径（后台按关键词圈选用户）→ [`run_audience.md`](run_audience.md)；两条路的区别 → [`执行层全流程.md`](执行层全流程.md) §2；拿 CSV 建名单 → [`run_distribution_ids.md`](run_distribution_ids.md)。
> **谁什么时候读**：走 B 路径取数时。

## 开工前

- **只导出 CSV，不建任何后台对象。** 看完数量满意了，再跑 `run_distribution_ids.py` 建分发名单——两条命令分开，就是为了让你在中间能喊停（数量不满意就改词重取）。
- ⚠ **这份 CSV 是中间产物**：建名单那步核对通过后会被**自动删掉**（要留就加 `--keep-csv`）。导出的时间 / 词数 / 博文数 / 总点击都写入数据库 `selection_run`。

## 怎么跑

```powershell
# 彩排（默认）：发问、等模型出「确认导出」卡片，然后停（不产生导出任务）
.venv\Scripts\python.exe -u automation/scripts/run_selection.py ^
  --config "<当前执行 YAML>" --only D --headed

# 真导出：点确认导出 → 轮询任务 → 抓 CSV
... run_selection.py --config <yaml> --only D --submit

# 多桶并发（一桶一个标签页，各一轮对话）
... --only B,C,D --parallel 3 --submit

# 本地已有当天 CSV 时默认跳过导出；要重取一份新的加 --refresh
# 用任务号重下（不重新导出）：--job <导出任务号> --out "<CSV 落盘路径>"
```

- 账本 `activities/{活动名}/日志/selection_progress.json`（键 = 任务组|桶）；彩排截图落 `日志/selection_shots/`。导出完日志里会直接给出下一步建名单的命令。
- **`--parallel N`**：同一浏览器上下文里给每个桶开一个独立标签页（各一轮对话）→ N 个问题一次发完 → 轮流看卡片 → 卡片齐了统一点「确认导出」→ 交错轮询各导出任务。实测三桶串行 183 秒 → `--parallel 3` 114.7 秒；5 桶建议 3+2 分两批（约 3 分钟内）。默认 `--parallel 1` = 串行。
  每桶独立 try/except，一桶失败不影响其他桶；断点与串行一致（本地已有当天 CSV 就跳过）。⚠ `--parallel` 不走 `bucket_runner` 的逐项日志风格，结尾打 `RESULT: OK / HAS_WARN`。

## 口径提示词（关键）

口径写在脚本里的 `PROMPT` 常量（用户 2026-09-21 的「已验证口径 · 修正版」），`--prompt-file` 可换成外部文件。**每次必须整段发给对话**——平台的「全局记忆」不可靠：不带提示词那一轮，模型自己把口径改成了分列 `multiSearchAny`、漏掉 `status = 1` / `intent_tag` / `category_three_name`；带上就一步不差。

要点：表 `csdn_dw.dws_media_blog_article_df_v`；四列 `article_id / title / article_url / last_30_days_pv`（**列名是 `article_url` 不是 `url`**）；`status = 1`、`last_30_days_pv > 1`；命中范围 `title / keyword_ai / intent_tag / category_one_name / category_two_name / category_three_name`；模板 `multiMatchAny(concat_ws('|', …), [...])`；先 COUNT，>1000 行走 `create_export_job`。

## 真机流程

| 步 | 动作 | 接口 / 页面 |
|---|---|---|
| 1 | 打开对话页、发问（提示词 + 词表） | `POST /api/chat/stream`（`model_code=deepseek-v4-pro`、`project_id=EFTccf`） |
| 2 | 等模型 COUNT 后出「确认导出」卡片 | 前端轮询 `GET /api/chat/running` |
| 3 | 点「确认导出」→ 拿任务 id | `POST /api/export-jobs` |
| 4 | 轮询到 done | `GET /api/export-jobs/{id}` |
| 5 | 抓文件、转 UTF-8 带 BOM 落盘 | `GET <download_url>`（华为云 OBS 签名链接） |

## 产物

CSV 落 `activities/{活动名}/数据/圈选/<日期>_<桶>桶<N>词_圈选博文_<YYYYMMDD>.csv`，**UTF-8 带 BOM、只此一份**。

- 文件名由脚本自己拼：平台返回的 `filename` 里主题词是模型每次现起的（跑两次得到 `…视频剪辑关键词圈选_…` 和 `…视频剪辑圈选博文_…`），不能拿来当文件名。
- 导完统计 **博文数 / 总点击数 / 平均点击数** 并写入 `selection_run`。平均值不单独存，按 `total_click / article_count` 现算。
- 统计用 `csv` 模块读（不是按行切）：标题里带换行时按行切会把 1 条算成 2 条。

## 已知坑

1. **Playwright 会接管浏览器下载**：文件变 UUID、无扩展名、落在 `%TEMP%\playwright-artifacts-*`、关窗即删 → 一律走 API 直取，不点「下载 CSV」。
2. **平台导出的 `filename` 没有扩展名**，内容是 **UTF-8 无 BOM** → 本地补 `.csv` 并转 UTF-8 带 BOM（Excel 才不乱码）。
3. **`row_count` 是物理行数**（标题里带换行会多算）；**同一份数据两次导出，行序会变**（内容相同）→ 比对用 id 集合，别比文件哈希。
4. **大导出：任务在后台已 done，但 Playwright 默认 30 秒下载超时会白导一次**（实测 39.9 万行要 105 秒、93.7 万行 165 秒）。已修：`DOWNLOAD_TIMEOUT_MS` = 30 分钟、`DOWNLOAD_ATTEMPTS` = 3（每次重试前重新取任务状态，签名链接会过期）。真下不来就用**任务号重下**：`--job <id> --out <路径>`（任务号在报错前那行 `导出任务 <id>，等它跑完…` 里，后台「导出任务管理」也能查）。
5. **掉登录先看是不是 `data.csdn.net` 过期**：数据平台登录态独立于广告后台，特征是脚本报**「对话页找不到输入框」**（`…/chat` 被重定向到 `/login`），用广告后台的 `wait_login.py` 探不出来 → 跑 `wait_login.py --site databi`（见 [`wait_login.md`](wait_login.md)）。
