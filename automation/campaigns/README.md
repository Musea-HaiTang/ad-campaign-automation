# 整活动 YAML · 字段规范

> 管什么：`activities/{活动名}/配置/{品牌}{负责人}.yaml` 的字段契约、默认值和生成前确认项。
>
> 不管什么：产品与文案的生成方法见流程文档，执行步骤见 `automation/docs/`。
>
> 谁在什么时候读：物料确认后、生成或修改批次 YAML 前读。

整活动 YAML 是自动化脚本消费的唯一执行载荷。物料确认后，由 `ad_output/工具/gen_yaml.py`
从活动定义装配；脚本据此创建任务组、资源、客群和任务工单。YAML 只放需要写入后台的数据，
不放统计或给人看的摘要。

## 顶层结构

| 段 | 必填 | 说明 |
|---|---|---|
| `version` | ✓ | schema 版本，当前为 `1` |
| `adType` | ✓ | 广告位类型，如 `blog-page-t0` |
| `label` | ✓ | 活动中文名，如 `{品牌}{负责人}-7类` |
| `controls` | ✓ | 当前广告位的固定控件配置 |
| `campaign` | ✓ | 本次投放计划信息 |
| `audiences` | ✓ | 人群桶数组，1 桶 = 1 客群 = 1 工单 |
| `taskOrder` | 建工单时 ✓ | 仅 `run_taskorder.py` 读取的建单配置 |

## `controls`

同一广告位基本不变。内容内嵌在 YAML 中，脚本无需额外读取 types 文件。

| 字段 | 说明 |
|---|---|
| `channelType` | 类型标签，如 `页面类` |
| `channel` | 渠道位，如 `PC博客详情页-新模版-T0` |
| `materialPath` | 素材类型路径，当前渠道为 `[动态广告, 其它]` |
| `username` | 动态广告用户名。生成器默认读取 `.local/operator.json` 的 `ad_username`，可用 `gen_yaml.py --username <名字>` 覆盖 |
| `defaults` | 表单默认值：`businessLine` / `isPopup` / `adClient` / `closeBtnColor` |
| `fields` | 文本控件定位：`title` / `summary` / `link` / `username`（placeholder + type） |

## `campaign`

| 字段 | 说明 |
|---|---|
| `brand` | 品牌 |
| `phase` | 预留期次，当前不参与命名 |
| `owner` | 负责人标识 |
| `taskGroupName` | 建或选任务组时使用，格式 `{品牌}{负责人}` |
| `namePrefix` | 子实体统一命名前缀，如 `{品牌}{负责人}` |
| `activityLink` | 活动链接，资源默认继承，可按资源覆盖 |
| `status` | 仅首次导入时使用：`active`（默认）或 `ended` |
| `endedAt` | 首次导入 `status: ended` 时填写；之后用 `activity_state.py` 更新数据库 |

新建任务组时 `taskGroupName = namePrefix`。沿用已有任务组时，两者可以不同；子实体统一用
`namePrefix`。桶名、客群名、工单名、资源名和物料文件名只允许由 `automation/scripts/naming.py`
生成；生成器和执行脚本均 import 该模块，不要在其他地方拼名字。

## `audiences`

每个数组元素代表一个人群桶。有 `namePrefix` 时，`taskName` 由生成器派生。

| 字段 | 说明 |
|---|---|
| `id` | 单页活动用 `A`~`Z`；多产品活动直接写产品名 |
| `topic` | 桶主题 |
| `target` | 目标读者描述 |
| `taskName` | 单个字母桶为 `{namePrefix}-{id}类`；产品类桶为 `{namePrefix}-{id}`，不加「类」 |
| `subBusinessLine` | 建资源时选择的子业务线 |
| `keywordGroup.keywords` | 客群圈选关键词，英文逗号分隔 |
| `resources` | 本桶本轮新建的 1～3 个资源，默认 3；空列表表示复用已有资源 |
| `abGroups` | 本桶资源分组；1 条为单资源对照组，2/3 条为 AB 组；不写时回落到 `taskOrder.abGroups` |
| `distributionList` | 本桶用户名单；依次回落到 `taskOrder.distributionList`、本桶客群名 |
| `abTest` | 可选的桶级 AB 模式；覆盖 `taskOrder.abTest`，用于混合 1/2/3 资源桶 |
| `clickThreshold` | 圈选「点击需≥」，默认 `0` |
| `exposureThreshold` | 圈选「曝光需≥」，默认 `1` |
| `reviewThresholdExposure` | 自动复盘门槛；缺省时沿用数据库值，首次登记默认 `3000` |
| `nameSuffix` | 重投后缀，只追加到客群名、工单名和资源名，不加入桶名 |

产品和客群按精确名称匹配。产品类桶的客群名、工单名不拼 ` · {topic}`。

### `resources[]`

| 字段 | 说明 |
|---|---|
| `role` | `control` / `experiment1` / `experiment2` |
| `name` | 由 `naming.resource_name()` 生成 |
| `title` | 广告标题，1 行，无 CTA |
| `summary` | 广告描述，1 行 |
| `link` | 可选；覆盖 `campaign.activityLink` |
| `angleKey` | 可选；已冻结角度 ID，用于复盘按角度归因 |
| `presentationType` | 可选；`disguised_post`（伪装博文）或 `direct_marketing`（纯营销） |
| `styleKey` | 可选；`regular` / `antithesis` / `adaptation` / `poetry_reference` |
| `validationSlot` | 可选；`first_test` / `retest` / `backup` / `anchor` |

四个文案分类字段对旧 YAML 保持可选，避免中断历史续跑；新生成的文案必须填写，
同步到数据库后分别落到 `creative.angle_key`、`presentation_type`、`style_key`、`validation_slot`。
缺失时保持空值，不从标题或摘要倒猜。

AB 资源和用户名单必须逐桶对应：工单应挂本桶资源、用本桶名单。`taskOrder` 中的 `abGroups`
和 `distributionList` 只是兜底；正式投放前确认每个桶都写了自己的 `abGroups`。

## 装载校验与默认值

唯一装载入口是 `automation/scripts/campaign.py` 的 `campaign.load(路径)`。生成器写完会立即
调用它自检；未知字段会报错并提示相近字段名。

必要字段：

- `campaign.taskGroupName`、`campaign.activityLink`
- `controls.channel`、`controls.materialPath`、`controls.defaults.businessLine`
- `controls.fields.{title,summary,link}.placeholder`
- 动态广告还需 `controls.username`、`controls.fields.username.placeholder`
- `audiences[].id`、`subBusinessLine`、`keywordGroup.keywords`、`resources`
- `audiences[].resources[].role`、`name`、`title`、`summary`
- `taskOrder.businessLine`、`taskGroup`、`channel`、`deliveryDate.start`、`deliveryDate.end`
- 有桶未写自己的 `abGroups` 时，`taskOrder.abGroups` 至少一组

`resources` 必须是列表；空列表表示本桶本轮不新建资源。

默认值只在 `campaign.py` 的 `DEFAULTS` 维护：

- `taskOrder.price = 20`
- `taskOrder.deliveryDate.mode = set_time`、`timeStart = 8`、`timeEnd = 23`
- `exposureCaps = {daily: 100000, weekly: 500000, total: 500000}`

投放日期没有默认值，`deliveryDate.start/end` 必须显式填写。子业务线唯一来源是
`audiences[].subBusinessLine`；`taskOrder.subBusinessLine` 不存在。

## 生成前确认

物料确认后、生成 YAML 前，先列待确认清单。以下字段无法可靠推导时必须问用户：

| 字段 | 确认内容 |
|---|---|
| `taskOrder.price` | 当期计费价格；不得套用历史 `20` / `30` |
| `owner` / `taskGroupName` | 负责人、任务组名，以及是否新建任务组 |
| `audiences[].subBusinessLine` | 各桶子业务线，可能不同 |
| `deliveryDate` | 起止日期和时间段 |
| `channel` / `activityLink` | 无法从活动细则或用户链接推导时确认 |

`deliveryDate.start` 填写建批当天，也就是复盘当天。工单创建后起始日无法修改；
不能写成次日，否则会少一天曝光。若用户一开始已提供上述值，则跳过对应确认项。
`taskOrder.channelSizeId` 不单独确认，它由后台选择渠道后自动带上。

## `taskOrder`

`run_taskorder.py` 读取本段，资源、客群脚本不读取。

| 字段 | 说明 |
|---|---|
| `businessLine` | 事业部，如 `企业服务事业部` |
| `taskGroup` | 后台已有任务组名 |
| `taskName` | 通常不填；脚本按桶派生：字母桶为 `{bucket.taskName} · {topic}`，产品桶为 `{bucket.taskName}` |
| `channel` | 渠道，如 `PC博客详情页-新模版-T0` |
| `channelSizeId` | 渠道尺寸/ID，用于核对；选择渠道时后台自动带上 |
| `abGroups` | 全局兜底，结构为 `[{label, resource, weightPct}]`；单资源模式不填权重 |
| `abTest` | 全局兜底；`true` = AB，`false` = 单资源。桶级 `audiences[].abTest` 优先 |
| `price` | 当期计费价格，必须由用户提供 |
| `deliveryDate` | `{mode: set_time, start, end}` |
| `distributionList` | 全局兜底名单；最终可回落到客群名 |
| `exposureCaps` | 每日/每周/总曝光上限 |

`gen_yaml.py` 会按每个桶的 `copies` 数量解析 AB 模式：1 条为 `false`，2/3 条为 `true`，
并把结果写入该桶的 `audiences[].abTest`。`taskOrder.abTest` 只作为旧 YAML 的全局兜底。
解析优先级为：桶级 `audiences[].abTest` → `taskOrder.abTest` → 按 `resources` / `abGroups` 数量推导。

执行依赖顺序：任务组 → 资源 → 客群 → 分发名单 → 任务工单。`distributionList` 填真实名单名，
不要带后台显示的「… 用户名」后缀。

### AB 组规则

- 权重按资源条数计算：3 条为 `34/33/33`，2 条为 `50/50`，总和必须为 100；1 条是单资源模式，不填权重。
- 槽位必须从前往后填满：2 条资源只能使用「对照组 + 实验组1」。
- 资源名的角色段必须与 AB 槽位一致。
- 生成后运行 `automation/scripts/check_batch_plan.py --config <批次 YAML>`，再跑 `run_ads` 或 `run_taskorder`。

`abTest: false` 时，工单选择「AB 测试 = 否」，只挂 `abGroups` 的第一条资源，没有流量占比。
新建单资源工单时，`resources` 写 1 条、`abGroups` 写 1 条；复用已有资源时，`resources` 可以写空列表，
但必须提供 1 条 `abGroups`。生成器会按 1 份 `copies` 自动派生对照组；多份 `copies` 又没手写
`abGroups` 则拒绝生成。详细跑法见 `automation/docs/run_taskorder.md`。

## 圈选口径

`clickThreshold` 和 `exposureThreshold` 是 A 路径建圈选任务时填写的数据阈值，
不是博文数量标准。`预估圈选总数`只记录，不参与拦截或调阈值。

A 路径是否达标只看后台 `日均曝光(预估) ≥ 10000`，越多越好；B 路径没有建前的曝光预估值。
