# 广告投放全链路自动化（工具集）

> 把「活动链接 + 要求」变成 CSDN 广告后台里真实跑起来的**任务组 / 资源 / 客群 / 工单**，
> 再配一块**复盘看板**（桶维度、三条文案对比、判定建议、待复盘角标）。
>
> ⚠ 本仓库只放**工具、代码、文档与模板**。真实活动的**配置、文案、物料与投放数据不在仓库里**——
> 那是业务数据，不进版本控制（见下面的「仓库里没有什么」）。

## 目录

| 目录 | 是什么 |
|---|---|
| `automation/scripts/` | 执行层脚本：建批、取数、看板装配、判定 |
| `automation/docs/` | 每个脚本的用法（改脚本先看这里） |
| `automation/tests/` | pytest（假柜台：手写台账库，不连后台、不开浏览器） |
| `web/` | 本地看板：一个只读的本地服务 + 静态页（`start.bat` 一键起） |
| `ad_output/流程文档/` | **唯一权威 SOP**：从摸产品到出物料的每一步 |
| `ad_output/工具/` | 物料 HTML / 整活动 YAML 生成器 |
| `ad_output/文案风格/` | 文案方法论与写法（分人群、自审表） |
| `activities/_活动细则模板.md` | 活动定义模板：新活动照它填 |
| `activities/*/README.md` | 各活动目录的说明骨架（数据说明） |

## 5 分钟能跑到什么程度

不需要后台账号，先跑这些：

```powershell
pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium   # 取数/建批要用浏览器
.venv\Scripts\python.exe -m pytest automation/tests -q    # 全绿就说明环境没问题
.venv\Scripts\python.exe automation/scripts/check_batch_plan.py --config <批次.yaml>   # 离线自检：这批该建几条
web\start.bat                                             # 看板（库是空的 → 页面空表，但界面能看）
```

**要到"能真跑一个活动"，还需要三样东西**（仓库里没有，得自己准备）：

1. **一个活动定义**：照 `activities/_活动细则模板.md` 写 → 生成
   `activities/{活动名}/配置/{品牌}{负责人}.yaml`（整活动 YAML 是唯一入口，所有脚本都吃它）。
2. **登录态**：`python automation/scripts/wait_login.py` 手工登录一次 CSDN 广告后台
   （登录 profile 存在 `.browser-profile/`，**不进 git**）。
3. **判定门槛**：`activities/{活动名}/配置/判定门槛.yaml`（每个桶的曝光门槛 + 达标线，
   不配也能跑，看板会降级显示）。

## 一个活动的完整链路

```
活动链接 + 要求
   ↓  摸产品 / 分人群 / 写文案（见 ad_output/流程文档/CSDN广告投放自动化流程.md）
整活动 YAML（activities/{活动}/配置/*.yaml）
   ↓  run_ads.py --config <整活动 YAML>           建资源
   ↓  run_taskorder.py --config <整活动 YAML>     建工单
   ↓  fetch_perf.py --config <整活动 YAML>        取数 → 写台账库 activities/_db/投放数据.db
   ↓  web/start.bat                               看板：分桶统计 / 批次之间 / 三条文案对比
   ↓  judge_batch.py --config <活动基础 YAML>     判定清单：留谁 / 下谁 / 下一批补几条
下一批：调整/{日期}-{第几批}.yaml
```

## 几个必须知道的口径（2026-10 定）

- **一批 = 一份整活动 YAML**，`配置/*.yaml` 是首批、`调整/*.yaml` 是后续批。
- **桶独立**：一个桶（`audiences[].id`）跨批次是同一个桶，**每个桶有自己的"当前批"**
  （= 该桶最后一次建批）。曝光大的桶会跑到很后面的批次、曝光小的桶还停在前几批，这是正常的。
- **判定**：桶内累计曝光 ≥ 门槛才判点击；达标线 = 实际点击率 ≥ 千三。
  有点击的留下（受幸存上限约束）、零点击的下线，空位补新文案。
- 口径只写一遍：判定规则在 `automation/scripts/judging.py`，桶/批次口径在
  `automation/scripts/campaign.py`（`bucket_current`），看板与命令行**共用同一份**。

## 仓库里没有什么（故意的）

`activities/*/配置|调整|物料|数据/`、`ad_output/memory/`、`_experiments/`、`activities/_db/`、
`.browser-profile/` —— 这些是**具体活动的配置、客户文案、物料、投放数据与登录态**，
已在 `.gitignore` 里排除，本地有、仓库没有。要跑真实活动，请自备。
