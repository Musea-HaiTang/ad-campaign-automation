# 圈选博文 → CSV（`run_selection.py`）

> 位置：执行层**第 3 步（圈选用户）的另一种走法**（2026-09-21 起）。原来那条是 `run_audience.py`
> 在后台按关键词圈选；这条路改成**在新数据平台取数拿 CSV**。
>
> ⚠ **只导出 CSV，不建任何后台对象。** 看完数量满意了，再跑 `run_distribution_ids.py` 建分发名单——
> 两条命令分开就是为了让你在中间能喊停（数量不满意就改词重取）。

## 怎么跑

```powershell
# 彩排（默认）：发问、等模型出「确认导出」卡片，然后停（不产生导出任务）
.venv\Scripts\python.exe -u automation/scripts/run_selection.py ^
  --config activities/火山引擎MediaKit/调整/2026-09-17-D桶换词重投.yaml --only D --headed

# 真导出：点确认导出 → 轮询任务 → 抓 CSV
... run_selection.py --config <yaml> --only D --submit

# 本地已有当天 CSV 时默认跳过导出；要重取一份新的
... 同上 + --refresh
```

断点账本 `activities/{活动名}/日志/selection_progress.json`（键 = 任务组\|桶）；
彩排截图落 `日志/selection_shots/`。导出完日志里会直接给出下一步建名单的命令。

## 并发导出：`--parallel N`（2026-09-28 加 · 用户提的）

一桶一轮对话，而"等模型出「确认导出」卡片"这一段要 40~150 秒——串行跑 5 桶自然就是六分多钟。
**用户 2026-09-28 提：一个会话里就能开多个对话，一次开三个应该没问题** → 加 `--parallel N`：

```powershell
... run_selection.py --config <yaml> --only B,C,D --parallel 3 --submit
```

**怎么并发**：同一浏览器上下文里给每个桶开一个**独立标签页**（各自一轮对话）→ N 个问题一次发完 →
轮流看每页卡片出现没有（这一段互相重叠）→ 卡片齐了统一点「确认导出」→ **交错**轮询各导出任务 →
各自抓 CSV / 写台账。仍然是"数据平台只导出、不建后台对象"。默认 `--parallel 1` = 原来的串行路径。

**实测（2026-09-28，B/C/D 三桶，与 9/24 同三桶串行对照）**：

| 跑法 | 用时 | 备注 |
|---|---|---|
| 串行（9/24 实测同三桶） | **183.1 秒**（43.5 + 79.5 + 60.1） | 一桶一轮，等完这轮等下一轮 |
| **`--parallel 3`（今天实测）** | **114.7 秒** | 卡片分别在 **44 / 44 / 68 秒**出现 —— 三路对话确实在并行；导出任务交错轮询 |

> 5 桶建议用 `--parallel 3` 分两批（3 + 2）：实测节奏约 **3 分钟内**（串行 6.6 分钟）。
> 每桶独立 try/except，一桶失败不影响其他桶；断点与串行一致（**本地已有当天 CSV 就跳过**，
> 中断后重跑只补缺的桶）。`--parallel` 只走"并发路径"（不走 `bucket_runner` 的逐项日志风格，
> 结束时打 `RESULT: OK / HAS_WARN`）。

## 口径提示词（关键）

口径写在脚本里的 `PROMPT` 常量（用户 2026-09-21 的「已验证口径 · 修正版」），`--prompt-file` 可换成外部文件。
**每次必须整段发给对话**——平台的「全局记忆」不可靠：不带提示词那一轮，模型自己把口径改成了分列
`multiSearchAny`、漏掉 `status = 1` / `intent_tag` / `category_three_name`；带上就一步不差。

要点：表 `csdn_dw.dws_media_blog_article_df_v`；四列 `article_id / title / article_url / last_30_days_pv`
（**列名是 `article_url` 不是 `url`**）；`status = 1`、`last_30_days_pv > 1`；命中范围
`title / keyword_ai / intent_tag / category_one_name / category_two_name / category_three_name`；
模板 `multiMatchAny(concat_ws('|', …), [...])`；先 COUNT，>1000 行走 `create_export_job`。

## 真机流程

| 步 | 动作 | 接口 / 页面 |
|---|---|---|
| 1 | 打开对话页、发问（提示词 + 词表） | `POST /api/chat/stream`（`model_code=deepseek-v4-pro`、`project_id=EFTccf`） |
| 2 | 等模型 COUNT 后出「确认导出」卡片 | 前端轮询 `GET /api/chat/running` |
| 3 | 点「确认导出」→ 拿任务 id | `POST /api/export-jobs` |
| 4 | 轮询到 done | `GET /api/export-jobs/{id}` |
| 5 | 抓文件、转 UTF-8 带 BOM 落盘 | `GET <download_url>`（华为云 OBS 签名链接） |

## 产物

CSV 落在 `activities/{活动名}/数据/圈选/<日期>_<桶>桶<N>词_圈选博文_<YYYYMMDD>.csv`，
**UTF-8 带 BOM、只此一份**。文件名由脚本自己拼：平台那个 `filename` 里的主题词是模型每次现起的
（跑两次得到 `…视频剪辑关键词圈选_20260921` 和 `…视频剪辑圈选博文_20260921`），不能拿来当文件名。

导完顺手统计 **博文数 / 总点击数 / 平均点击数**：

- 控制台直接打出来（看数量决定要不要往下走）；
- 同时追加一行到 **`activities/{活动名}/数据/圈选/圈选记录.md`** ——
  `| 导出时间 | 桶 | 关键词数 | 博文数 | 总点击数 | 平均点击数 | CSV |`，一次导出一行，文件不存在时脚本自己写表头。

> 为什么记这儿：跟 CSV 同一个目录，一眼能看到「这次圈了多少、量级多大」；纯文本、好 diff、能进 git。
> 统计用 `csv` 模块读（不是按行切）——标题里带换行时按行切会把 1 条算成 2 条（实测 51,677 vs 51,681）。

## 踩过的坑（2026-09-21 实测）

1. **Playwright 会接管浏览器下载**：文件变 UUID、无扩展名、落在 `%TEMP%\playwright-artifacts-*`、关窗即删。
   → 一律走 API 直取，不点「下载 CSV」。
2. **平台导出的 `filename` 没有扩展名**，内容是 **UTF-8 无 BOM** → 本地补 `.csv` 并转 UTF-8 带 BOM（Excel 才不乱码）。
3. **`row_count` 是物理行数**：标题里带换行会多算（实测 51,681 vs 记录数 51,677，跟 COUNT 一致）。
4. **同一份数据两次导出，行序会变**（哈希不同、内容相同）——比对要用 id 集合，别比文件哈希。
5. 签名链接会过期；要重下按 `GET /api/export-jobs/{id}` 重新取（脚本没做重下，需要时手动）。

## 大导出：下载超时与重下（2026-09-29 修）

**症状**：几十万行的大导出，任务在后台**已经 done**，但脚本报
`APIRequestContext.get: Timeout 30000ms exceeded` 就退出了——**白导一次**。当天实测两张：
39.9 万行拉了 **105 秒**、93.7 万行拉了 **165 秒**，而 Playwright 的默认超时是 **30 秒**。

**修法（已进脚本，不用再手工兜）**：

| 项 | 值 / 行为 |
|---|---|
| `DOWNLOAD_TIMEOUT_MS` | **30 分钟**（单次下载超时；模块常量，改一处即可） |
| `DOWNLOAD_ATTEMPTS` | **3 次**；每次重试前**重新取一次任务状态**（签名链接会过期，重新取才拿得到新链接） |
| 真下不来 | 用**任务号重下**，不重新导出：`run_selection.py --config <同一个 YAML> --job <导出任务号> --out "<CSV 落盘路径>"`（配 `--only <桶>` 会把这一笔记进 `圈选记录.md`） |

> 任务号在报错前那行 `导出任务 <id>，等它跑完…` 里；后台「导出任务管理」也能查。
> ⚠ 判定口径没变：小导出（几千行）照样秒回，这套只影响大文件。

## 掉登录：先看是不是 data.csdn.net 过期了（2026-09-29 加）

取数平台 `data.csdn.net` 的登录态**独立于广告后台**，会自己过期。特征是脚本报
**「对话页找不到输入框」**——那时 `…/chat` 已经被重定向到 `/login`，用广告后台的 `wait_login.py`
（探 `mp-admin`）**探不出来**。

```powershell
.venv\Scripts\python.exe -u automation/scripts/wait_login.py --site databi
```

开一个最大化窗口让你重登数据平台，探到「没被踢 + 输入框在位」才返回（判定见 `wait_login.md`）。

## 下一步

数量满意 → `run_distribution_ids.py`（把 CSV 的博文 id 灌进分发名单）。工单仍是 `run_taskorder.py` 的活。
