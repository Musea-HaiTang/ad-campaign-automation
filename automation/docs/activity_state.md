# 活动启停 · `activity_state.py`

> **管什么**：查看活动和切换数据库中的 `activity.status` / `ended_on`。
> **不管什么**：CSDN 后台任务下线 → 人工确认后操作后台；建新批 → `执行层全流程.md`。
> **谁什么时候读**：活动收尾、恢复项目跟进或排查看板/巡检状态时。

## 查看

```powershell
.venv\Scripts\python.exe automation/scripts/activity_state.py list
```

## 收尾

```powershell
.venv\Scripts\python.exe automation/scripts/activity_state.py `
  end "腾讯云产品-hang" --on 2026-10-28
```

## 恢复

```powershell
.venv\Scripts\python.exe automation/scripts/activity_state.py `
  start "腾讯云产品-hang"
```

## 边界

- 只修改数据库，不操作 CSDN 后台。
- `end` 必须提供用户确认的收尾日。
- 恢复只恢复项目内跟进，不恢复已经下线的后台工单。
