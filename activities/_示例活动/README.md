# 示例活动（**脱敏**）

> 这里是一份**能过契约校验的假活动**：所有人名 / 链接 / 关键词 / 分发名单都是占位符。
> 它的用处是让新人（和未来的你）**不用碰后台**就能看懂这套东西长什么样、怎么跑。

## 里面有什么

| 文件 | 是什么 |
|---|---|
| `配置/示例活动-hang.yaml` | **首批**的整活动 YAML：2 个桶（A 3 条资源 / B 2 条资源）、每个桶的客群定义与 AB 组 |

## 怎么用它

```powershell
# 1) 离线自检：这批该建几条资源 / 工单（不连后台、不登录）
.venv\Scripts\python.exe automation/scripts/check_batch_plan.py --config "activities/_示例活动/配置/示例活动-hang.yaml"

# 2) 跑测试验证数据库 v2、看板装配和判定
.venv\Scripts\python.exe -m pytest -q automation/tests
```

## 照它写你自己的活动

1. 复制 `配置/示例活动-hang.yaml` → 建你自己的活动目录 `activities/{活动名}/配置/{品牌}{负责人}.yaml`；
2. 把 `campaign`（品牌 / 负责人 / 任务组名 / 活动链接）、`audiences`（人群 / 关键词 / 分发名单 / 三条文案）换成你自己的；
3. 跑 `check_batch_plan.py` 看它算出来的资源与工单名对不对；
4. 有后台账号之后，按 `ad_output/流程文档/CSDN广告投放自动化流程.md` 走真实创建。

> ⚠ 示例活动在 `activities/_示例活动/`：**下划线开头的目录不进看板的活动下拉**，
> 所以它不会污染你日常看板；要用就按上面 `--config` 显式点名。
