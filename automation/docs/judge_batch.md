# 判定与待复盘 · `judge_batch.py`

> **管什么**：从数据库 v2 判断每个桶自己的当前批是否达到曝光门槛，创建待复盘记录并输出短报。
> **不管什么**：复盘对话排版 → [`复盘会话格式.md`](复盘会话格式.md)；复盘内容与文案规则 → `../../ad_output/流程文档/`。
> **谁什么时候读**：自动巡检、人工判定、排查待复盘记录时。

## 命令

```powershell
.venv\Scripts\python.exe automation/scripts/judge_batch.py `
  --v2-db activities/_db/投放数据.db `
  --mark --brief
```

只处理指定活动：

```powershell
... --activity "腾讯云产品-hang"
```

## 参数

| 参数 | 作用 |
|---|---|
| `--v2-db` | 可选，数据库路径；默认 `activities/_db/投放数据.db` |
| `--activity` | 可选，只处理指定 `activity_key`，可重复 |
| `--mark` | 到门槛且仍未复盘时创建 `review.status='due'` |
| `--brief` | 输出运营短报 |

## 判定口径

- 只看每个桶自己的当前批；
- 当前批后台工单状态不是“进行中”时跳过，不拿历史累计读数冒充在投任务；
- 当前批来自 `v_bucket_current`；
- 累计曝光和点击来自最新 `resource_reading`；
- 累计曝光达到该桶门槛后才判点击；
- 达标线为全局千三；
- 不额外增加“每条资源满 1,000 曝光”的门槛；
- 已收尾活动默认跳过。

## 输出

`--brief` 固定先输出：

```text
【本轮结论】需要复盘 / 无需复盘
【需要你处理】
【执行结果】
【桶进度】
```

要求：

- 有需要复盘的桶时全部列出；
- 有在跑任务且无需复盘时，只列最接近门槛的前 3 个桶；
- 没有在跑任务时只报“当前没有任务进行 / 无在跑任务”，不展示历史桶进度；
- 指标由脚本计算，AI 不重算；
- 不输出 `STATUS:` 长行；
- 不写 Markdown 待办文件。

## 后续动作

有 `review.status='due'` 时：

```powershell
.venv\Scripts\python.exe automation/scripts/review_queue.py `
  --db activities/_db/投放数据.db list
```

复盘对话正文按 [`复盘会话格式.md`](复盘会话格式.md) 输出。
