# CSDN 广告投放自动化

> **管什么**：项目入口、安装与启动、目录边界、常用命令和文档导航。
> **不管什么**：具体投放 SOP、执行脚本字段和数据库结构，分别指向对应文档。
> **谁什么时候读**：第一次接触项目、准备启动看板、定位文档或排查环境问题时。

这个项目把 CSDN 广告投放从人工串联做成一条可追踪的流程：

```text
活动链接
  → 产品与人群拆分
  → 文案与投放物料 HTML
  → 用户确认
  → 整活动 YAML
  → 后台建任务组 / 资源 / 客群 / 任务工单
  → 数据取入 SQLite
  → 看板查看与自动复盘
```

## 当前状态

当前版本已完成 P0 发布阻断项和 P1 长期维护整改，并已在独立干净工作空间通过一键部署、
自动化测试、动态端口、CSDN 双站登录、备份恢复、缓存清理和发布预检验收。

普适化首版已发布到私有仓库：
[Musea-HaiTang/ad-campaign-automation](https://github.com/Musea-HaiTang/ad-campaign-automation)。

第一次接触项目时，先读[运营使用说明](运营使用说明.md)；也可以把这份说明交给 AI，让它按文档向其他运营讲解。

首次使用需要：

- 新建独立工作空间后再执行一键部署；
- 在部署后的浏览器中分别登录 CSDN 广告后台和 `data.csdn.net`。

## 环境要求

- Windows 10/11
- PowerShell
- Python 3.12-3.14
- Microsoft Edge 或 Google Chrome
- 可访问 CSDN 后台和相关数据平台的网络环境

项目固定使用仓库根目录下的虚拟环境，不依赖系统默认 `python`：

```powershell
.venv\Scripts\python.exe
```

## 快速开始

> ⛔ **AI 部署闸门**：执行任何部署命令前，必须先确认用户已经新建独立工作空间，并将项目克隆或放入该工作空间。建议将新工作空间目录命名为 `ad_management`，项目根目录就是该目录。未确认时 AI 必须停止，不得安装依赖、初始化数据库或开始登录，也不得复用原操作者的工作空间。确认后，在该工作空间的项目根目录执行一键部署命令，后续配置和日常办公也都在这里完成。

以下命令均在仓库根目录执行。

### 1. 一键部署

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

首次运行会提示输入负责人标识 `owner`；后续部署会直接复用 `.local/operator.json`，不会覆盖已有环境或数据库。

空数据库会写入一份脱敏示例活动，包含两个桶、两个已收尾批次和三天离线指标，用于首次启动看板。已有真实活动的数据库不会写入示例。

如果自动检测失败，可以显式指定：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 `
  -Owner "hang" `
  -Python "<Python 3.12-3.14 解释器路径>" `
  -Browser auto
```

### 2. 手动创建虚拟环境

```powershell
python --version
python -m venv .venv
```

确认 `python --version` 显示 Python 3.12-3.14 后，才能直接执行第二条命令。
如果不确定或默认 `python` 版本不兼容，请显式使用任意一个已安装的 Python 3.12-3.14：

```powershell
& "<你的 Python 3.12-3.14 安装目录>\python.exe" -m venv .venv
```

### 3. 手动安装依赖和浏览器

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

公共浏览器使用本机 Microsoft Edge 或 Google Chrome，并保存在仓库内的 `.browser-profile/`。

### 4. 运行测试

```powershell
.venv\Scripts\python.exe -m pytest -q
```

测试使用假柜台，不需要登录 CSDN，也不创建后台对象。

### 5. 首次登录与环境诊断

```powershell
.venv\Scripts\python.exe scripts\doctor.py --login
```

按提示分别登录 CSDN 广告后台和数据平台。广告后台登录成功后，当前用户名会保存到 `.local/operator.json`。

以后只做只读检查：

```powershell
.venv\Scripts\python.exe scripts\doctor.py
```

### 6. 运行一次离线示例

```powershell
.venv\Scripts\python.exe automation/scripts/check_batch_plan.py --config "activities/_示例活动/配置/示例活动-hang.yaml"
```

`_示例活动` 是脱敏配置，不会进入正式看板的活动下拉。

### 7. 启动看板

已有 `activities/_db/投放数据.db` 时：

```powershell
.venv\Scripts\python.exe automation/scripts/board_service.py --start
.venv\Scripts\python.exe automation/scripts/board_service.py --status
```

然后打开：

```text
http://127.0.0.1:8770/   # 首选地址；冲突时以 --status / --url 输出的实际地址为准
```

也可以双击 `web/start-hidden.vbs` 无窗口启动。

空数据库会自动初始化脱敏示例；已有真实活动时不会写入示例。

## 完整业务流程

1. 从活动链接提取产品、卖点、人群和目标。
2. 拆分人群桶，确定关键词、资源和复盘门槛。
3. 编写文案，并生成人可阅读的投放物料 HTML。
4. 用户确认物料后，生成整活动 YAML。
5. 先跑 dry-run 检查名称、数量、AB 权重和日期。
6. 显式使用 `--submit` 后才在 CSDN 后台创建对象。
7. 取数写入 SQLite，在看板查看表现并进入复盘。

权威业务流程见：

- [CSDN 广告投放自动化流程](ad_output/流程文档/CSDN广告投放自动化流程.md)
- [自动化执行层全流程](automation/docs/执行层全流程.md)
- [脚本通用约定](automation/docs/脚本通用约定.md)

## 目录说明

| 目录 | 作用 |
|---|---|
| `activities/` | 活动配置、物料、执行 YAML；运行历史统一进入数据库 |
| `ad_output/` | 业务流程、文案规则、物料模板和 YAML 生成工具 |
| `automation/` | 后台执行脚本、数据库接口、取数、判定和自动复盘 |
| `web/` | 本地看板服务与前端页面 |
| `scripts/` | 项目级维护和发布脚本 |
| `automation/tests/` | 不打开真实浏览器的自动化测试 |

详细说明：

- [看板说明](web/README.md)
- [执行层说明](automation/README.md)
- [文档导航](automation/docs/README.md)

## 常用操作

| 操作 | 命令或入口 |
|---|---|
| 查看看板状态 | `.venv\Scripts\python.exe automation/scripts/board_service.py --status` |
| 停止看板 | `.venv\Scripts\python.exe automation/scripts/board_service.py --stop` |
| 查看公共浏览器 | `.venv\Scripts\python.exe automation/scripts/browser_broker.py --status` |
| 停止公共浏览器 | `.venv\Scripts\python.exe automation/scripts/browser_broker.py --stop` |
| 重新登录 CSDN | `.venv\Scripts\python.exe automation/scripts/wait_login.py` |
| 环境诊断 | `.venv\Scripts\python.exe scripts\doctor.py` |
| 首次登录并保存用户名 | `.venv\Scripts\python.exe scripts\doctor.py --login` |
| 备份数据库 | `.venv\Scripts\python.exe automation/scripts/db_backup.py` |
| 只读校验数据库快照 | `.venv\Scripts\python.exe automation/scripts/db_restore.py check <快照>` |
| 恢复数据库快照 | `.venv\Scripts\python.exe automation/scripts/db_restore.py restore <快照> --confirm` |
| 清理日志和临时文件 | `.venv\Scripts\python.exe automation/scripts/cleanup.py` |
| 停止后清理浏览器缓存 | `.venv\Scripts\python.exe automation/scripts/cleanup.py --browser-profile` |
| 运行一次巡检 | `.venv\Scripts\python.exe automation/scripts/patrol.py` |
| 运行全部测试 | `.venv\Scripts\python.exe -m pytest -q` |
| 检查批次计划 | `.venv\Scripts\python.exe automation/scripts/check_batch_plan.py --config <YAML>` |

双击入口也保留在 `web/` 下，适合不习惯命令行的运营人员。

## 数据与安全边界

- `activities/_db/投放数据.db` 是活动、批次、指标和复盘等长期状态的唯一真相。
- 数据库备份位于 `activities/_db/backups/`；手动运行备份命令默认保留最近 7 份本工具快照。
- 恢复数据库前先停止看板和取数；恢复命令还会自动保存一份 `pre-restore` 当前库快照。
- 浏览器停止时最多每 7 天检查缓存；登录 Cookie、Local State、Preferences 和扩展配置不会被清理。
- YAML 只保存当前配置或一次性执行载荷，不保存历史运行状态。
- 活动配置、业务文案和执行脚本分离；数据库、日志、浏览器 profile 和客户物料不进入公开仓库。
- `.browser-profile/` 是本机浏览器缓存和登录态，不随项目复制；新部署者应在自己的独立工作空间重新登录。
- 创建类脚本默认 dry-run；只有显式 `--submit` 才会写 CSDN 后台。
- 同一时间只运行一个 `--submit` 写入流程，避免后台对象重复创建。
- 不确定远端是否已创建时先对账，按照 `FOUND / ABSENT / UNKNOWN` 处理，不盲目重试。

数据库职责、迁移和备份规则见
[数据库 v2 说明](automation/docs/数据库v2说明.md)，逐版本变化和回滚步骤见
[数据库迁移版本](automation/docs/数据库迁移版本.md)。

## 常见问题

### 为什么不能直接运行 `python`？

系统 Python 可能版本不对或没有安装依赖。统一使用：

```powershell
.venv\Scripts\python.exe
```

### 看板显示没有活动

说明当前数据库没有可展示活动。全新环境的示例活动初始化闭环仍在 P0-4 中处理；已有数据库时先检查
`activities/_db/投放数据.db` 是否存在。

### 看板地址打不开

```powershell
.venv\Scripts\python.exe automation/scripts/board_service.py --status
```

如果启动失败，查看 `%TEMP%\board_service.log`。不要在未确认进程归属时重复启动第二个看板。
启动成功后用 `--status` 或 `--url` 查看实际端口；`8770` 只是首选值。

### CSDN 页面能打开，但脚本说没有登录

页面能打开不等于登录身份完整。运行：

```powershell
.venv\Scripts\python.exe automation/scripts/wait_login.py
```

确认用户名和登录 Cookie 都恢复后再继续。

### 浏览器或页面失活

```powershell
.venv\Scripts\python.exe automation/scripts/browser_broker.py --status
.venv\Scripts\python.exe automation/scripts/browser_broker.py --stop
```

下一次取数或执行会自动重新启动公共浏览器。

## 遇到问题先看哪里

| 问题 | 优先阅读 |
|---|---|
| 不知道完整投放流程 | [CSDN 广告投放自动化流程](ad_output/流程文档/CSDN广告投放自动化流程.md) |
| 不知道执行顺序或在哪停 | [执行层全流程](automation/docs/执行层全流程.md) |
| 脚本参数、恢复和退出码 | [脚本通用约定](automation/docs/脚本通用约定.md) |
| 看板打不开或数据不显示 | [看板说明](web/README.md) |
| 数据库表、YAML 边界和迁移 | [数据库 v2 说明](automation/docs/数据库v2说明.md) |
| 准备发布给其他运营 | [发布前整改计划](automation/docs/发布前整改计划.md) |
