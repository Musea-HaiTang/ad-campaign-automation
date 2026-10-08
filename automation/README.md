# automation — CSDN 投放执行层

把一份**整活动数据**（`../activities/{活动名}/配置/{品牌}{负责人}.yaml`）变成 CSDN 后台可创建的对象：
任务组 / 资源 / 客群 / 任务工单，并在后台自动执行。

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
│   ├── naming.py            # ★共用层（命名）：桶名/客群名/工单名/资源名/物料文件名唯一出处
│   ├── audience_policy.py   # 圈选阈值策略（纯函数）：越界只升点击、**曝光锁死 1**，最多 5 次
│   ├── audience_metrics.py  # 圈选达标读数/判定/轮询 + 行级「停止/勾选/批量删除」（纯函数 + 页面动作，共用层）
│   ├── campaign.py          # ★整活动 YAML 装载：校验必填 / 补默认值 / 读写 thresholds
│   ├── run_taskgroup.py     # 建任务组（保底步骤，dry-run；--submit 才建）
│   ├── run_ads.py           # 建资源
│   ├── run_audience.py      # 圈选用户（含 --tune）
│   ├── run_distribution.py  # 一键创建分发名单（第3.5步：圈选后、工单前；dry-run；--submit 才建）
│   ├── run_selection.py     # 圈选博文（第3步另一种走法）：新数据平台取数出 CSV，**不建后台对象**；dry-run；--submit 才真导出；--job <任务号> 可只重下已导出的任务
│   ├── run_distribution_ids.py # 用博文 id 建分发名单（第3.5步另一种走法）：普通名单；dry-run；--submit 才建
│   ├── run_taskorder.py     # 建任务工单（第4步，逐桶 7 个；dry-run；--submit 才建）
│   ├── check_campaign.py    # 活动体检（只读）：核对后台 5 类对象在不在、名字一字不差；查客群时顺带读「日均曝光(预估)」判达标
│   ├── check_batch_plan.py  # 批次 YAML 计划自检（离线、秒级）：权重按资源数 / AB 位次不能跳 / 名字↔槽位，跑执行层之前跑它
│   ├── perf_db.py           # 【看板】★台账库（SQLite）：活动/工单/按天事实/资源读数，看板的唯一数据源
│   ├── fetch_perf.py        # 【看板】取数（只读）：按天查工单级 + 按任务查资源级读数 → 写台账库（默认增量），另落取数流水
│   ├── perf_payload.py      # 【看板】★数据装配（纯数据层）：台账库 + 活动 YAML → 看板 JSON（服务版/单文件版共用）
│   ├── visualize_perf.py    # 【看板】单文件导出：页面 + 数据烤成一个 HTML（发人/归档）
│   ├── judge_batch.py       # 【判定】读台账库 + 配置/判定门槛.yaml → 出「留谁 / 下谁 / 下一轮补几条新文案」清单（**只读，不碰后台**；下线由用户手动做）
│   │                        #   `--write` 追加清单、`--todo` 覆盖写待办；结尾打一行 `STATUS:` 给定时巡检原样抄
│   ├── judging.py           # 【判定规则·唯一实现】门槛 → 达标 / 留谁下谁 / 补几条（纯函数；judge_batch 命令行与看板共用一份，2026-09-28 收口）
│   ├── record_audience.py   # 开发用录制器（圈选用户）
│   ├── record_report.py     # 开发用录制器（数据报表页）
│   └── wait_login.py        # 等登录（只读）：开最大化窗口让你重登，登录态真恢复才返回；--site admin（广告后台，默认）/ databi（数据平台）
├── tests/                   # 假柜台单测（不开真浏览器）
│   ├── test_csdn_ui.py      # csdn_ui 的行为测试
│   ├── fakes.py             # 假柜台/假列表页（测试共用的假页面，不开浏览器）
│   ├── test_list_page.py    # 列表页的行为测试（页签作用域/冻列合并/只认全等/按钮兜底）
│   ├── test_bucket_runner.py # 工头的行为测试（断点/止损/退出码）
│   ├── test_cli.py          # 命令外壳的行为测试（--only 校验/过滤、目录与账本约定、结果三态与退出码）
│   ├── test_naming.py       # 命名规则测试（含「生成器输出 = 规则」的锚点）
│   ├── test_audience_policy.py # 圈选阈值搜索测试（假 estimate，不开浏览器）
│   ├── test_audience_metrics.py # 达标读数/判定/轮询测试（假页面 + 假时钟，不开浏览器）
│   ├── test_material_template.py # 物料模板测试（一个桶块 + 4–7 桶都能生成）
│   ├── test_perf_payload.py # 看板装配测试（同桶多工单/工单共用同名资源时不许合并）
│   ├── test_perf_db.py      # 台账库测试（今天覆盖/历史不丢/重拉幂等/读数取最新）
│   ├── test_campaign.py     # 装载/校验/默认值测试（含两个真实活动 YAML 的回归锚点）
│   ├── test_selection.py    # 圈选的纯函数测试（词表读取 / CSV 落盘路径）
│   ├── test_distribution_ids.py # 建名单的纯函数测试（后台计数回读 / 名单命名 / CSV 读 id）
│   └── test_run_audience.py # 圈选「提交前闸门」测试（假页面：校验没过只点取消、绝不点确定）
├── docs/                    # 每个任务的说明（按任务名）
│   ├── run_taskgroup.md
│   ├── run_ads.md
│   ├── run_audience.md
│   ├── run_distribution.md
│   ├── run_selection.md
│   ├── run_distribution_ids.md
│   ├── run_taskorder.md
│   ├── check_campaign.md
│   ├── check_batch_plan.md
│   ├── fetch_perf.md
│   ├── visualize_perf.md
│   ├── judge_batch.md
│   ├── record_audience.md
│   ├── record_report.md
│   ├── wait_login.md
│   └── 执行层实测耗时.md     # 人看的记录：各脚本实测用时（不是流程规则，不进 AI 阶段阅读清单）
└── campaigns/README.md      # 整活动 YAML 字段规范（schema，工具侧）

> 活动数据在仓库根 `../activities/{活动名}/`：**yaml 分两类**——`配置/`（活动定义 / 整活动 / thresholds，脚本平时消费的那份）、
> `调整/`（每次换词 / 换文案重投单独一份，按日期命名）；物料 / 数据 / 日志同目录，与工具分离。
> **展示层（网站）在仓库根 `../web/`**：`app.py` 起本地只读服务、`static/` 是页面；怎么起、怎么改见 `../web/README.md`。
> **看板这一域横跨两层（刻意如此）**：上面带【看板】标记的四个文件（台账库 / 数据装配 / 取数 / 单文件导出）留在本层 `scripts/`，
> 页面与服务在 `../web/`；依赖方向**单向**（web → automation）。为什么不把它们搬进 `web/`、每层改哪份文档：见 `../web/README.md` 的「看板相关代码分布」。
```

## 设计原则

- **数据驱动**：一份整活动 yaml 喂所有脚本；类型固定项（`controls`）内嵌、自包含。
- **共用层**：**跟后台页面打交道**的知识分两层，都只有一处——底下的动作（起浏览器带登录态 / 下拉选择 / 穿梭框 / 弹窗清场 / 字段回读 / 截图 / 中文占位符常量）在 `scripts/csdn_ui.py`；**列表页这一层（翻开 → 筛选 → 查询 → 取行）在 `scripts/list_page.py`**（页签作用域、冻列碎片按行号合并、按名字取行只认全等、行内按钮结构定位 + 坐标兜底、勾选）。各 `run_*.py` 只写「这次要办什么」（办事顺序）。后台改版只改这两个共用层。
  `list_page` **不提供写入动作**（新建/提交/确定）——写入留在各 `run_*.py` 的提交闸门里；等待超时不抛错，只有菜单/筛选框找不到才当场抛。
  **等页面也只写条件等待**：`csdn_ui.wait_for()`（等元素/等状态）、`visible_input()`（挑可见那份输入框）、
  `click_query()`（点查询 + 等这次查询落地）——**不许再新增固定 `wait_for_timeout` 死等**
  （2026-09-22 把各脚本的固定死等统一换成了条件等待：快就少等、慢就多等，最多等到设的上限）。
- **提交闸门 + 回读核对（2026-09-22 全量铺开）**：凡"创建类"动作，**任一步没通过就不提交**（关弹窗、记 `warn` 下次重跑），
  **提交后一律回读后台确认落库**——工单（`verify_created`）、客群（`verify_created`）、资源（整批一次性回读）、
  任务组（回任务组列表查）、分发名单（回「分发名单」页签查）。理由见下一条与「写入后台必须回读核对」。
- **命名唯一出处**：桶名/客群名/工单名/资源名/物料文件名只在 `scripts/naming.py` 里拼（生成器 `ad_output/工具/gen_*.py` 与执行脚本都 import 它）。后台按**精确字符串**匹配，名字对不上就选不中——所以别在别处拼字符串。
- **装载唯一入口**：整活动 YAML 一律 `campaign.load(路径)`（校验必填 + 补默认值）；脚本里 `.get("字段", 默认值)` 这种自兜底一律不许再写——字段名打错要**启动就报错**，不是跑到浏览器第 3 步才炸。契约见 `campaigns/README.md`。
- **调优落点形状唯一出处（2026-09-23）**：`thresholds.yaml` 每桶记录（`click/exposure/count/status/base`）的形状定义在 `scripts/campaign.py` 的 `threshold_record()`——它同时吃「策略结果对象」与「记录字典」；写回只有 `run_audience.save_thresholds()` 一个入口，且是**盖格子**（只改这次跑到的桶，其余保留）。原先两条写回路径各拼一遍栏位、取值方式还不同（`r["click"]` vs `r.click`），加一栏要改三处。
- **看板口径与「合计」唯一出处（2026-09-23）**：一个桶「当天的量」和「哪些天算有量」（「日均曝光」的分母）由 `perf_payload` 算好下发（`bucketCells` / `bucketDays` / `orderDays`），**页面只做加减**——这套口径原先写在 `web/static/app.js` 里、没有测试护着。`totals(payload, 桶, 口径, days=…)` 只有一个实现（页面所选区间与命令行摘要同一套口径）；取数日志那行「本次取回 N 天…合计」说的是**这次取回的天**，不是看板合计。
- **拆分 + 断点 + 止损**：每个脚本只做一个实体；**逐项排队 / 断点账本 / 止损 / RESULT 口径统一在 `scripts/bucket_runner.py`（工头）一处**——每项独立 `try/except`、运行前读"已完成清单"支持断点续跑、**首项/连续 3 项失败即中止**（避免连锁白跑）；各 `run_*.py` 只提供「怎么跑一项」。改规矩只改工头。
- **命令外壳只有一处（2026-09-23）**：开关（`--config/--submit/--headed/--reset-progress/--only`）、装载（读 YAML → 活动目录 → 截图目录）、账本文件名、`ui.session(...)` 包装、「`RESULT:` 行 + 退出码」全在 `scripts/cli.py`——七个 `run_*.py` 原先各写一遍（`--only` 的未知桶报错文案 4 处逐字相同），改一处规则要改七遍。现在各脚本只加自己的开关、只写自己那件事。
- **彩排也讲真话（2026-09-11 修）**：每项跑完做「步骤体检」——**全部步骤 ok 才记 `done`**（下次彩排跳过）；**有一步失败就记 `warn`**，那项下次会重跑，并计入 `RESULT: HAS_WARN`（退出码 1）。以前彩排一律返回 True，界面一堆 ✗ 却报 `RESULT: OK`、账本还记 done（假通过）。判定只有一处实现：`bucket_runner.steps_status()`。
- **每趟都报用时**：工头逐项打 `⏱ 用时 X 秒`、结尾打 `⏱ 总用时 X 秒（跑了 N 项，跳过 M 项）`；四个脚本的 `RESULT` 行也带总用时。要做用时统计就直接从日志抓这几行。
- **安全优先**：默认 `dry-run`（只填 + 校验 + 截图，不点确定）；`--submit` 才真正创建。**截图仅在 dry-run/测试阶段产生，正式 `--submit` 不截图**（截图是测试专用，不拖慢正式流程）。
- **一次只跑一条命令（2026-09-23 实测）**：彩排 / 正式都别在一条命令行里连着开好几个浏览器会话——上一个会话刚关就开下一个时，后台弹窗还没渲染出来，会报 `Locator.click: Timeout 8000ms exceeded`（实测卡在 `run_ads` 的 preflight；同一条命令单独重跑就过，改动前后行为一致）。四条命令连着跑的那次：第 3 条超时，单独重跑全绿。
- **取数只走只读查询接口（2026-09-16 定）**：数据接口在 `csdn-distadmin.csdn.net/admin/`（页面在 `mp-admin`，两个域名）。取数（`fetch_perf.py`）用两个查询接口：**任务组解析 → 按天查工单级 → 按任务查资源级累计**。**不用后台的「导出」**：导出模块会整块失效（2026-09-16 全接口 `code=400600 无权限`）、还会按参数复用旧文件（拿昨天上午生成的半截数据当今天的用，实测差 7 倍）。只读、失败不落盘。接口契约与踩过的坑见 `docs/fetch_perf.md`。
- **写入后台必须回读核对（2026-09-14 定）**：凡"创建类"动作，**点了提交不算成功**——必须回读后台确认落库（列表按名称查 / 回读输入框），查不到就记 `warn`，下次重跑。
  起因：真实创建一轮里连续出现 5 次"脚本报成功、后台其实没有"（圈选 A/E 假通过；工单提交按钮名写错成「创建」，16 项全填对却什么都没建还返回成功；投放日期跨月点错月；分发名单被"圈选用户中"挡住）。只看「弹窗关闭 + `.el-message` 提示」一律不可靠。
- **执行前门控（AI 负责，不进脚本）**：必给 3 项（负责人标识→`taskGroupName` / 子业务线 / 是否新建任务组+名）未提供 → 不启动执行层；由 AI 执行前检测，规矩见 `automation/AGENTS.md`。

> 彩排 / 正式由**运行命令决定**（带 `--submit` 才真创建，不带就是彩排）；`csdn_ui.session(dry_run=…)` 只负责「知道是彩排之后怎么表现」。
> 共用层的验收入口：`.venv\Scripts\python.exe -m unittest discover -s automation/tests -v`（假柜台，不开真浏览器）。

> 执行层 4 步已就绪：任务组 `run_taskgroup.py` / 资源 `run_ads.py` / 圈选 `run_audience.py` / 任务工单 `run_taskorder.py`。
> 另一条路（2026-09-21 起，**两步分开跑，中间人工看数量**）：`run_selection.py`（新数据平台圈选出 CSV，不建后台对象）→ 满意后 `run_distribution_ids.py`（用博文 id 建普通分发名单）；之后的工单照旧走 `run_taskorder.py`。
> 依赖顺序：任务组(可能自动创建) → 资源 → 客群(圈选) → 任务名单(一键创建分发名单) → 任务工单。

## 术语

| 词 | 意思 |
|---|---|
| 整活动 YAML | `activities/{活动名}/配置/{品牌}{负责人}.yaml`，执行层消费的唯一数据对象 |
| 活动定义 YAML | `activities/{活动名}/配置/活动定义.yaml`，物料/整活动 yaml 的上游数据源 |
| 桶（类） | 一个人群分组；1 桶 = 1 客群 = 1 任务工单 |
| 任务组 / 资源 / 客群 / 任务工单 | 后台四个实体，对应执行层第 1–4 步 |
| 圈选 | 按关键词圈出目标用户（第 3 步） |
| 共用层（csdn_ui） | 跟后台页面打交道的知识；四个脚本共用，见「设计原则」 |
| 列表页（list_page） | 列表页这一层：翻开（菜单/页签）/ 筛选 / 查询 / 按名字取行 / 行内按钮 / 勾选；体检「只读」靠它保证 |
| 命令外壳（cli） | 七条命令共用的那套架子：`parser()` 开关 / `context()` 装载 / `Ctx.session()` 会话 / `finish()` RESULT 与退出码；单测 `tests/test_cli.py` |
| 工头（bucket_runner） | 排队的老规矩：逐项跑 / 断点账本 / 失败清场 / 到点止损 / RESULT 三态；四个脚本共用 |
| 命名（naming） | 名字的唯一出处：`{前缀}-{id}类` / `· {topic}` / `· {角色}`；前缀取 `campaign.namePrefix` |
| 装载（campaign） | 整活动 YAML 的唯一入口：解析 / 校验（必填 + 未知字段）/ 补默认值 / 读写 thresholds |
| 取数（fetch_perf） | 把后台投放数据写进**台账库** `activities/_db/投放数据.db`（按天事实 upsert + 资源读数追加），另落一份取数流水：`activities/{活动名}/数据/{取数时刻}/` |
