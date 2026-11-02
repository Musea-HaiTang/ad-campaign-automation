# 取数 · `fetch_perf.py`

> **管什么**：从 CSDN 后台只读查询工单按天数据和资源累计读数，写入数据库 v2。
> **不管什么**：看板展示 → [`../../web/README.md`](../../web/README.md)；判定 → [`judge_batch.md`](judge_batch.md)。
> **谁什么时候读**：执行取数、补历史、排查数据新鲜度时。

## 命令

```powershell
.venv\Scripts\python.exe automation/scripts/fetch_perf.py `
  --activity "腾讯云产品-hang"
```

指定区间：

```powershell
.venv\Scripts\python.exe automation/scripts/fetch_perf.py `
  --activity "腾讯云产品-hang" `
  --from 2026-10-20 `
  --to 2026-10-20
```

## 参数

| 参数 | 作用 |
|---|---|
| `--activity` | 数据库中的任务组名，必填 |
| `--from` | 起始日，可选 |
| `--to` | 结束日，可选 |
| `--label` | 本次操作标签，只进日志 |
| `--headed` | 显示公共浏览器 |
| `--v2-db` | 数据库路径，默认 `activities/_db/投放数据.db` |

## 刷新口径

- 默认从最近有数据那天补到昨天，记为 `fetch_run.scope='full'`。
- 今天的刷新由看板传 `--from 今天 --to 今天`，记为 `scope='today'`。
- 按天指标按桶批次和日期覆盖写。
- 资源读数每次成功取数追加一条。

## 写入数据库

- `fetch_run`
- `daily_metric`
- `resource_reading`
- `bucket_batch.task_id/task_name/task_state`
- `creative.resource_id/resource_name`

活动、桶、门槛和文案计划由执行脚本的 `workspace_sync` 提前写入，取数不再从 YAML 重建主数据。

## 工单归桶

1. 用后台 task ID 匹配 `bucket_batch.task_id`；
2. 没有 task ID 时用完整工单名匹配；
3. 新工单按完整名称唯一匹配桶后创建批次；
4. 无法唯一匹配时整次取数失败，不猜桶。

## 边界

- 只调用任务列表和资源累计读数两个只读接口。
- 不创建、修改、暂停、审核或下线后台对象。
- 不写 CSV、不写取数流水目录。
- 后台登录失效、任务组不存在或区间无数据时失败，不写半截数据。
