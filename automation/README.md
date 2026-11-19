# automation — CSDN 投放执行层

把一份**整活动数据**（`../activities/{活动名}/配置/{品牌}{负责人}.yaml`）变成 CSDN 后台可创建的对象：
任务组 / 资源 / 客群 / 任务工单，并在后台自动执行。

## 跑之前（环境只写在这一处）

- **解释器固定用仓库根下的 venv**（Python 3.11-3.15 + PyYAML + Playwright，依赖清单见仓库根 `requirements.txt`）。Windows 是 `.venv\Scripts\python.exe`，macOS 是 `.venv/bin/python`。**一律用 venv 解释器，不假设系统 `python` 的版本或 PATH。**
  venv 缺失时，用本机 Python 3.11-3.15 执行 `python -m venv .venv`；Windows 再用 `.venv\Scripts\python.exe -m pip install -r requirements.txt`，macOS 用 `.venv/bin/python -m pip install -r requirements.txt`。
- 浏览器自动使用本机 Microsoft Edge 或 Google Chrome，选择结果记录在 `.local/browser.json`；登录 profile 在仓库内的 `.browser-profile`（cookie 过期跑 [`wait-login`](docs/wait_login.md) 重登）。如果系统策略拦截浏览器启动，再由当前操作者按本机安全策略允许。
- 每一步怎么做、在哪停：见 [`docs/执行层全流程.md`](docs/执行层全流程.md)。共用层的验收入口用对应平台的 venv 解释器执行 `-m unittest discover -s automation/tests -v`（假柜台，不开真浏览器）。

## 命令入口

所有执行命令统一从仓库根目录调用：

```powershell
.venv\Scripts\python.exe -m automation.scripts <command> [options]
.venv\Scripts\python.exe -m automation.scripts --help
```

命令实现按职责放在 `domain / data / browser / runtime / commands` 五个包中；调用方只依赖上面的命令接口。

## 目录

```
automation/
├── README.md                # 本文件（执行层总览/入口）
├── AGENTS.md                # 执行层极简索引（AI 用）
├── scripts/                 # 统一命令入口 + 分层实现
│   ├── __main__.py          # ★唯一外部命令入口：python -m automation.scripts <command>
│   ├── domain/              # 业务规则：活动契约、命名、判定、远端三态
│   ├── data/                # SQLite：仓储、同步、看板 payload、复盘、备份恢复
│   ├── browser/             # 浏览器、CSDN 页面动作、列表查询、登录
│   ├── runtime/             # 命令外壳、批处理工头、项目路径
│   └── commands/            # 各业务命令的实现
├── tests/                   # 假柜台单测（不开真浏览器）
├── docs/                    # 说明书：一个命令或共享模块一份，按业务动作组织
│   ├── README.md            # ★ 文档导航：按任务定位该读哪一篇
│   ├── 执行层全流程.md      # ★ 入口：每一步做什么、读哪份文档、在哪停（建批前先读这页）
│   ├── 脚本通用约定.md      # ★ 所有脚本共用的命令、安全、恢复、日志和结果口径
│   ├── 数据库说明.md        # ★ 数据库职责、核心约束、YAML 边界和备份规则
│   ├── 复盘会话格式.md      # 复盘对话唯一排版真源（改前/改后/问题/产物）
│   ├── workspace_payload.md # 看板 payload 的入口、字段和当前边界
│   ├── workspace_sync.md    # 执行结果同步到投放数据库
│   ├── activity_state.md    # 活动启停命令与边界
│   ├── run_taskgroup.md / run_ads.md / run_audience.md / run_distribution.md
│   ├── run_selection.md / run_distribution_ids.md / run_taskorder.md
│   ├── check_campaign.md / check_batch_plan.md / check_pool.md / wait_login.md
│   ├── fetch_perf.md / visualize_perf.md / judge_batch.md
│   └── 巡检与自动复盘.md     # 运维：通用巡检命令 + Codex / WorkBuddy / 人工接入
└── campaigns/README.md      # 整活动 YAML 字段规范（schema，工具侧）
```

> 活动数据在仓库根 `../activities/{活动名}/`：`配置/` 保留活动定义和当前整活动 YAML，遗留的 `批次/` 也只能放当前执行载荷；历史批次、指标和复盘统一保存在数据库，不再保留历史批次 YAML 或 `归档/`。物料 / 日志同目录，与工具分离。
> **展示层（网站）在 `../web/`**（`app.py` 起本地只读服务、`static/` 是页面），见 `../web/README.md`。
> **看板这一域横跨两层（刻意如此）**：上面带【看板】标记的四个文件留在本层 `scripts/`，页面与服务在 `../web/`；依赖方向**单向**（web → automation）。

## 设计原则

- **数据驱动**：一份整活动 yaml 喂所有脚本；类型固定项（`controls`）内嵌、自包含。
- **共用层只有一处**：跟后台页面打交道的知识分层——底下的动作（挂公共浏览器 / 下拉 / 穿梭框 / 弹窗清场 / 字段回读 / 截图 / 中文占位符常量）在 `browser/csdn_ui.py`；**列表页那一层**（翻开 → 筛选 → 查询 → 取行）在 `browser/list_page.py`；**按完整名称查远端是否存在**统一在 `browser/remote_lookup.py`，三态与 payload 指纹在 `domain/execution_state.py`。各 `run-*` 命令只写「这次要办什么」。
  `list_page` **不提供写入动作**（新建/提交/确定）——写入留在各 `run-*` 命令的提交闸门里；等待超时不抛错，只有菜单 / 筛选框找不到才当场抛。
- **浏览器只有一只**：`browser/browser_broker.py` 起一只独立 Edge 或 Chrome，首选 CDP 9222，冲突时自动向后寻找并把实际端口写入状态；看板 / 建任务 / `wait-login` 都从状态读取 CDP 地址后 `connect_over_cdp`，各开各的标签页；**不许再写 `launch_persistent_context`**。真办事（`--submit`）另有写锁 `browser/csdn_ui._write_lock`，同一时刻只允许一个脚本。
- **等页面只写条件等待**：`csdn_ui.wait_for()` / `visible_input()` / `click_query()` / `table_has_rows()`——**不许新增固定 `wait_for_timeout` 死等**（快就少等、慢就多等）。
- **提交闸门 + 回读核对**：凡"创建类"动作，**任一步没通过就不提交**（关弹窗、记 `warn` 下次重跑），**提交后一律回读后台确认落库**——只看「弹窗关闭 + `.el-message` 提示」不算成功；回读工具本身失效时记 `warn`，不能返回通过。
- **命名唯一出处**：桶名 / 客群名 / 工单名 / 资源名 / 物料文件名只在 `domain/naming.py` 里拼（生成器 `ad_output/工具/gen_*.py` 与执行命令都 import 它）。后台按**精确字符串**匹配，名字对不上就选不中。
- **装载唯一入口**：整活动 YAML 一律 `domain/campaign.load(路径)`（校验必填 + 未知字段 + 补默认值）；命令里 `.get("字段", 默认值)` 这种自兜底一律不许再写——字段名打错要**启动就报错**。契约见 `campaigns/README.md`。
- **拆分 + 断点 + 止损**：每个命令只做一个实体；**逐项排队 / 断点账本 / 止损 / RESULT 口径统一在 `runtime/bucket_runner.py`（工头）一处**——每项独立 `try/except`、运行前读"已完成清单"支持断点续跑、**首项 / 连续 3 项失败即中止**。任务工单账本键含完整批次名，跨批不会误 SKIP。账本先写同目录临时文件、刷盘后再原子替换，避免写入中断留下半截 JSON。各 `run-*` 命令只提供「怎么跑一项」；通用规则见 [`docs/脚本通用约定.md`](docs/脚本通用约定.md)。
- **模式二：只对中断项做恢复对账**：正常新建不预读后台；每项真正填写前持久化 `submitting` 和 payload 指纹。若进程在提交后崩溃，下一次只查这一项：`FOUND` 复用、`ABSENT` 重做、`UNKNOWN` 记 `needs_reconcile` 并停止，禁止整批预读或盲重建。账本在 `--submit` 下严格读取，存在但损坏就停止；缺失仍视为首次运行。
- **回读只看精确身份**：客群 / 名单 / 工单 / 任务组按完整名称精确行核对，资源按完整资源名全等；禁止用整页正文包含、桶名前缀或任务名尾号单独判成功。查询失败返回 `UNKNOWN`，不能伪装成“不存在”或“已创建”。
- **命令外壳只有一处**：开关（`--config/--submit/--headed/--reset-progress/--only`）、装载（读 YAML → 活动目录 → 截图目录）、账本文件名、`ui.session(...)` 包装、「`RESULT:` 行 + 退出码」全在 `runtime/cli.py`。各命令只加自己的开关、只写自己那件事。
- **彩排也讲真话**：每项跑完做「步骤体检」——**全部步骤 ok 才记 `done`**（下次彩排跳过）；**有一步失败就记 `warn`**，那项下次会重跑，并计入 `RESULT: HAS_WARN`（退出码 1）。判定只有一处实现：`bucket_runner.steps_status()`。
- **安全优先**：默认 `dry-run`（只填 + 校验 + 截图，不点确定）；`--submit` 才真正创建。**截图仅 dry-run / 测试阶段产生**，正式 `--submit` 不截图。**一次只跑一条命令**（连着开多个浏览器会话会撞上"上一个刚关、下一个弹窗还没渲染"，报 `Locator.click: Timeout`）。
- **每趟都报用时**：工头逐项打 `⏱ 用时 X 秒`、结尾打 `⏱ 总用时 X 秒（跑了 N 项，跳过 M 项）`；四个脚本的 `RESULT` 行也带总用时。要用时统计直接从日志抓这几行。
- **每趟都留日志**：`ui.session()` 自动把 stdout 同步写到 `activities/{活动}/日志/runs/`；浏览器恢复、重试和 RESULT 可直接回查。
- **取数只走只读查询接口**：`fetch-perf` 命令使用两个查询接口（任务组解析 → 按天查工单级 → 按任务查资源级累计），**不用后台的「导出」**（导出模块会整块失效、还会按参数复用旧文件拿半截数据当今天的用）。接口契约见 `docs/fetch_perf.md`。
- **数据库同步整批回滚**：`workspace_sync.sync_config_batch()` 对活动、桶、批次和文案使用同一事务；中途失败不留下半批数据库记录，已 `submitted` 的项下次运行会重新同步修复。
- **看板口径与「合计」唯一出处**：一个桶「当天的量」和「哪些天算有量」由 `workspace_payload` 从投放数据库算好下发（`bucketCells` / `bucketDays` / `orderDays`），页面只做加减。
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
| 共用层（browser/csdn_ui · browser/list_page · domain/execution_state · browser/remote_lookup） | 页面动作、精确查询、远端三态与 payload 指纹；见「设计原则」 |
| 命令外壳（runtime/cli） | 各命令共用的那套架子：`parser()` 开关 / `context()` 装载 / `Ctx.session()` 会话 / `finish()` RESULT 与退出码 |
| 工头（runtime/bucket_runner） | 排队规则：逐项跑 / 断点账本 / 失败清场 / 到点止损 / RESULT 三态 |
| 命名（domain/naming） | 名字的唯一出处：`{前缀}-{id}类` / `· {topic}` / `· {角色}`；前缀取 `campaign.namePrefix` |
| 装载（domain/campaign） | 整活动 YAML 的唯一入口：解析 / 校验（必填 + 未知字段）/ 补默认值 / 读写 thresholds |
| 远端三态（domain/execution_state · browser/remote_lookup） | `FOUND / ABSENT / UNKNOWN`；列表按完整名称精确查询，恢复策略统一由工头执行 |
| 取数（fetch-perf） | 把后台投放数据写进投放数据库 `activities/_db/投放数据.db` |
