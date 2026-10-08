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

## 快速上手（第一次跑，约 15 分钟）

### 第 0 步：装环境（一次就够）

```powershell
pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium            # 建批 / 取数要用浏览器
.venv\Scripts\python.exe -m pytest automation/tests -q             # 全绿 = 环境没问题（279 条，约 13 秒）
```

### 第 1 步：**不用账号**，先把看板点亮看长什么样

仓库里带了一份**脱敏示例活动**（`activities/_示例活动/`）和一个**假数据种子**：

```powershell
.venv\Scripts\python.exe automation/scripts/seed_demo.py
.venv\Scripts\python.exe web/app.py --db activities/_db/示例看板.db --port 8788
#    浏览器打开 http://127.0.0.1:8788
```

看到的完整界面：分桶统计（一行 = 该桶最新那个任务）、批次之间（最新 → 最老）、
点行弹出的**三条文案对比**——A 桶过门槛走「胜出特写」，B 桶没到门槛走「记分卡」，还有待复盘角标。
假数据只写 `activities/_db/示例看板.db`，**不会碰真实台账库**。

### 第 2 步：离线自检一份活动定义（不连后台）

```powershell
.venv\Scripts\python.exe automation/scripts/check_batch_plan.py --config "activities/_示例活动/调整/2026-01-08-二批.yaml"
#   ✓ 自检通过：权重 / 位次 / 名字↔槽位 / 工单字段 都没问题（1 桶）
```

### 第 3 步：连后台（**这一步必须有 CSDN 广告后台的账号**）

登录**只能手工做一次**——脚本不碰、也不该存你的密码：

```powershell
# 会起一个有头浏览器，你在里面手工登录；登完它自己检测到就退出
.venv\Scripts\python.exe automation/scripts/wait_login.py --minutes 10
# 数据平台（圈选导出用）是另一套登录态，要单独登：
.venv\Scripts\python.exe automation/scripts/wait_login.py --site databi --minutes 10
```

登录态存在 `.browser-profile/`（**不进 git、不上传**），之后建批 / 取数都复用它。

⚠ 三个坑先说在前：

- **一个登录 profile 同时只能被一个进程用**：看板服务开着时别再跑建批 / 取数，
  否则报"浏览器起不来"；要抢就先停服务（`web/README.md` 里有完整顺序）。
- **登录态会过期**，过期后任何取数都会失败，重跑一次 `wait_login.py` 就行。
- **没有账号怎么办**：第 1、2 步照样能跑（界面 + 自检 + 单测）；再往下的建批 / 取数 / 判定
  是**读你自己账号里的数据**，没有号跑不了——这不是配置问题，是权限问题。

### 真跑一个活动要准备的三样东西

1. **活动定义**：复制 `activities/_示例活动/配置/示例活动-hang.yaml` 改成你自己的；
   完整流程（摸产品 → 分人群 → 写文案 → 出物料 → 建批 → 复盘）见
   `ad_output/流程文档/CSDN广告投放自动化流程.md`。
2. **登录态**：上面第 3 步。
3. **判定门槛**：`activities/{活动名}/配置/判定门槛.yaml`（每个桶的曝光门槛 + 达标线；不配也能跑，看板降级显示）。

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
