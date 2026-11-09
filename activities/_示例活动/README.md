# 示例活动

> **管什么**：区分“可提交的脱敏契约样例”和“只能 dry-run 的真实彩排数据”。
> **不管什么**：活动投放流程 → `ad_output/流程文档/CSDN广告投放自动化流程.md`。
> **谁什么时候读**：部署后验收、更换运营账号、需要演示资源/工单表单时。

## 两份数据

| 文件 | 用途 | 能否提交 |
|---|---|---|
| `配置/示例活动-hang.yaml` | 脱敏契约样例；用于离线测试、物料和 YAML 校验 | 不能直接连真实后台 |
| `配置/rehearsal-腾讯云产品-hang.yaml` | 当前账号的真实彩排数据；引用已有任务组、业务线和分发名单 | 不能提交；`campaign.rehearsal: true` 会阻止 `--submit` |

## 彩排命令

在仓库根目录执行：

```powershell
.venv\Scripts\python.exe automation/scripts/check_batch_plan.py --config activities/_示例活动/配置/rehearsal-腾讯云产品-hang.yaml
.venv\Scripts\python.exe automation/scripts/run_ads.py --config activities/_示例活动/配置/rehearsal-腾讯云产品-hang.yaml --headed
.venv\Scripts\python.exe automation/scripts/run_taskorder.py --config activities/_示例活动/配置/rehearsal-腾讯云产品-hang.yaml --headed
```

两条 `run_*.py` 都不要加 `--submit`。彩排会填写、回读、截图，然后取消。

## 换账号时

彩排文件里的任务组、业务线、子业务线和分发名单属于当前 CSDN 账号。如果部署到另一账号，保留文件结构，只替换这些真实对象名称，并先重新跑 `check_batch_plan.py`。
