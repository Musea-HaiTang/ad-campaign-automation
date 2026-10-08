# CSDN 客群 · 圈选用户 数据驱动自动化（创建关键词博客ID圈选任务）

> 与 `run_ads.py`（建资源）平级、互不依赖。消费同一份整活动 YAML
> （`activities/{活动名}/配置/{品牌}{负责人}.yaml`），逐桶（A~G）创建「圈选任务」。
> 只走「圈选用户」这一执行层；分发名单是后续独立执行步，不在本脚本内。
> ⚠ **跑圈选（A 路径）一律安排在下午**：后台数据集每天上午还在写入、一般中午才写完，早上圈出来的数偏小
> （同款 58 词实测：10:2x = 7,816 → 11:0x = 67,207）。理由见流程文档 §5.1。
> **B 路径（`run_selection.py`，数据平台导 CSV）没有这条约束**——随时可导（2026-09-29 用户定）。

## 流水线位置

对应 §5.4 / §8 的「客群（圈选用户）」。后台实体 = **客群**，每桶 1 个。
数据来源：`audiences[].keywordGroup.keywords` + 派生任务名 + 每活动子业务线。

## 构架（拆开 + 断点续跑，排队/止损在工头里）

```
automation/
├── scripts/
│   ├── bucket_runner.py   # 共用层（工头）：逐项排队 / 断点账本 / 止损 / RESULT 口径
│   ├── cli.py             # 共用层（命令外壳）：开关 / 装载 / 账本路径 / 会话 / RESULT 行与退出码
│   └── run_audience.py    # 本执行器：逐桶创建圈选任务（dry-run 默认不开、不点确定）
├── docs/
│   └── run_audience.md    # 本文件
└── .. 活动数据：`../activities/{活动名}/配置/{品牌}{负责人}.yaml`（唯一消费对象）
```

与 `run_ads.py` 同构，排队/断点/止损都由 `bucket_runner.py`（工头）负责：**每桶独立 `try/except`**，失败后关弹窗；**首桶失败 / 连续 3 桶失败即中止**；
跑前读「已完成清单」（`../activities/{活动名}/日志/audience_progress.json`）：**已创建的桶永远跳过**，只是彩排校验过的桶在正式跑时会重跑并真正创建（要全部重跑加 `--reset-progress`）；**彩排里「字段校验」没全过的桶记 `warn`**（下次会重跑），全过才记 `done`；
**截图 `aud_X_filled.png` 仅 dry-run 产生，正式 `--submit` 不截图**；`RESULT: OK / HAS_WARN / HAS_FAILURES`（只有 `OK` 返回 0）。

`--tune` 模式也走同一个循环，但**不记账本**（它不创建任何东西）。

## 操作链（一次真实录得，去重后）

| # | 动作 | 数据源 / 选择器 | 必填 | 说明 |
|---|---|---|---|---|
| 0 | 菜单 `圈选用户` → Tab`博文圈选任务` → 按钮`创建圈选任务` | `page.get_by_text('圈选用户')` → `.el-tabs__item:has-text('博文圈选任务')` → `.el-button--primary:has-text('创建圈选任务')` | 入口 | 打开表单 |
| 1 | 填**关键词列表**（textarea） | `textarea[placeholder='请输入关键词,按（中英文）逗号分割']` | ✓ | 整行逗号分隔，`audiences[].keywordGroup.keywords` |
| 2 | 填**数据阈值控制**两个数 | `.el-form-item:has-text('数据阈值控制')` 下第 1/第 2 个 `input.el-input__inner` | ✓ | 点击需≥`0`、曝光需≥`1`（`--click-threshold 0 --exposure-threshold 1`） |
| 3 | 点**idf分析与总数预估** | `button:has-text('idf分析与总数预估')` | ✓ | 触发圈中数量预估 |
| 4 | 读**预估圈选总数** | 文本 `预估圈选总数：<数字>个` | ✓ | = 这行词能匹配到多少**篇博文**（**不是曝光**）：<25000 → 太少（改词），>200000 → 太多（升点击），当场自动调 |
| 5 | 点表单内**创建圈选任务** | 表单 dialog 内 `.el-button--primary:has-text('创建圈选任务')` | 条件 | 打开确认层（仅当第 4 步在正常范围） |
| 6 | 选**子业务线/用户组** | `input[placeholder='请选择子业务线/用户组']` → 下拉选项 = `audiences[].subBusinessLine` | ✓ | **每活动不同**（示例：`训练营与大赛`） |
| 7 | 填**圈选任务名称** | `input[placeholder='请输入用户名称']` | ✓ | 派生：`{namePrefix}-{id}类 · {topic}`（如 `{品牌}{负责人}-A类 · AI 编程核心`）；唯一实现在 `../scripts/naming.py` |
| 8 | 点**确定** | `.el-button--primary:has-text('确定')` | 提交 | dry-run 只填+校验，不点确定；`--submit` 才点 |

## 圈选总数提醒逻辑

读 `预估圈选总数` 后：
- `count < min`（默认 **25000**）：**太少**；`count > max`（默认 200000）：**太多**。
- 越界 → **当场自动调阈值**（不跳过、不用你跑第二趟）：**只升点击 1..4、曝光锁死 1**，
  取**第一个 ≤上限且 ≥下限**的组合。
  - 搜到落点 → 打印落点，继续走确认/创建，并把结果写回 `thresholds.yaml`（下次不用再搜；**盖格子**，只改这一桶）；
  - 搜不到（或压根读不到数字）→ 打印原因并**跳过该桶**，建议改关键词——**不硬选**；
  - **最多试 5 次**，到顶就收手。
    正式跑刚读过的基线会**直接传给策略**当起点，不再把同一组阈值读第二遍
    （重复读不但白花一次分析，数字没变化还要等满 25 秒兜底超时；实测省约 25 秒/越界桶）。

> **曝光阈值锁死 1**（用户 2026-09-21 定）：「日常就设置曝光1，博文数量越多越好，这样曝光就会大」。
> 不再有「偏低就降曝光到 0」这一步——**曝光=0 是虚池**：池子大 2.2~24 倍，日均曝光反而低 2.8~11 倍
> （`audience_policy.py` 模块注释里有实测数据）。偏低 = 词不够，去改词。
> 下限 10000 → **25000** 也是同一天定的：按「日均曝光 ≈ 圈选数 × 0.4」倒推，保底 1 万曝光要约 2.5 万篇。
>
> 阈值控制（点击≥X / 曝光≥Y）就是把圈中量拉回正常区间的旋钮。搜索规则本身是纯函数，
> 在 `../scripts/audience_policy.py`（可脱浏览器测，见 `../tests/test_audience_policy.py`）；
> 脚本里只剩「设阈值 → 点分析 → 读数字」这一个动作。

## 达标口径：建完才看得到（2026-09-21 加）

**`预估圈选总数` 不是曝光**，别拿它当达标依据。真正的口径是后台「**博文圈选任务**」列表那四列：

```
创建时间 | 实际圈选博客ID数 | 日均点击(预估) | 日均曝光(预估) | 日均pv(预估) | 关键词列表 | ...
```

- **创建弹窗里没有这几项**（弹窗只有「预估圈选总数」+ idf 分词表）；要**建完、等后台「圈选用户中…」跑完**才刷出来 → 判断天然在创建之后。
- 达标线：**日均曝光(预估) 目标 ≥ 20000、底线 ≥ 10000**（当期口径由用户给）。
- 一条命令读：`check_campaign.py --only audience`（详见 `check_campaign.md`），不达标 → **改词重投**（客群重名建不了，重投带后缀）。

### `--verify`：建完不关浏览器，每 10 秒点一次「查询」（2026-09-21 加）

```powershell
# 真建 + 就地体检（浏览器一直开着，页面不重开）
.venv\Scripts\python.exe -u automation/scripts/run_audience.py --config <yaml> --submit --verify

# 间隔/上限可调（默认 10 秒 / 900 秒）
... --submit --verify --verify-interval 5 --verify-timeout 1800
```

- 只对**这一趟真建成的桶**轮询（跳过/标 `needs_keywords` 的没得看）；实测**创建后 10~26 秒数据就刷出来了**。
- 实测出数要 **1~5 分钟**（2026-09-21 五桶：快的 80 秒，慢的 4~5 分钟）——轮询间隔 10 秒、上限给到 600~1800 秒比较稳；
  赶时间可以把 `--verify-timeout` 调小，之后也能用 `check_campaign.py --only audience` 再补看。
- 每轮日志：`第 N 次查询：已出数 x/y | 还等：…`；出齐（或到上限）后打达标表。
- `--verify` 只在 `--submit` 时有意义（彩排跳过）。
- 读数/判定/轮询实现在共用层 `../scripts/audience_metrics.py`（单测 `../tests/test_audience_metrics.py`）。
- ⚠ **数字受"什么时候量"影响很大**：后台数据集每天上午还在写入、一般中午才写完，
  同款 58 词实测 10:2x = 7,816 → 11:0x = 67,207。**只认下午量到的数**（见流程文档 §5.1）。

### `--name-suffix`：下午先"试圈"一版看数据（2026-09-21 加）

```powershell
# 用正式配置里的真实词表建一遍，但名字带后缀 → 不动正式客群名、也不占正式账本
.venv\Scripts\python.exe -u automation/scripts/run_audience.py --config <yaml> \
    --submit --verify --name-suffix=-试圈 --min-count 1000

# 看完数据不满意：删掉试圈那批
... --config <yaml> --delete "火山引擎MediaKit-hang-A类 · AI 编程 / Agent 工具-试圈"
```

- 试圈的断点账本单独一个文件（`日志/audience_progress.试圈.json`），**不污染正式账本**。
  （踩坑：不带后缀时正式账本记着 `submitted`，试圈一个都不会建、还空等轮询。）
- 用途就是流程 §5 那条：**下午圈选 → 看「日均曝光(预估)」→ 满意才用正式名建**。

### `--delete`：不满意就删掉（用户 2026-09-21 给的步骤）

```powershell
.venv\Scripts\python.exe -u automation/scripts/run_audience.py --config <yaml> --delete "圈选任务名" [--delete "另一条"]
```

按用户给的步骤走：每行先点「**停止**」→ 勾选该行 → 点工具条「**批量删除**」→ 弹窗确认；
删完回列表复读核对，全没了才返回 0。**只动圈选任务**，绝不碰资源 / 分发名单 / 任务工单。

**`--tune`**：只调不建（给人单独看落点用），走的是**同一套策略**，结果写
`activities/{活动名}/配置/{品牌}{负责人}.thresholds.yaml`（每桶 `click/exposure/count/status/base`）。
`--submit` 读该文件（未写出的桶按默认 `0/1`）。

两条写回路径（`--tune` 整批 / 正式跑当场自动调落点单条）走**同一个入口** `run_audience.save_thresholds()`，
且都是**盖格子**（只改这次跑到的桶）；每条记录的栏位形状只在 `campaign.threshold_record()` 定义一次——
对象（`r.click`）和字典（`r["click"]`）都收，加栏位只改那一处（2026-09-23 收口）。

**提交后回读核对（2026-09-14 加）**：`--submit` 点完「确定」不再直接记账——会**重新打开列表、按圈选任务名查找**，
查得到才记 `submitted`，查不到记 `warn`（下次重跑这一桶，结尾 `RESULT: HAS_WARN`）。
原因：老实现只看「弹窗关掉 + `.el-message` 里有提示」，后台没落库也算成功——实测 A、E 各踩过一次"假成功"
（特征是提示只有 1 个「操作成功！」，而真正建成时是 2 个）。代价：每桶多约 3~5 秒。

**提交前闸门（2026-09-22 加）**：`--submit` 在点「确定」**之前**先看字段校验——圈选任务名 / 子业务线
任一回读不过就**关弹窗、不提交**，记 `warn`（下次重跑这一桶）。
原来正式路径不看这个 `ok`、照样点「确定」，而回读只查"任务名在不在列表里"，**查不出字段缺失**
（名字对、子业务线没绑上这种事它发现不了）。彩排口径不变（校验没全过照样记 `warn`）。
单测：`../tests/test_run_audience.py`（假页面，验"校验没过只点取消、绝不点确定"）。

**回读也改成条件等待（2026-09-22）**：`verify_created()` 里原来固定死等 1200ms 再找任务名，
现在**等任务名真的出现在列表里**（最多 8 秒）——后台快就少等，慢也不会误判成"没建成"。
另外 `open_form()` 每桶都调一次的清弹窗现在**先看有没有弹窗**（`csdn_ui.dismiss_dialogs()`）：没有就直接返回，
不再白按一次 Escape + 等 400ms（7 桶省约 3 秒）。
**实测（2026-09-22 彩排，5 桶 dry-run）**：78.5 秒 → 77.8 秒 —— **差异在噪声内**：这条路的时间几乎全在
后台 idf 分析与总数预估（14~18 秒/桶），脚本侧那点等待只占零点几秒。闸门与回读同样只在 `--submit` 路径上跑。

## 字段规范（沿用 campaign yaml）

读取的字段：
- `campaign.taskGroupName`：任务组名前缀（派生任务名用，现为 `{品牌}{负责人}`）
- `audiences[].id` / `.topic`：派生 `{taskGroupName}-{id}类 · {topic}`
- `audiences[].keywordGroup.keywords`：关键词整行
- `audiences[].subBusinessLine`：子业务线（每活动同值）

> `audiences[].taskName` 字段**由执行器派生覆盖**，yaml 里可不填/仅参考。

## 怎么跑

```powershell
# dry-run：只填 + 读总数 + 校验，不点「确定」（默认）
.venv\Scripts\python.exe -u automation/scripts/run_audience.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml

# 调优（可选）：只对超范围桶找阈值、写报告 + thresholds 文件，不创建
# 注：正式跑/彩排遇到越界本来就会当场自动调，--tune 只用于「先看一眼落点」或批量体检
.venv\Scripts\python.exe -u automation/scripts/run_audience.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml --tune

# 真正创建：加 --submit
.venv\Scripts\python.exe -u automation/scripts/run_audience.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml --submit

# 阈值/区间可调、重置进度（下限 2026-09-21 由 10000 抬到 25000）
... --click-threshold 0 --exposure-threshold 1 --min-count 25000 --max-count 200000 --reset-progress
```

前置：python 3.12 装 `playwright`、`pyyaml`；浏览器 `D:\playwright-browsers`；
登录 profile `D:\Codex_WorkingSpace\ad_management\.browser-profile`（cookie 过期需重登）。
启动浏览器需提权。

## 已知坑
- 表单内「创建圈选任务」与列表页同名，务必**限定在弹窗 dialog 内**点，避免点错。
- 两个阈值输入无 placeholder，需按「数据阈值控制」form-item 内序号区分（第1=点击，第2=曝光）。
- 分析后读总数是**显示文本**，用正则抓 `预估圈选总数：(\d+)个`；没出现说明分析未完成，先条件等待。
- 越界且自动调不到落点时，要 **关掉表单弹窗** 再进下一条，否则下一条点「创建圈选任务」会因弹窗已开而错乱（脚本已处理）。
- `goto` 用 `domcontentloaded`；`networkidle` 会因 SPA 长连接卡住。运行加 `python -u` 看实时输出。
