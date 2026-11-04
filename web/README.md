# 投放看板

> **管什么**：看板页面、本地 HTTP 服务、按活动取数、自动刷新和待复盘入口。
> **不管什么**：执行参数与后台建对象 → [`../automation/README.md`](../automation/README.md)；复盘正文 → [`../automation/docs/复盘会话格式.md`](../automation/docs/复盘会话格式.md)。
> **谁什么时候读**：启动看板、排查取数/页面问题、修改活动列表时。

## 唯一数据源

`activities/_db/投放数据.db`

- 活动、桶、桶批次、文案、按天指标、资源读数、取数记录和复盘都在这里。
- 看板只读该库。
- 数据库中的活动即使没有对应 YAML，也可以只读展示历史和指标；YAML 只在实际执行新批次时提供参数。
- 取数成功只写当前正式库，不生成 CSV 流水。
- 历史快照只放在 `activities/_db/backups/`，运行期不读取。

趋势图中的棕色批次上线标记按起投日聚合：悬停看汇总，点击查看该日全部批次，避免多个产品同日上线时文字重叠。

## 启动与停止

推荐双击：

- `web/start-hidden.vbs`：无窗口启动看板服务。
- `web/browser-status.bat`：查看公共浏览器状态。
- `web/scripts/browser-stop.bat`：关闭公共浏览器。

命令行：

```powershell
.venv\Scripts\python.exe automation/scripts/board_service.py --start
.venv\Scripts\python.exe automation/scripts/board_service.py --status
.venv\Scripts\python.exe automation/scripts/board_service.py --stop
```

服务默认使用 `http://127.0.0.1:8770/`；端口冲突时自动向后寻找。实际地址以 `board_service.py --status` 或 `--url` 为准。
看板带项目目录级单实例锁；重复启动会复用已经健康运行的那一个，并清理旧的多余实例。状态文件丢失时会从实际监听端口找回看板。后台的端口和进程检查不显示控制台窗口。

## 数据流

```text
CSDN 只读查询接口
  → automation/scripts/fetch_perf.py
  → activities/_db/投放数据.db
  → workspace_payload.build_payload()
  → /api/perf
  → web/static/
```

页面上的两个动作：

- **取数**：补历史到昨天；每个活动每天最多一次。
- **刷新**：只刷新今天，可随时执行。

取数由看板进程里的单取数线程串行执行，共用 `browser_broker.py` 启动的公共浏览器。

## 自动刷新

调度线程每 30 秒检查一次状态，但同一活动默认每 30 分钟才自动执行一次：

1. 今天还没完整取数：先跑 `full`，固定昨天终值；
2. 已经取过：按间隔刷新今天；
3. 活动已收尾且过了 2 天补数窗口：不再自动刷新。

成功和失败都算一次自动尝试；失败后同样等满 30 分钟再重试。后台查不到任务组这类永久错误会暂停该活动的自动重试，页面上保留错误原因；修正配置或后台状态后可手动重试。

关闭自动刷新：

```powershell
.venv\Scripts\python.exe -u web/app.py --auto 0
```

## 接口

| 接口 | 作用 |
|---|---|
| `GET /api/health` | 本项目看板身份、PID、实际端口和数据库路径 |
| `GET /api/activities` | 活动列表和库内数据状态 |
| `GET /api/perf?activity=...` | 单个活动的 v2 看板数据 |
| `GET /api/todo` | 所有活动的待复盘项 |
| `GET /api/snapshots?activity=...` | 数据库 `fetch_run` 取数凭据 |
| `GET /api/fetch/status` | 单活动取数状态 |
| `GET /api/fetch/status?all=1` | 整批取数进度 |
| `POST /api/fetch` | 取数到昨天 |
| `POST /api/fetch?today=1` | 刷新今天 |

页面「取数 / 刷新」默认带 `all=1`，会串行处理全部在投活动。

## 代码位置

| 文件 | 作用 |
|---|---|
| `web/app.py` | HTTP 服务、取数队列、自动刷新 |
| `web/static/` | 页面、样式和前端逻辑 |
| `automation/scripts/fetch_perf.py` | 后台只读取数与 v2 写入 |
| `automation/scripts/workspace_payload.py` | 数据库 v2 → 看板 JSON |
| `automation/scripts/workspace_review.py` | 到门槛判断与复盘短报 |
| `automation/scripts/visualize_perf.py` | 从 v2 导出单文件看板 |

## 修改后验证

```powershell
.venv\Scripts\python.exe -m pytest -q automation/tests
.venv\Scripts\python.exe automation/scripts/board_service.py --start
```

然后打开 `--status` 或 `--url` 输出的实际地址，检查活动切换、数据截止日、取数状态和待复盘角标。
