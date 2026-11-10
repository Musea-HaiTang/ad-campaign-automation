# AGENTS.md — automation（执行层）

> 把「整活动 YAML」变成 CSDN 后台对象：任务组 / 资源 / 客群 / 任务工单。
> **这份文件是索引，不是说明书**：每一步怎么做、在哪停 → [`docs/执行层全流程.md`](docs/执行层全流程.md)；为什么这么设计、环境怎么配 → [`README.md`](README.md)；某个脚本的开关与坑 → `docs/<脚本名>.md`；YAML 字段 → [`campaigns/README.md`](campaigns/README.md)。

## 动手前必知（硬规则）

- **默认 dry-run**（只填 + 校验 + 截图，不点提交），`--submit` 才真建；**没让执行就不执行**。
- **一步一停**：一步跑完 → 给用户看后台效果 → 确认后才下一步。**建批一律直接 `--submit`**（这条路径本身就是「填完 → 逐字段回读 → 全过才点确定」），不再单跑一遍彩排。
- **执行前门控**（AI 检测，不写在脚本里）：负责人标识→`taskGroupName` / 子业务线 / 是否新建任务组+名字 / 投放日期 + 时间段——缺一项**不启动**。
- **提交闸门 + 回读**：任一字段没过 → 关弹窗、不提交、记 `warn`；提交后必须回后台列表**按名字核对**（「弹窗关了 + 有提示」不算成功）。
- **模式二恢复**：正常新建不预读后台；点提交前写 `submitting`。只有上次中断/未确认的项才做定点对账：`FOUND` 复用、`ABSENT` 重做、`UNKNOWN` 停住，禁止整批预读或盲重建。
- **回读只认精确身份**：完整名称精确行 / 完整资源名；禁止整页包含、桶名前缀、任务名尾号单独判成功。
- **圈选一律安排下午**（上午后台数据集还在写入，早上跑 = 白跑）；**走 A 路径还是 B 路径先问用户**，AI 不自行选。
- **一次只跑一条命令**；两个 `--submit` 脚本不能同时跑（写锁会拦下第二个）。

## 写代码时

- **只用共用层，别重写**：页面动作 `scripts/csdn_ui.py`、列表页 `scripts/list_page.py`、命令外壳 `scripts/cli.py`（开关 / 装载 / 账本 / RESULT）、排队与止损 `scripts/bucket_runner.py`、远端三态 `scripts/execution_state.py` / `scripts/remote_lookup.py`、命名 `scripts/naming.py`、YAML 装载 `scripts/campaign.py`。各 `run_*.py` 只写「这次要办什么」。
- **等待只用条件等待**（`csdn_ui.wait_for()` / `visible_input()` / `click_query()` / `table_has_rows()`）——不许新增固定 `wait_for_timeout` 死等。
- **装载只走 `campaign.load(路径)`**：不许 `cfg.get("字段", 默认值)` 自兜底——字段写错要启动就报错，别跑到浏览器第 3 步。
- **列表页只读**：`list_page` 不提供新建 / 提交 / 确定；写入只留在各 `run_*.py` 的提交闸门里。
- **浏览器只有一只**：`scripts/browser_broker.py`（独立 Edge/Chrome，首选 CDP 9222，冲突时写入实际端口）——不许再写 `launch_persistent_context`。
- **改共用层就配单测**：`automation/tests/`（假柜台，不开真浏览器），用仓库 venv 跑 `-m unittest discover -s automation/tests -v`；Windows 解释器是 `.venv\Scripts\python.exe`，macOS 是 `.venv/bin/python`。

## 必读

| 文件 | 作用 |
|---|---|
| [`docs/执行层全流程.md`](docs/执行层全流程.md) | 每一步做什么、用哪个脚本、读哪份文档、在哪停（**建批从这页开始**） |
| [`README.md`](README.md) | 执行层总览 / 设计原则 / 环境（跑之前先看） |
| [`campaigns/README.md`](campaigns/README.md) | 整活动 YAML 字段规范（AI 生成依据、脚本消费契约） |
| `scripts/` 的共用层 + `tests/` | 改后台交互 / 列表页 / 外壳 / 工头 / 远端对账 / 命名 / 装载，只改这些 |
| `docs/*.md` | 各脚本说明书 + 巡检配置 + 实测耗时 |
