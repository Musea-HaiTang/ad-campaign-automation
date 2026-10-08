# CSDN 新建任务组 · 数据驱动自动化（保底步骤）

> 执行层第 1 步。与 `run_ads.py`（建资源）/ `run_audience.py`（圈选用户）平级，各自独立执行。

## 定位：这是"保底"逻辑，普通情况跳过

后台创建任务组弹窗里有提示：**「企业服务无需创建任务组，在CRM立项且分配团队后，会自动生成」**。
也就是说：立项后任务组一般已存在，`run_ads.py` 建资源时直接在"请选择任务组"里能选到，**本步骤平常不用执行**；
只有当立项没自动建出任务组、导致资源/圈选选不到任务组时，才需要兜底执行。

> 编排规则：**开始执行层前，先问「是否需要新建任务组？如果需要，任务组叫什么」**；不需要就跳过。

## 数据来源（整活动 YAML）

| 字段 | 用途 |
| --- | --- |
| `campaign.taskGroupName` | 任务组名称，格式 `{品牌}{负责人}`，如 `{品牌}{负责人}` |
| `controls.defaults.businessLine` | 业务线（事业部），默认 `企业服务事业部` |
| `audiences[0].subBusinessLine` | 子业务线/用户组（任务组只填一个，取第 1 桶） |
| 签呈号 | 选填，默认不填 |

## 操作链（2026-09-09 真机勘察，去重后）

| # | 动作 | 选择器 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 0 | 侧边栏菜单 `1.创建任务组` | `get_by_text("1.创建任务组", exact=True)` | 入口 | 路由到任务组列表页 |
| 1 | 点按钮 `创建任务组` | `page.locator("button").filter(has_text="创建任务组")` | 入口 | 打开「添加」弹窗 |
| 2 | 填**任务组名称** | `input[placeholder='请输入任务组名称']` | ✓ | `campaign.taskGroupName` |
| 3 | 选**业务线(事业部)** | `input[placeholder='请选择事业部']` | ✓ | 显式重选绑值，`defaults.businessLine` |
| 4 | 选**子业务线/用户组** | `input[placeholder='请选择子业务线/用户组']` | ✓ | `audiences[0].subBusinessLine` |
| 5 | 签呈号 | `input[placeholder='请输入签呈号']` | 选填 | 默认不填 |
| 6 | 点**提交** | 弹窗内 `button.el-button--primary:has-text("提交")` | 提交 | dry-run 不点；`--submit` 才点 |

## 怎么跑

```powershell
# dry-run：填+校验+截图，点「取消」，不创建（默认）
.venv\Scripts\python.exe -u automation/scripts/run_taskgroup.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml

# 真正创建：加 --submit
.venv\Scripts\python.exe -u automation/scripts/run_taskgroup.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml --submit

# 想看浏览器窗口：加 --headed

# 断点账本不想要了，从头全跑：加 --reset-progress
```

前置：同其他执行器——python 3.12 装 `playwright`、`pyyaml`；浏览器 `D:\playwright-browsers`；
登录 profile `D:\Codex_WorkingSpace\ad_management\.browser-profile`（cookie 过期需重登）。启动浏览器需提权。

**断点与结果**（与另外三个执行器同一套规矩，见 `../README.md`「设计原则」）：跑完记一笔到
`../activities/{活动名}/日志/taskgroup_progress.json`——**已提交的跳过**，只是彩排校验过的在正式跑时会重跑；
**彩排里名称/业务线/子业务线校验没全过的记 `warn`**（下次会重跑），全过才记 `done`；
失败会关掉残留弹窗并中止；结尾 `RESULT: OK / HAS_WARN / HAS_FAILURES`（只有 `OK` 返回 0）。

**提交前闸门 + 提交后回读（2026-09-22 加）**：`--submit` 先看三个校验值——名称 / 业务线 / 子业务线
任一没过就**关弹窗、不提交**（记 `warn`，下次重跑）；提交后回**任务组列表**（`#/distribute/taskteam/team`，
输入框 `请输入任务组名称`）按名字查一次，**查得到才记 `submitted`**，查不到记 `warn`。

- 起因：任务组名是后面三步的锚点（资源 / 客群 / 工单都按名字**精确字符串**匹配），名字错了整条链都选不中；
  老实现只看「弹窗关掉 + `.el-message` 提示」，那是 2026-09-14 那批"假成功"的老毛病。
- 代价：提交后多一次列表往返（约 2~3 秒；本步骤只跑一次，可忽略）。
- ⚠ 回读是**子串匹配**（`check_campaign.py` 同款限制），要更严就用 `check_campaign.py --only taskgroup`。
- **实测（2026-09-22 彩排，dry-run 单次）**：3.3 秒 → 3.8 秒（差异在噪声内；本脚本 dry-run 路径本来就没有
  会白等的固定死等，闸门/回读只在 `--submit` 路径上跑）。

## 执行前门控（AI 负责，不写在脚本里）

必给 3 项，**执行前由 AI 检测**，未给齐则**不启动执行层**（不放在脚本里硬拦）：
1. 负责人标识 `owner` → `campaign.taskGroupName`
2. 子业务线 → `audiences[].subBusinessLine`
3. 是否新建任务组 + 名字（运行期决定，开工前询问）

> 规矩：凡物料/细则/活动链接推不出来的必填字段，执行前先跟用户确认，确认后才进执行层。

## 已知坑

- 菜单与按钮均需精确定位：`1.创建任务组` 是侧边栏菜单，`创建任务组` 是列表页按钮（同名元素多，按按钮定位）。
- 业务线/子业务线都是 el-select，**须显式重选**（页面显示 ≠ 模型绑定），用 `.el-select-dropdown:visible` 内选项点选 + 等下拉收起作为可靠信号。
- 截图时机在下拉收起后（脚本内 `_wait_dropdown_closed`），避免弹窗带下拉残影。
- 截图（`taskgroup_filled.png`）**仅 dry-run 产生，正式 `--submit` 不截图**。
- `goto` 用 `domcontentloaded`；`networkidle` 会因 SPA 长连接卡住。运行加 `python -u` 看实时输出。
