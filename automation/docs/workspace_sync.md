# 执行结果同步到投放数据库

> **管什么**：把执行 YAML 中的桶批次、工单名和资源计划幂等写入投放数据库。
> **不管什么**：真正后台创建动作 → `run_ads.md` / `run_taskorder.md`。
> **谁什么时候读**：执行层需要同步写数据库，或排查新批次在数据库中缺失、重复时。

## 入口

```python
import workspace_sync

workspace_sync.sync_config_batch(
    db_path, cfg, audiences, started_on,
    change_reason="文件名", status="running",
)
```

## 幂等规则

- 同一完整工单名只对应一个桶批次；
- 同一批次槽位只对应一条文案资源；
- 资源和工单创建分阶段执行时，先 `planned`，后更新为 `running`；
- task_id 尚未从后台取得时允许为空，后续 `fetch_perf.sync_metrics()` 按工单名补全。
- 活动、桶、桶批次、文案使用同一数据库事务；中途失败整批回滚，不留下半批记录。

## 脚本入口

```powershell
.venv\Scripts\python.exe -m automation.scripts run-ads --config "..." --submit
.venv\Scripts\python.exe -m automation.scripts run-taskorder --config "..." --submit
```

默认写入 `activities/_db/投放数据.db`；测试或排障时才显式传 `--db`。
