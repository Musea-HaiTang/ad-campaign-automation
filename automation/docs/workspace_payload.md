# 数据库 v2 看板装配

> **管什么**：从 v2 数据库生成现有看板同形的 payload。
> **不管什么**：网页服务与控件 → [`../../web/README.md`](../../web/README.md)；取数 → [`fetch_perf.md`](fetch_perf.md)。
> **谁什么时候读**：修改看板字段、排查 `/api/perf` 数据时。

## 入口

```python
import workspace_payload

payload = workspace_payload.build_payload(conn, activity_id, today="2026-10-28")
```

`conn` 必须是通过 `workspace_repo.connect()` 打开的 v2 数据库。

## 已对齐字段

- 活动名称和活动 ID；
- 日期列表与未完成日；
- 桶、当前批、参考批、门槛；
- 每日桶数据与各口径合计；
- 工单和逐日序列；
- 资源级最新读数；
- 批次统计；
- 批次判定和已保存的复盘动作。

`batchStats.runDays` 按任务状态计算：`进行中` 从首个有数据日算到今天，`下线` 等非进行中状态冻结在最后一个有数据日。

## 网页入口

```powershell
.venv\Scripts\python.exe web/app.py --db automation/_tmp/投放数据.db
```

取数只写数据库 v2；页面数据也从 v2 读取。

## 当前边界

- 默认启动入口直接使用 v2；
- 取数只写数据库 v2；
- 待复盘接口读 `review`；
- 不读写旧库。
