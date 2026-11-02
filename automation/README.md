# automation — CSDN 投放执行层

把一份**整活动数据**（`../activities/{活动名}/配置/{品牌}{负责人}.yaml`）变成 CSDN 后台可创建的对象：
任务组 / 资源 / 客群 / 任务工单，并在后台自动执行。

## 跑之前（环境只写在这一处）

- **解释器固定用仓库根下的 `.venv\Scripts\python.exe`**（Python 3.12.4 + PyYAML + playwright，依赖清单见仓库根 `requirements.txt`）。**一律用 venv 解释器、不依赖 PATH**——本机默认 `python` 是 3.14.6（空环境，只装了 pip）。
  venv 缺失时重建：用 Python 3.12-3.14 执行 `python -m venv .venv`，再执行 `.venv\Scripts\python.exe -m pip install -r requirements.txt`。
- 浏览器自动使用本机 Microsoft Edge 或 Google Chrome，选择结果记录在 `.local/browser.json`；登录 profile 在仓库内的 `.browser-profile`（cookie 过期跑 [`wait_login.py`](docs/wait_login.md) 重登）。**启动浏览器需提权。**
- 每一步怎么做、在哪停：见 [`docs/执行层全流程.md`](docs/执行层全流程.md)。共用层的验收入口：`.venv\Scripts\python.exe -m unittest discover -s automation/tests -v`（假柜台，不开真浏览器）。

## 目录

```
automation/
├── README.md                # 本文件（执行层总览/入口）
├── AGENTS.md                # 执行层极简索引（AI 用）
├── scripts/                 # 执行脚本
│   ├── csdn_ui.py           # ★共用层：会话/下拉/穿梭框/弹窗清场/字段回读/截图 + 占位符常量
│   ├── list_page.py         # ★共用层（列表页）：翻开/筛选/查询/取行（页签作用域 + 冻列碎片合并 + 行内按钮）
│   ├── cli.py               # ★共用层（命令外壳）：开关 / 装载 / 账本路径 / 会话 / RESULT 行与退出码
│   ├── bucket_runner.py     # ★共用层（工头）：逐项排队 / 断点账本 / 止损 / RESULT 口径
│   ├── execution_state.py   # ★共用层：FOUND/ABSENT/UNKNOWN、payload 指纹
│   ├── remote_lookup.py     # ★共用层：列表页按完整名称做三态查询
│   ├── naming.py            # ★共用层（命名）：桶名/客群名/工单名/资源名/物料文件名唯一出处
│   ├── audience_metrics.py  # 圈选达标读数/判定/轮询 + 行级「停止/勾选/批量删除」（纯函数 + 页面动作，共用层）
│   ├── campaign.py          # ★整活动 YAML 装载：校验必填 / 补默认值 / 读写 thresholds
│   ├── workspace_repo.py    # ★数据库 v2 公开接口：活动 / 桶 / 桶批次 / 复盘 / 指标
│   ├── workspace_payload.py # 数据库 v2 → 看板 payload
│   ├── workspace_review.py  # 数据库 v2 自动复盘判断、待办创建和运营短报
│   ├── workspace_sync.py    # 执行 YAML 的桶批次 / 资源计划幂等写入 v2
│   ├── activity_state.py    # 活动启停：查看 / ended / active
│   ├── run_taskgroup.py     # 建任务组（保底步骤，dry-run；--submit 才建）
│   ├── run_ads.py           # 建资源
│   ├── run_audience.py      # 圈选用户（建后按日均曝光验收）
│   ├── run_distribution.py  # 一键创建分发名单（第3.5步：圈选后、工单前；dry-run；--submit 才建）
│   ├── run_selection.py     # 圈选博文（第3步另一种走法）：新数据平台取数出 CSV，**不建后台对象**
│   ├── run_distribution_ids.py # 用博文 id 建分发名单（第3.5步另一种走法）：普通名单
│   ├── deepseek_web_mcp.py # DeepSeek Search / Fetch 的最小 MCP stdio 服务（Codex 联网工具）
│   ├── run_taskorder.py     # 建任务工单（第4步，逐桶；dry-run；--submit 才建）
│   ├── check_campaign.py    # 活动体检（只读）：核对后台 5 类对象在不在、名字一字不差；查客群时顺带读「日均曝光(预估)」
│   ├── check_batch_plan.py  # 批次 YAML 计划自检（离线、秒级）：权重按资源数 / AB 位次不能跳 / 名字↔槽位
│   ├── check_pool.py        # 想法池自检（离线、秒级）：建过却没删 / 各桶还没上过的存量
│   ├── fetch_perf.py        # 【看板】取数（只读）：按天查工单级 + 按任务查资源级读数 → 写数据库 v2
│   ├── visualize_perf.py    # 【看板】单文件导出：页面 + 数据烤成一个 HTML（发人/归档）
│   ├── judge_batch.py       # 【判定】读数据库 v2 → 出「留谁 / 下谁 / 补几条」清单（**只读，不碰后台**）
│   ├── judging.py           # 【判定规则·唯一实现】门槛 → 达标 / 留谁下谁 / 补几条（纯函数；命令行与看板共用）
│   ├── review_queue.py      # 待复盘队列：列出 due review，并回写平台会话 ID
│   ├── patrol.py            # 供应商无关巡检：刷新今天 → 判定 → 待复盘队列 + 报告
│   ├── record_audience.py   # 开发用录制器（圈选用户）
│   ├── record_report.py     # 开发用录制器（数据报表页）
│   ├── browser_broker.py    # ★公共浏览器：一只独立 Edge/Chrome（首选 CDP 9222，实际端口写入状态）挂在登录 profile 上
│   ├── board_service.py     # 看板服务（web/app.py）的起 / 停 / 查（**不动公共浏览器**）
│   └── wait_login.py        # 等登录（只读）：把公共浏览器切成有窗口让你重登，登录态真恢复才返回
├── tests/                   # 假柜台单测（不开真浏览器）
├── docs/                    # 说明书：一个脚本一份，文件名 = 脚本名把 .py 换成 .md
│   ├── README.md            # ★ 文档导航：按任务定位该读哪一篇
│   ├── 执行层全流程.md      # ★ 入口：每一步做什么、读哪份文档、在哪停（建批前先读这页）
│   ├── 脚本通用约定.md      # ★ 所有脚本共用的命令、安全、恢复、日志和结果口径
│   ├── 数据库v2说明.md      # ★ 数据库职责、核心约束、YAML 边界和备份规则
│   ├── 发布前整改计划.md     # ★ P0/P1 交付阻断项与验收 Gate
│   ├── workspace_payload.md # v2 看板 payload 的入口、字段和当前边界
│   ├── workspace_review.md  # 兼容旧链接；内容统一到 judge_batch.md
│   ├── 复盘会话格式.md      # 复盘对话唯一排版真源（改前/改后/问题/产物）
│   ├── workspace_sync.md    # 执行结果同步到数据库 v2
│   ├── activity_state.md    # 活动启停命令与边界
│   ├── run_taskgroup.md / run_ads.md / run_audience.md / run_distribution.md
│   ├── run_selection.md / run_distribution_ids.md / run_taskorder.md
│   ├── deepseek_web_mcp.md  # DeepSeek Search / Fetch 的 MCP 注册与鉴权
│   ├── check_campaign.md / check_batch_plan.md / check_pool.md / wait_login.md
│   ├── fetch_perf.md / visualize_perf.md / judge_batch.md
│   ├── record_audience.md / record_report.md   # 开发用录制说明
│   ├── 巡检与自动复盘.md     # 运维：通用巡检命令 + Codex / WorkBuddy / 人工接入
│   └── 执行层实测耗时.md     # 人看的记录：各脚本实测用时（不是流程规则，不进 AI 阶段阅读清单）
└── campaigns/README.md      # 整活动 YAML 字段规范（schema，工具侧）
```

> 活动数据在仓库根 `../activities/{活动名}/`：`配置/` 保留活动定义和当前整活动 YAML，遗留的 `批次/` 也只能放当前执行载荷；历史批次、指标和复盘统一保存在数据库，不再保留历史批次 YAML 或 `归档/`。物料 / 日志同目录，与工具分离。
> **展示层（网站）在 `../web/`**（`app.py` 起本地只读服务、`static/` 是页面），见 `../web/README.md`。
> **看板这一域横跨两层（刻意如此）**：上面带【看板】标记的四个文件留在本层 `scripts/`，页面与服务在 `../web/`；依赖方向**单向**（web → automation）。

## 设计原则

- **数据驱动**：一份整活动 yaml 喂所有脚本；类型固定项（`controls`）内嵌、自包含。
- **共用层只有一处**：跟后台页面打交道的知识分层——底下的动作（挂公共浏览器 / 下拉 / 穿梭框 / 弹窗清场 / 字段回读 / 截图 / 中文占位符常量）在 `csdn_ui.py`；**列表页那一层**（翻开 → 筛选 → 查询 → 取行）在 `list_page.py`；**按完整名称查远端是否存在**统一在 `remote_lookup.py`，三态与 payload 指纹在 `execution_state.py`。各 `run_*.py` 只写「这次要办什么」。
  `list_page` **不提供写入动作**（新建/提交/确定）——写入留在各 `run_*.py` 的提交闸门里；等待超时不抛错，只有菜单 / 筛选框找不到才当场抛。
- **浏览器只有一只**：`browser_broker.py` 起一只独立 Edge 或 Chrome，首选 CDP 9222，冲突时自动向后寻找并把实际端口写入状态；看板 / 建任务 / `wait_login` 都从状态读取 CDP 地址后 `connect_over_cdp`，各开各的标签页；**不许再写 `launch_persistent_context`**。真办事（`--submit`）另有写锁 `csdn_ui._write_lock`，同一时刻只允许一个脚本。
- **等页面只写条件等待**：`csdn_ui.wait_for()` / `visible_input()` / `click_query()` / `table_has_rows()`——**不许新增固定 `wait_for_timeout` 死等**（快就少等、慢就多等）。
- **提交闸门 + 回读核对**：凡"创建类"动作，**任一步没通过就不提交**（关弹窗、记 `warn` 下次重跑），**提交后一律回读后台确认落库**——只看「弹窗关闭 + `.el-message` 提示」不算成功；回读工具本身失效时记 `warn`，不能返回通过。
- **命名唯一出处**：桶名 / 客群名 / 工单名 / 资源名 / 物料文件名只在 `naming.py` 里拼（生成器 `ad_output/工具/gen_*.py` 与执行脚本都 import 它）。后台按**精确字符串**匹配，名字对不上就选不中。
- **装载唯一入口**：整活动 YAML 一律 `campaign.load(路径)`（校验必填 + 未知字段 + 补默认值）；脚本里 `.get("字段", 默认值)` 这种自兜底一律不许再写——字段名打错要**启动就报错**。契约见 `campaigns/README.md`。
- **拆分 + 断点 + 止损**：每个脚本只做一个实体；**逐项排队 / 断点账本 / 止损 / RESULT 口径统一在 `bucket_runner.py`（工头）一处**——每项独立 `try/except`、运行前读"已完成清单"支持断点续跑、**首项 / 连续 3 项失败即中止**。任务工单账本键含完整批次名，跨批不会误 SKIP。账本先写同目录临时文件、刷盘后再原子替换，避免写入中断留下半截 JSON。各 `run_*.py` 只提供「怎么跑一项」；通用规则见 [`docs/脚本通用约定.md`](docs/脚本通用约定.md)，可迁移经验已移到桌面 `执行层工程经验.md`。
- **模式二：只对中断项做恢复对账**：正常新建不预读后台；每项真正填写前持久化 `submitting` 和 payload 指纹。若进程在提交后崩溃，下一次只查这一项：`FOUND` 复用、`ABSENT` 重做、`UNKNOWN` 记 `needs_reconcile` 并停止，禁止整批预读或盲重建。账本在 `--submit` 下严格读取，存在但损坏就停止；缺失仍视为首次运行。
- **回读只看精确身份**：客群 / 名单 / 工单 / 任务组按完整名称精确行核对，资源按完整资源名全等；禁止用整页正文包含、桶名前缀或任务名尾号单独判成功。查询失败返回 `UNKNOWN`，不能伪装成“不存在”或“已创建”。
- **命令外壳只有一处**：开关（`--config/--submit/--headed/--reset-progress/--only`）、装载（读 YAML → 活动目录 → 截图目录）、账本文件名、`ui.session(...)` 包装、「`RESULT:` 行 + 退出码」全在 `cli.py`。各脚本只加自己的开关、只写自己那件事。
- **彩排也讲真话**：每项跑完做「步骤体检」——**全部步骤 ok 才记 `done`**（下次彩排跳过）；**有一步失败就记 `warn`**，那项下次会重跑，并计入 `RESULT: HAS_WARN`（退出码 1）。判定只有一处实现：`bucket_runner.steps_status()`。
- **安全优先**：默认 `dry-run`（只填 + 校验 + 截图，不点确定）；`--submit` 才真正创建。**截图仅 dry-run / 测试阶段产生**，正式 `--submit` 不截图。**一次只跑一条命令**（连着开多个浏览器会话会撞上"上一个刚关、下一个弹窗还没渲染"，报 `Locator.click: Timeout`）。
- **每趟都报用时**：工头逐项打 `⏱ 用时 X 秒`、结尾打 `⏱ 总用时 X 秒（跑了 N 项，跳过 M 项）`；四个脚本的 `RESULT` 行也带总用时。要用时统计直接从日志抓这几行。
- **每趟都留日志**：`ui.session()` 自动把 stdout 同步写到 `activities/{活动}/日志/runs/`；浏览器恢复、重试和 RESULT 可直接回查。
- **取数只走只读查询接口**：`fetch_perf.py` 用两个查询接口（任务组解析 → 按天查工单级 → 按任务查资源级累计），**不用后台的「导出」**（导出模块会整块失效、还会按参数复用旧文件拿半截数据当今天的用）。接口契约见 `docs/fetch_perf.md`。
- **数据库同步整批回滚**：`workspace_sync.sync_config_batch()` 对活动、桶、批次和文案使用同一事务；中途失败不留下半批数据库记录，已 `submitted` 的项下次运行会重新同步修复。
- **看板口径与「合计」唯一出处**：一个桶「当天的量」和「哪些天算有量」由 `workspace_payload` 从数据库 v2 算好下发（`bucketCells` / `bucketDays` / `orderDays`），页面只做加减。
- **执行前门控（AI 负责，不进脚本）**：必给项（负责人标识→`taskGroupName` / 子业务线 / 是否新建任务组+名 / 投放日期+时间段）未提供 → **不启动执行层**，规矩见 `AGENTS.md`。

> 彩排 / 正式由**运行命令决定**（带 `--submit` 才真创建，不带就是彩排）；`csdn_ui.session(dry_run=…)` 只负责「知道是彩排之后怎么表现」。

## 术语

| 词 | 意思 |
|---|---|
| 整活动 YAML | `activities/{活动名}/配置/{品牌}{负责人}.yaml`，执行层消费的唯一数据对象 |
| 活动定义 YAML | `activities/{活动名}/配置/活动定义.yaml`，物料 / 整活动 yaml 的上游数据源 |
| 桶（类） | 一个人群分组；1 桶 = 1 客群 = 1 任务工单 |
| 任务组 / 资源 / 客群 / 任务工单 | 后台四个实体，对应执行层第 1–4 步 |
| 圈选 | 按关键词圈出目标用户（第 3 步） |
| 共用层（csdn_ui / list_page / execution_state / remote_lookup） | 页面动作、精确查询、远端三态与 payload 指纹；见「设计原则」 |
| 命令外壳（cli） | 七条命令共用的那套架子：`parser()` 开关 / `context()` 装载 / `Ctx.session()` 会话 / `finish()` RESULT 与退出码 |
| 工头（bucket_runner） | 排队的老规矩：逐项跑 / 断点账本 / 失败清场 / 到点止损 / RESULT 三态 |
| 命名（naming） | 名字的唯一出处：`{前缀}-{id}类` / `· {topic}` / `· {角色}`；前缀取 `campaign.namePrefix` |
| 装载（campaign） | 整活动 YAML 的唯一入口：解析 / 校验（必填 + 未知字段）/ 补默认值 / 读写 thresholds |
| 远端三态（execution_state / remote_lookup） | `FOUND / ABSENT / UNKNOWN`；列表按完整名称精确查询，恢复策略统一由工头执行 |
| 取数（fetch_perf） | 把后台投放数据写进数据库 v2 `activities/_db/投放数据.db` |
