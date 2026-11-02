# 单文件看板导出 · `visualize_perf.py`

> **管什么**：从数据库 v2 生成一个可双击、可转发的独立 HTML 看板。
> **不管什么**：实时服务 → [`../../web/README.md`](../../web/README.md)；取数 → [`fetch_perf.md`](fetch_perf.md)。
> **谁什么时候读**：需要归档或把某次看板发给别人时。

## 命令

```powershell
.venv\Scripts\python.exe automation/scripts/visualize_perf.py `
  --activity "腾讯云产品-hang"
```

指定输出：

```powershell
... --activity "腾讯云产品-hang" --out .\看板.html
```

## 参数

| 参数 | 作用 |
|---|---|
| `--activity` | 数据库中的任务组名，必填 |
| `--db` | 数据库路径，默认 `activities/_db/投放数据.db` |
| `--out` | 输出文件；不填则落到对应活动 `数据/看板/` |

## 数据来源

- 使用 `workspace_payload.build_payload()`；
- 与服务版看板读取同一个数据库、同一套聚合口径；
- 只读，不联网、不写数据库。
