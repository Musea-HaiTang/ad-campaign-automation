# 建任务组 · `run_taskgroup.py`（执行层第 1 步 · 保底）

> **管什么**：什么时候才要建任务组、怎么跑、它跟另外几步的关系。
> **不管什么**：其余各步 → 各自说明书；字段契约 → [`../campaigns/README.md`](../campaigns/README.md)；排队 / 断点 / 止损 / 回读口径 → [`../README.md`](../README.md)「设计原则」。
> **谁什么时候读**：执行层开工前，问「要不要新建任务组」的时候。

## 这是"保底"步骤，普通情况跳过

后台创建任务组弹窗里写着：**「企业服务无需创建任务组，在CRM立项且分配团队后，会自动生成」**。立项后任务组一般已存在，`run_ads.py` 建资源时在「请选择任务组」里直接能选到。**只有立项没自动建出任务组、导致资源 / 圈选选不到任务组时，才用它兜底。**

编排规则：**开始执行层前先问「是否需要新建任务组？如果需要，叫什么」**，不需要就跳过这一步。
（另外三项门控——负责人标识 / 子业务线 / 投放日期 + 时间段——见 [`../AGENTS.md`](../AGENTS.md)。）

## 怎么跑

```powershell
# dry-run：填 + 校验 + 截图，点「取消」，不创建（默认）
.venv\Scripts\python.exe -u automation/scripts/run_taskgroup.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml

... --submit             # 真正创建（本步骤只跑一次，直接提交即可）
--headed                 # 想看浏览器窗口
--reset-progress         # 断点账本不想要了，从头全跑
```

- **提交前闸门、中断对账和提交后回读**：统一按 [`脚本通用约定.md`](脚本通用约定.md) 执行。

## 数据来源（整活动 YAML）

| 字段 | 用途 |
| --- | --- |
| `campaign.taskGroupName` | 任务组名称 `{品牌}{负责人}` |
| `controls.defaults.businessLine` | 业务线（事业部） |
| `audiences[0].subBusinessLine` | 子业务线/用户组（任务组只填一个，取第 1 桶） |
| 签呈号 | 选填，默认不填 |

## 后台操作链

| # | 动作 | 选择器 |
| --- | --- | --- |
| 0 | 侧边栏 `1.创建任务组` | `get_by_text("1.创建任务组", exact=True)` → 任务组列表页 |
| 1 | 点列表页按钮 `创建任务组` | `page.locator("button").filter(has_text="创建任务组")` → 打开「添加」弹窗 |
| 2 | 任务组名称 | `input[placeholder='请输入任务组名称']` |
| 3 | 业务线（事业部） | `input[placeholder='请选择事业部']` |
| 4 | 子业务线/用户组 | `input[placeholder='请选择子业务线/用户组']` |
| 5 | 签呈号 | `input[placeholder='请输入签呈号']`（选填，默认不填） |
| 6 | 提交 | 弹窗内 `button.el-button--primary:has-text("提交")`（dry-run 不点） |

## 已知坑

- `1.创建任务组` 是侧边菜单、`创建任务组` 是列表页按钮——同名元素多，要按按钮定位。
- 业务线 / 子业务线都是 el-select，**须显式重选**（页面显示 ≠ 模型绑定）；点 `.el-select-dropdown:visible` 里的选项 + 等下拉收起才算选中。
- 截图 `taskgroup_filled.png` **仅 dry-run 产生**，且要等下拉收起后再截（免得弹窗带下拉残影）。
- `goto` 用 `domcontentloaded`（`networkidle` 会被 SPA 长连接卡住）；运行加 `python -u` 看实时输出。
