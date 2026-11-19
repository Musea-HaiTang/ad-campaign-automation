# 示例活动

> **管什么**：区分“可提交的脱敏契约样例”和“只能 dry-run 的真实彩排数据”。
> **不管什么**：活动投放流程 → `ad_output/流程文档/CSDN广告投放自动化流程.md`。
> **谁什么时候读**：部署后验收、更换运营账号、需要演示资源/工单表单时。

## 两份数据

| 文件 | 用途 | 能否提交 |
|---|---|---|
| `配置/示例活动-hang.yaml` | 脱敏契约样例；用于离线测试、物料和 YAML 校验 | 不能直接连真实后台 |
| `配置/rehearsal-腾讯云产品-hang.yaml` | 已脱敏的彩排数据；链接固定为示例域名，其余字段用于验证表单 | 不能加 `--submit`；`campaign.rehearsal: true` 会阻止提交 |

## 彩排命令

在仓库根目录执行：

```powershell
.venv\Scripts\python.exe -m automation.scripts check-batch-plan --config activities/_示例活动/配置/rehearsal-腾讯云产品-hang.yaml
.venv\Scripts\python.exe -m automation.scripts run-ads --config activities/_示例活动/配置/rehearsal-腾讯云产品-hang.yaml --headed
.venv\Scripts\python.exe -m automation.scripts run-taskorder --config activities/_示例活动/配置/rehearsal-腾讯云产品-hang.yaml --headed
```

两条 `run-*` 命令都不要加 `--submit`。彩排会填写、回读、截图，然后取消。

## 换账号时

彩排文件里的任务组、业务线、子业务线和分发名单属于当前 CSDN 账号。如果部署到另一账号，保留文件结构，只替换这些真实对象名称，并先重新跑 `check-batch-plan`。
