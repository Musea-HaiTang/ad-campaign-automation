# AGENTS.md — automation（执行层）

> 把「整活动 YAML」变成 CSDN 后台对象：任务组 / 资源 / 客群 / 任务工单。

## 一句话

- 位置：物料确认 OK → 生成整活动 YAML → 本层脚本据此在后台自动建对象。
- 4 步：任务组(`run_taskgroup`，保底) → 资源(`run_ads`) → 客群(`run_audience`) → 任务工单(`run_taskorder`)。
- 依赖顺序：任务组(可能自动创建) → 资源 → 客群(圈选) → 任务名单(一键创建分发名单) → 任务工单；工单要等**用户名单**生成后才能选「分发名单→用户名单」。
- 安全：默认 dry-run（只填+校验+截图）；`--submit` 才真正创建；没让执行就不执行。**截图仅 dry-run（测试）产生；正式 `--submit` 不截图**。
- 数据：一份整活动 YAML（`../activities/{活动名}/配置/{品牌}{负责人}.yaml`）喂所有脚本；字段规范见 `campaigns/README.md`。
- 装载：**只用 `scripts/campaign.py` 的 `campaign.load(路径)`**（校验必填 + 未知字段 + 补默认值；默认值只在那里定义一次）。各 `run_*.py` 不许再 `cfg.get("字段", 默认值)` 自兜底——字段写错要启动就报错，别跑到浏览器第 3 步；生成器 `gen_yaml.py` 产出后也用同一个校验器自检。
- 断点：跑一项记一笔账（`../activities/{活动名}/日志/{实体}_progress.json`）。**已创建的永远跳过；只是彩排校验过的，正式跑会重跑并真正创建**；要重新全跑加 `--reset-progress`。
- 页面交互分两层：**底下的动作只用 `scripts/csdn_ui.py`**（起浏览器带登录态 / 下拉 / 穿梭框 / 弹窗清场 / 字段回读 / 截图 + 中文占位符常量）；**列表页的「翻开 → 筛选 → 查询 → 取行」只用 `scripts/list_page.py`**（页签作用域 / 冻列碎片合并 / 按名字取行 / 行内按钮结构定位+坐标兜底 / 勾选）。各 `run_*.py` 不许自己实现这两层，只写「这次要办什么」；后台改版只改共用层。
- 列表页只读：`list_page` **不提供**新建 / 提交 / 确定这类写入动作（写入留在各 `run_*.py` 的提交闸门里，体检「只读」因此是结构上的保证）；等不到行**不抛错**（返回「没等到」让调用方决定），只有侧边菜单 / 筛选框找不到才算结构性错误、当场抛。
- 等页面：**只用条件等待**（`csdn_ui.wait_for()` / `visible_input()` / `click_query()` / `table_has_rows()`）——**不许新增固定 `wait_for_timeout` 死等**（2026-09-22 把各脚本的固定死等统一换掉了：快就少等、慢就多等）。**读正文前先等"当前可见页签"的表出数据**（传 `scope=".el-tab-pane:visible"`）：后台把**所有页签都留在 DOM 里**、隐藏页签的表也有行，不限定作用域会被误满足，然后读到空表（2026-09-22 `--verify` 就因此把 5 个已建名单全报成未找到）。**列表页上这一整套由 `list_page` 负责**（`lp.query()` 点查询+等落地、`lp.wait_rows()` 等表出数据、`lp.row_by_name()` 取行），各脚本不再自己写。
- 提交闸门：**任何一步没通过就不提交**（关弹窗、记 warn 下次重跑），**提交后必须回读核对**——工单/客群/资源/任务组/分发名单五个创建脚本都已上（2026-09-22）；只看"弹窗关了 + `.el-message` 有提示"一律不算成功。
- 排队与止损：**只用 `scripts/bucket_runner.py`**（工头：逐项跑 / 断点账本 / 失败清场 / 首项与连续 3 项失败即止 / `RESULT` 三态）。各 `run_*.py` 不许自己写循环与止损；改规矩只改工头。
- 命令外壳：**开关（`--config/--submit/--headed/--reset-progress/--only`）/ 装载（读 YAML → 活动目录 → 截图目录）/ 账本文件名 / `ui.session` 包装 / `RESULT` 行与退出码，七条命令只有一处**，在 `scripts/cli.py`（`parser()` / `context()` / `Ctx.session()` / `fatal()` / `finish()`）。各 `run_*.py` 只加自己的开关、只写「这次要办什么」；`--only` 的未知桶报错文案也只有 `cli.only_buckets()` 一处。2026-09-23 前是七个脚本各写一遍（那段校验 4 处逐字相同），**新建命令照这个外壳搭，别再抄一遍**。
- 命名：**只用 `scripts/naming.py`**（桶名 `{前缀}-{id}类` / 客群名与工单名 `桶名 · {topic}` / 资源名 `桶名 · {角色}`；前缀取 `campaign.namePrefix`）。各 `run_*.py` 与生成器都不许自己拼名字——后台按精确字符串匹配，拼错就选不中。
- 门控：执行前先确认必给项（负责人→taskGroupName / 子业务线 / 是否新建任务组+名 / **投放日期+时间段**），规矩见流程文档「执行层前置门控」。
- 圈选越界：桶预估总数超 `[25000,200000]` → **正式跑/彩排当场自动调阈值**（**只升点击、曝光锁死 1**，最多试 5 次，规则在 `scripts/audience_policy.py`），搜到落点就继续创建并写回 `thresholds.yaml`；搜不到才标 `needs_keywords` 跳过该桶，与用户同步。**偏低于下限不降曝光**（曝光=0 是虚池：池大 2.2~24 倍而日均曝光低 2.8~11 倍）→ 那是词不够，改词。**不用人再跑一趟 `--tune`**（用户 2026-09-10 定；`--tune` 仍保留为「只调不建」）。下限 10000→25000 是 2026-09-21 定的（≈ 保底 1 万日均曝光）。
- **圈选时点：一律安排在下午**（用户 2026-09-21 问后台技术人员确认）：那边数据集**每天上午还在写入、一般中午才写完**，早上圈出来的数偏小（同款词实测 10:2x = 7,816 → 11:0x = 67,207）。早上跑圈选 = 白跑。
- 客群达标：口径 = 「**日均曝光(预估)**」**目标 2 万 / 底线 1 万**（用户 2026-09-21 定）。这个数只在「圈选用户 → 博文圈选任务」列表（`实际圈选博客ID数 / 日均点击(预估) / 日均曝光(预估) / 日均pv(预估)`），且**建完、等后台算完才刷出来**（创建弹窗里没有）——所以判断在**创建之后**，用 `check_campaign.py --only audience` 读（见 `docs/check_campaign.md`）。
- 建完体检/删除：`run_audience.py --submit --verify`（浏览器不关，每 10 秒点一次「查询」，读到数就判达标）；试圈用 `--name-suffix=-试圈`（不动正式客群名，跑完 `--delete` 删）；不满意用 `run_audience.py --delete "任务名"` 删（**停止 → 勾选 → 批量删除**，只动圈选任务）。读数/判定/轮询/删除唯一实现在 `scripts/audience_metrics.py`，各脚本不许自己实现。
- 环境：**本层固定用仓库根下的 `.venv\Scripts\python.exe`**（Python 3.12.4 + PyYAML + playwright；依赖清单见仓库根 `requirements.txt`）。**一律用 venv 解释器、不依赖 PATH**——本机默认 `python` 是 3.14.6（空环境，只装了 pip），勿用。venv 缺失时重建：`D:\Python\Python3.12.4\python.exe -m venv .venv` → `.venv\Scripts\python.exe -m pip install -r requirements.txt`。浏览器 `D:\playwright-browsers`、profile `D:\Codex_WorkingSpace\ad_management\.browser-profile`（cookie 过期重登）；启动浏览器需提权。

## 必读

- `README.md`：执行层总览
- `scripts/csdn_ui.py`：**共用层**（改后台页面交互只改这里）；单测 `tests/test_csdn_ui.py`（假柜台，不开真浏览器）
- `scripts/list_page.py`：**共用层（列表页）**（改「翻开/筛选/查询/取行」只改这里）；单测 `tests/test_list_page.py`（假列表页，不开真浏览器）
- `scripts/cli.py`：**共用层（命令外壳）**（改开关/装载/账本路径/会话/收尾只改这里）；单测 `tests/test_cli.py`（不开浏览器）
- `scripts/bucket_runner.py`：**共用层（工头）**（改排队/断点/止损/退出码只改这里）；单测 `tests/test_bucket_runner.py`
- `scripts/naming.py`：**共用层（命名）**（改命名规则只改这里，生成器也 import 它）；单测 `tests/test_naming.py`
- `scripts/audience_policy.py`：**圈选阈值策略**（纯函数：越界怎么搜落点；单测 `tests/test_audience_policy.py`）
- `scripts/campaign.py`：**整活动 YAML 装载**（校验/默认值/thresholds 读写；契约见 `campaigns/README.md`；单测 `tests/test_campaign.py`）
- `docs/*.md`：各脚本说明
- `campaigns/README.md`：整活动 YAML 字段规范（AI 生成依据、脚本消费契约）
