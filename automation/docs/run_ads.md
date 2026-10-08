# CSDN 页面类广告 · 数据驱动自动化（整活动 YAML）

给「新建资源」这套重复操作做数据驱动：读一份**整活动 YAML**（`../activities/{活动名}/配置/{品牌}{负责人}.yaml`，
内置 `controls` + `campaign` + `audiences`），用 Playwright 复用已登录浏览器，逐条走完
`页面类 → 新建资源 → 填基本信息 → 选渠道 → 选素材路径 → 填三栏 → 飘红 → 确定`。

> **飘红（2026-09-24 加）**：YAML 的 `resources[].highlight` = 飘红词。填了就选「是否飘红 = 是」并填词，
> 留空保持默认「否」。字段定位 `csdn_ui.PH_HIGHLIGHT_WORD`；结构来自只读探针 `automation/_tmp/_probe_highlight.py`。
> 后台机制（用户实测）：**只能填一个表达**（逗号分隔无效）、正则最长匹配、**标题 + 摘要里所有出现处都会标红**。

## 架构

```
automation/
├── scripts/
│   ├── csdn_ui.py       # 共用层：跟后台页面打交道（下拉/穿梭框/弹窗清场/截图）
│   ├── bucket_runner.py # 共用层（工头）：逐项排队 / 断点账本 / 止损 / RESULT 口径
│   ├── cli.py           # 共用层（命令外壳）：开关 / 装载 / 账本路径 / 会话 / RESULT 行与退出码
│   └── run_ads.py      # 主驱动：读 campaign yaml → 逐条创建（dry-run 默认不开、不点确定）
├── docs/
│   └── run_ads.md      # 本文件
└── .. 活动数据：`../activities/{活动名}/配置/{品牌}{负责人}.yaml`（schema 见 `../campaigns/README.md`）
```

### 分层思路

| 层 | 职责 | 放哪 |
|---|---|---|
| **类型固定项** | 这类广告固定不变的控件：`channelType`、`channel`、`materialPath`、`defaults`、`fields` | campaign yaml 的 `controls`（内嵌，自包含） |
| **整活动数据** | 任务组名/活动链接（`campaign`）+ 人群桶（`audiences`：客群关键词 + 每桶 3 份资源） | campaign yaml |
| **执行器** | 打开弹窗、逐项填、逐项校验、截图（仅 dry-run）、确定；只认 `controls` + `audiences[].resources`，不写死某类 | `run_ads.py` |

> 设计目标：**每个活动 = 一份 campaign yaml**（含 N 桶 × 3 份资源）；加类型 = 换 `controls`（如图片类改 `materialPath`/`fields`）。
> 字段规范以 `campaigns/README.md` 为准，本文件只讲怎么跑 + 执行器可靠性。

## 怎么跑

```powershell
# dry-run：只填 + 校验 + 截图，不点「确定」、不创建（默认）
.venv\Scripts\python.exe -u automation/scripts/run_ads.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml

# 真正创建：加 --submit
.venv\Scripts\python.exe -u automation/scripts/run_ads.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml --submit

# 只跑指定桶（逐桶推进，如先只验 A 桶那 3 条）：加 --only
.venv\Scripts\python.exe -u automation/scripts/run_ads.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml --only A --submit

# 想看浏览器窗口：加 --headed

# 断点账本不想要了，从头全跑：加 --reset-progress
.venv\Scripts\python.exe -u automation/scripts/run_ads.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml --reset-progress
```

前置：python 3.12.4 装了 `playwright`、`pyyaml`；浏览器在 `D:\playwright-browsers`；
已登录 profile 在 `D:\Codex_WorkingSpace\ad_management\.browser-profile`（会随 cookie 失效需重登）。
启动浏览器需要提权（沙箱会拦浏览器子进程）。

**`--only A`（或 `--only A,C`）**：只跑指定桶，逐桶推进用——想「先建 A 桶 3 条、看过效果再建其余」就靠它。
桶 id 大小写不敏感；给了不存在的桶（如 `--only X`）直接报错，不会静默跑空。
断点账本的键是 `任务组|桶id|资源名`，所以先跑的桶之后跑全量时会自动 `SKIP`，**不会重复创建**；
截图/日志编号按本次实际清单从 1 开始。

## 性能与稳定性

**实测**（2026-09-08，dry-run）：
- 单条（含浏览器启动 + 页面加载）：**≈6s**
- 两条连跑：**≈9.8s**（第 2 条 ≈4s，因为不重新加载页面）
- 按此估算 10 条 ≈ **45s** 左右。

**为什么快/稳**：全部用**条件等待**（等元素可见、等下拉收起、等勾上、等弹窗隐藏），
不写死 sleep；**浏览器会话全程复用**，且**第二条起不重新 goto**——提交/关闭后直接留在
资源列表页，再点「新建资源」即可。每条独立 `try/except`，**失败后自动关弹窗**（避免残留遮罩引发连锁超时）。

**可靠性兜底**：
- **preflight**：跑主流程前先打开一次弹窗读「任务组」下拉，校验 `campaign.taskGroupName` 存在；**不存在则立即中止**，并列出实际可选项前 20（避免后续资源连锁失败）。
- **断点续跑**：每跑完一条记一笔到 `../activities/{活动名}/日志/ads_progress.json`；再跑时**已创建的永远跳过**，只是彩排校验过的则在正式跑时重做。要全部重跑加 `--reset-progress`。**彩排里校验没全过的条记 `warn`**（下次会重跑），只有全过才记 `done`。
- **失败止损**：**首条失败 / 连续 3 条失败即中止**后续（疑似系统性配置问题，如任务组名/子业务线错、页面结构变更）。止损规矩统一在 `bucket_runner.py`。
- 业务线必须显式重选（页面显示≠模型绑定）；下拉选中的可靠信号是「点中选项 + 下拉收起」。
- 渠道勾选点可见的 `.el-checkbox__inner`；移入按钮找**可用**的（带箭头）那个。
- 若某条失败，会打印 `✗ [n] <资源名> 失败:...`（提交失败还会列出表单校验错误），结尾 `RESULT: OK / HAS_WARN / HAS_FAILURES`（只有 `OK` 返回 0）。
- **截图仅 dry-run（测试）**：`item_XX_filled.png` 只在 dry-run 生成；正式 `--submit` **不截图**。

## 提速与防假成功（2026-09-22）

**① 提交前闸门**：`--submit` 现在先看「步骤是否全过」——**资源名 / 三栏 / 飘红任一回读不过就关弹窗、不提交**，记 `warn`
（下次重跑）。原来 `ok1/ok2` 只写日志、正式路径照样点「确定」：21 条规模下会一次性建出字段写错的资源，
而事后的回读只查"名字在不在"，查不出字段缺失。

**② 整批一次性回读核对**：`--submit` 跑完在资源列表用**「任务组」下拉**筛一遍，核对这一趟真提交的资源名在不在；
查不到的逐条打 `✗ 查不到`，并记 `warn`（`RESULT: HAS_WARN`、退出码 1）。
- 为什么整批核一次：逐条核对要多付 21 次列表往返（≈2~3 秒/条，合计一分钟上下），
  整批只多一次列表往返（`check_campaign.md` 实测：任务组下拉筛一次约 8.6 秒）。
- 「任务组」筛选不可用时**跳过核对并提示**（不当作缺失，需要自己跑 `check_campaign.py` 核一遍）。
- ⚠ 名字检查是**子串匹配**（跟 `check_campaign.py` 同款限制：`…A类 · 对照` 会被 `…A类 · 对照-4` 命中），
  且资源列表有**默认创建时间窄窗**（见 `check_campaign.md` 坑 6），老资源可能不在列表里 → 回读可能假报缺失。
  **以 `check_campaign.py` 的逐条精确查为准。**

**③ 等页面只写条件等待**：共用层新增 `csdn_ui.wait_for()` / `visible_input()` / `fill_visible()` / `click_query()`
（见 `csdn_ui.py` 顶部注释）。本脚本只在回读里用到；**不再新增固定 `wait_for_timeout` 死等**。

**实测（2026-09-22 彩排，本活动 15 条 dry-run）**：52.5 秒 → 52.8 秒（每条约 3.5 秒）——
**dry-run 不变是预期的**：闸门与整批回读都只在 `--submit` 路径上跑。真跑一轮才会多出回读那一次列表查询
（按 `check_campaign.md` 的实测：任务组下拉筛一次约 8.6 秒，即整批回读约 +10 秒以内）。
> 文档早先记的「单条 ≈6s」是 2026-09-08 另一套条件下的数；2026-09-22 同活动实测 **3.5 秒/条**。

## 已知坑（已固化进执行器）
- **业务线必须显式重选**：下拉显示"企业服务事业部"但模型值可能为空，提交报 `departmentId is required`。执行器会在填子业务线**前**重选业务线。
- **渠道勾选**：Element UI 把原生 checkbox 隐藏了，要点可见的 `.el-checkbox__inner`；移动按钮找**可用**的那个（别点 disabled 的）。
- **下拉查找**：先 `filter(has_text)` 再遍历，避免全页几百项导致很慢。
- **goto**用 `domcontentloaded`，`networkidle` 会因 SPA 长连接卡住。
- 运行加 `python -u` 才能实时看到步骤输出。

> 字段规范见 `campaigns/README.md`；每个活动生成 campaign yaml 前先过「待确认清单」（见该 README 的「生成前确认」）。
