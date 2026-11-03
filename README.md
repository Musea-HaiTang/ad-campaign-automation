# CSDN 广告投放自动化

> **管什么**：项目定位、核心能力、最短 AI 部署入口和文档导航。
> **不管什么**：具体投放流程、部署细节、登录验收和故障排查，分别指向对应文档。
> **谁什么时候读**：第一次了解项目、准备部署或查找权威文档时。

这个项目把 CSDN 广告投放从人工串联做成一条可追踪的流程：

```text
活动链接
  → 产品与人群拆分
  → 文案与投放物料
  → 用户确认
  → 整活动 YAML
  → 后台建任务组、资源、客群和任务工单
  → 数据写入 SQLite
  → 看板查看与自动复盘
```

## 当前状态

当前版本已完成 P0 发布阻断项和 P1 长期维护整改，并提供 AI 原生一键部署入口。
部署、登录和运行边界的权威说明分别在：

- [部署说明](automation/docs/部署说明.md)
- [登录与验收](automation/docs/登录与验收.md)
- [故障排查](automation/docs/故障排查.md)

项目已发布到私有仓库：
[Musea-HaiTang/ad-campaign-automation](https://github.com/Musea-HaiTang/ad-campaign-automation)。

## 环境要求

- Windows 10/11
- Python 3.12-3.14，可由当前 AI 宿主直接调用
- Microsoft Edge 或 Google Chrome
- 可访问 CSDN 后台和相关数据平台的网络环境

## AI 部署

部署必须使用独立工作空间，项目根目录就是这个工作空间，不能嵌套在旧项目或旧操作者目录中。

AI 应从当前对话询问真实 `owner`，不能使用文档示例值或系统用户名代填。然后由 AI 在项目根目录执行：

```powershell
python scripts/setup_ai.py --owner "真实owner" --run-tests --start-board
```

该入口会：

1. 创建或复用 `.venv`
2. 安装并检查依赖
3. 检测浏览器
4. 创建目录和本机配置
5. 初始化数据库和示例活动
6. 运行自动化测试
7. 启动常驻看板并检查健康接口
8. 写入部署和测试结果

成功后必须检查：

```text
.local/setup-result.json
.local/test-results.json
```

两份结果的 `status` 都必须是 `"ok"`。随后 AI 应打开看板和 CSDN 登录页面，告知用户本人完成登录，再运行：

```powershell
.venv\Scripts\python.exe scripts\doctor.py
```

详细步骤见[部署说明](automation/docs/部署说明.md)和[登录与验收](automation/docs/登录与验收.md)。

## 核心能力

- 活动、人群桶、资源和文案配置
- 投放物料 HTML 与整活动 YAML 生成
- CSDN 后台任务创建及只读核对
- SQLite 运行数据、指标和复盘记录
- 本地看板、自动巡检和待复盘队列
- 数据库备份、恢复、缓存清理和环境诊断

## 业务流程

权威流程见：

- [CSDN 广告投放自动化流程](ad_output/流程文档/CSDN广告投放自动化流程.md)
- [CSDN 广告投放全流程图](ad_output/流程文档/CSDN广告投放全流程图.html)
- [自动化执行层全流程](automation/docs/执行层全流程.md)

## 目录说明

| 目录 | 作用 |
|---|---|
| `activities/` | 活动配置、物料和整活动 YAML；运行历史进入数据库 |
| `ad_output/` | 业务流程、文案规则、物料模板和 YAML 生成工具 |
| `automation/` | 执行脚本、数据库、取数、判定、巡检和自动复盘 |
| `web/` | 本地看板服务与前端页面 |
| `scripts/` | AI 部署、环境诊断和内部发布工具 |
| `automation/tests/` | 不打开真实浏览器的自动化测试 |

## 开发与维护

AI 或自动化环境统一使用：

```powershell
python scripts/verify_tests.py
```

脚本会自动选择全量或按文件模式，并写入 `.local/test-results.json`。

发布 GitHub 前使用内部发布脚本：

```powershell
.\scripts\push_github.ps1 -DryRun -Mirror "<上传线目录>"
```

它只复制白名单中的代码、测试、文档和脱敏示例，不发布客户活动、数据库、浏览器 profile 或本机配置。

## 文档导航

- [运营使用说明](运营使用说明.md)
- [登录与验收](automation/docs/登录与验收.md)
- [部署故障排查](automation/docs/故障排查.md)
- [执行层文档导航](automation/docs/README.md)
- [看板说明](web/README.md)
