# 执行层文档导航

> **管什么**：按任务找到该读的文档，避免把 `automation/docs/` 从头读到尾。
> **不管什么**：具体业务规则仍以 `ad_output/流程文档/` 为准；YAML 字段以 `../campaigns/README.md` 为准。
> **谁什么时候读**：进入执行、取数、巡检或排障前，先在这里定位；只读对应阶段需要的页面。

## 最常用的入口

| 现在要做什么 | 先读 | 再读 |
|---|---|---|
| 第一次理解执行链 | [`执行层全流程.md`](执行层全流程.md) | [`脚本通用约定.md`](脚本通用约定.md) |
| 准备新建一批 | [`执行层全流程.md`](执行层全流程.md) §0～§3 | 对应 `run_*.md` |
| 跑之前检查配置 | [`check_batch_plan.md`](check_batch_plan.md) | 按需跑 [`check_pool.md`](check_pool.md) |
| 建完后确认后台对象 | [`check_campaign.md`](check_campaign.md) | — |
| 取数、判定、复盘 | [`fetch_perf.md`](fetch_perf.md) | [`judge_batch.md`](judge_batch.md)、[`复盘会话格式.md`](复盘会话格式.md) |
| 看数据库设计 | [`数据库v2说明.md`](数据库v2说明.md) | [`workspace_sync.md`](workspace_sync.md)、[`workspace_payload.md`](workspace_payload.md) |
| 数据库升级或回滚 | [`数据库迁移版本.md`](数据库迁移版本.md) | [`数据库v2说明.md`](数据库v2说明.md) |
| 清理日志和浏览器缓存 | [`磁盘清理.md`](磁盘清理.md) | — |
| 查定时巡检 | [`巡检与自动复盘.md`](巡检与自动复盘.md) | [`judge_batch.md`](judge_batch.md) |
| 查脚本历史性能 | [`执行层实测耗时.md`](执行层实测耗时.md) | — |

## 按文档类型找

**执行脚本**

- 新建：`run_taskgroup.md`、`run_ads.md`、`run_audience.md`、`run_distribution.md`
- B 路径：`run_selection.md`、`run_distribution_ids.md`
- 建工单：`run_taskorder.md`
- 只读核对：`check_batch_plan.md`、`check_pool.md`、`check_campaign.md`、`wait_login.md`

**数据与复盘**

- 取数：`fetch_perf.md`
- 判定与待复盘：`judge_batch.md`
- 巡检编排：`巡检与自动复盘.md`
- 复盘回复格式：`复盘会话格式.md`（用户审批件，不得擅自修改）
- 数据库同步与看板装配：`workspace_sync.md`、`workspace_payload.md`
- 活动启停：`activity_state.md`
- 单文件看板：`visualize_perf.md`

**开发与维护**

- 页面录制：`record_audience.md`、`record_report.md`
- 磁盘维护：`磁盘清理.md`
- 发布前工作：`发布前整改计划.md`

## 阅读纪律

- 建批只看当前这一步和它的直接依赖，不把全部脚本说明当流程文档通读。
- 当前做法看操作文档；为什么这样定看 `ad_output/流程文档/决策台账.md`；实测数据只看 [`执行层实测耗时.md`](执行层实测耗时.md)。
- `复盘会话格式.md` 是审批件。需要修改时，先在对话里说明改什么、为什么改，得到用户当次同意后再落盘。
