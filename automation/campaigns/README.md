# 整活动 YAML · 字段规范

> 本文件定义 `activities/{活动名}/配置/{品牌}{负责人}.yaml` 的**字段规范**。
> 它是所有自动化脚本消费的唯一对象：AI 在「物料你确认 OK」后按此生成一份（**现由 `ad_output/工具/gen_yaml.py` 从「活动定义 YAML」装配**），脚本据此建 任务组/资源/客群/工单。
> 原则：**只存需要填进后台的数据**，不含统计/给人看的摘要。

---

## 顶层结构

| 段 | 必填 | 说明 |
|---|---|---|
| `version` | ✓ | schema 版本，现为 1 |
| `adType` | ✓ | 广告位类型标识（→ 决定 `controls`），如 `blog-page-t0` |
| `label` | ✓ | 中文名，如 `{品牌}{负责人}-7类` |
| `controls` | ✓ | 本类型固定项（见下） |
| `campaign` | ✓ | 本次投放计划信息（命名/校验用） |
| `audiences` | ✓ | 人群桶数组（桶 = 客群 = 工单，1:1） |
| `taskOrder` | 建工单时 ✓ | 执行层第 4 步「建任务工单」专用配置（仅 `run_taskorder.py` 读） |

## `controls`（类型固定项）

这部分对同类型活动基本不变，由 AI 按本文件规范生成，**内嵌进来使本文件自包含**（脚本只读 campaign yaml 一份，无需单独的 types 文件）。

| 字段 | 说明 |
|---|---|
| `channelType` | 进入时的类型标签，如 `页面类` |
| `channel` | 渠道位，如 `PC-博客-详情页-相关推荐T0` |
| `materialPath` | 素材类型三级路径，如 `[静态广告, 信息流, 文本]` |
| `defaults` | 表单默认值：`businessLine` / `isPopup` / `adClient` / `closeBtnColor` |
| `fields` | 每条资源文本控件定位：`title`/`summary`/`link`（placeholder + type） |

## `campaign`（本次投放计划）

| 字段 | 说明 |
|---|---|
| `brand` | 品牌，如 `华为云码道` |
| `phase` | *(暂预留) 期次，如 `二期`；当前不用于命名，可不填* |
| `owner` | 负责人标识，如 `hang` |
| `taskGroupName` | **任务组名**（第1步建任务组/选已有组用），格式 `{品牌}{负责人}`，如 `{品牌}{负责人}`。⚠️ 它只管「建/选任务组」，**不用于命名**子实体（资源/客群/工单）；命名用 `namePrefix`/`audiences[].taskName`。沿用已有任务组时，任务组名 ≠ 活动命名前缀 |
| `namePrefix` | *(可选)* **统一命名前缀**（主名），如 `{品牌}{负责人}`；新建任务组时 `taskGroupName = namePrefix`，沿用已有组时 `taskGroupName` 用它处值，但子实体仍用 `namePrefix` |
| `activityLink` | 活动链接（用户一开始给的活动链接，**所有资源共用**；默认值，资源可覆盖） |

> **命名只有一处实现**：`automation/scripts/naming.py`（桶名 / 客群名 / 工单名 / 资源名 / 物料文件名）。
> 生成器（`gen_yaml.py`、`gen_material.py`）和执行脚本都 import 它——**改命名规则只改这个模块**，
> 别在别处拼字符串（后台按精确字符串匹配，名字对不上就选不中）。

## `audiences`（人群桶数组）

一个数组元素 = 一个人群桶 = 1 个客群 = 1 个任务工单。数量即工单数（现定 7，可调）。

| 字段 | 说明 |
|---|---|
| `id` | 桶标识：`A`~`Z` |
| `topic` | 桶主题，如 `AI 编程核心` |
| `target` | 目标读者描述 |
| `taskName` | **桶名**，格式 `{namePrefix}-{id}类`，如 `{品牌}{负责人}-A类`。⚠️ 前缀用**活动名**（`campaign.namePrefix`），不是 `taskGroupName`（沿用已有任务组时两者不同）。有 `namePrefix` 时它只是生成器写出来的结果；没有 `namePrefix` 时才反过来用它 |
| `subBusinessLine` | 建资源时后台选的**子业务线**（示例值，需按实际选） |
| `clickThreshold` | *(可选)* 圈选任务"点击需≥"阈值，默认 `0`；`--tune` 自动调优后写入 |
| `exposureThreshold` | *(可选)* 圈选任务"曝光需≥"阈值，默认 `1`；`--tune` 自动调优后写入 |
| `keywordGroup.keywords` | 客群圈选关键词整行（第3步圈选用户用，英文逗号分隔） |
| `resources` | 该桶**本轮新建**的资源（`role`：`control`/`experiment1`/`experiment2`）。**幸存资源不重建**（在 `abGroups` 里按名字绑定），所以**可以是空列表** = 本桶本轮一条都不新建 |
| `abGroups` | *(可选)* **本桶工单**的 AB 三组资源（结构同 `taskOrder.abGroups`）。不写才回落到 `taskOrder.abGroups` |
| `distributionList` | *(可选)* **本桶工单**的用户名单名。不写才回落到 `taskOrder.distributionList`，再回落到本桶客群名 |
| `nameSuffix` | *(可选)* **重投/二期的名字后缀**（如 `-2`）：追加在**客群名 / 工单名 / 资源名**末尾（`naming.name_suffix`）。同一活动二次起投时后台这些对象**重名建不了**才用它；**桶名本体不带**（后台回读工单按桶名找）。例：资源名 `…-D类 · 对照-2` |

> **AB 资源 / 用户名单是逐桶的**：1 桶 = 1 工单，工单要挂**本桶**那 3 份资源、用**本桶**的名单，
> 所以写在 `audiences[]` 里；`taskOrder.abGroups` / `taskOrder.distributionList` 只是「桶没写时的兜底」
> （全活动共用一组，彩排借别人的对象时用得上）。真实投放前请确认每桶都写了自己的 `abGroups`，
> 否则所有工单会指向同一组创意。

每个 `resources[]` 元素字段：

| 字段 | 说明 |
|---|---|
| `role` | 对照 (`control`) / 实验1 (`experiment1`) / 实验2 (`experiment2`) |
| `name` | 资源名称，格式 `{namePrefix}-{id}类 · {role中文}`，如 `{品牌}{负责人}-A类 · 对照`（由 `naming.resource_name()` 生成） |
| `title` | 广告标题（1 行，无 CTA） |
| `summary` | 广告摘要（1 行） |
| `link` | *(可选)* 活动链接覆盖，默认继承 `campaign.activityLink`；同一活动一般相同，仅个别资源不同才写 |
| `highlight` | *(可选)* **飘红词**（2026-09-24 加）：填了就选「是否飘红 = 是」并写入该词；留空 = 不飘红。后台只能填一个表达、正则最长匹配、**标题 + 摘要里所有出现处都会标红**，所以选词前先扫一遍文案 |

---

## 必填 / 默认值 / 字段名保护（装载时校验）

装载唯一入口：**`automation/scripts/campaign.py`**（`campaign.load(路径)`）。执行层四个脚本都从它拿配置，
生成器 `gen_yaml.py` 写完也用它自检——**产出即验证**，坏 YAML 进不了 `activities/`。

**必填**（缺了/写成空 → 启动就报错，并一次列全所有问题）：

| 位置 | 字段 |
|---|---|
| `campaign` | `taskGroupName`、`activityLink` |
| `controls` | `channel`、`materialPath`、`defaults.businessLine`、`fields.{title,summary,link}.placeholder` |
| `audiences[]` | `id`、`subBusinessLine`、`keywordGroup.keywords`、`resources`（**必须是列表**；空列表合法 = 本桶本轮没有新建资源，见 2026-09-29 起的 `-7` 批 E 桶） |
| `audiences[].resources[]` | `role`、`name`、`title`、`summary`（`highlight` 可选） |
| `taskOrder` | `businessLine`、`taskGroup`、`channel`、`deliveryDate.start / .end`；`abGroups`（≥1 组）**仅当有桶没写自己的 `abGroups` 时必填**（全局兜底） |

**默认值**（只写在 `campaign.py` 的 `DEFAULTS` 一处，脚本不再各自兜底；写过的值不会被覆盖）：
`taskOrder.price = 20`、`taskOrder.deliveryDate.mode = set_time` / `timeStart = 8` / `timeEnd = 23`、
`taskOrder.exposureCaps = {daily: 100000, weekly: 500000, total: 500000}`。

> ⚠️ **投放日期不再有默认值**：以前脚本里写死 `2026-09-09 ~ 2026-09-11`（日期不写就照这个跑），
> 现在 `start`/`end` 必填——日期是最容易跑错的一项，宁可启动就报错。

**字段名保护**：不在契约里的字段会报「未知字段 X.Y，是不是想写 Z？」。
以前 `exposureCap` 少写一个 s 不报错，三个曝光框静默用默认值一路填到后台，跑到浏览器第 3 步才发现。

**子业务线只有一个来源**：`audiences[].subBusinessLine`（工单也取**本桶**这个值）。
`taskOrder.subBusinessLine` 在契约里不存在（历史上脚本留过一个永远取不到的兜底，已删）。

---

## 生成前确认（待确认字段）

部分字段**物料/活动细则推导不出来**（不是用户一开始就会给的），生成 yaml 前必须先跟用户确认，否则会填错后台。

AI 在「物料你确认 OK、**但还没生成 yaml**」时，先列一张**待确认清单**，逐项列出本次要填但来源不明确的字段，
等用户确认/补值后才生成。**这也是执行层前置门控的节点**——必给项（负责人→任务组名 / 子业务线 / 是否新建任务组+名 /
**投放日期+时间段** / **计费价格**）在此一并确认，未给齐不继续。

| 字段 | 来源 |
|---|---|
| **`price`（计费价格）** | **必须问用户**（2026-09-22 起**不再固定数值**；历史用过 20 / 30，**一律不套用**）。写 YAML 前就问，问清再生成——YAML 里缺它直接报错（`campaign.py` 必填校验） |
| `owner` / `taskGroupName` | 需用户提供（负责人标识，决定任务组名 `{品牌}{负责人}`） |
| `subBusinessLine` | 需用户提供（物料/细则未含，且可能每桶不同） |
| 是否新建任务组 + 名字 | 需用户提供（立项后一般自动生成，通常跳过；保底才建） |
| `deliveryDate`（投放日期起止 + 时间段） | **需用户提供**（日期区间 `start/end` + 时段 `timeStart/timeEnd`，如 8–23 点）。⚠️ **`start` 一律填「建批当天」=「复盘当天」**（2026-09-28 定；**2026-09-29 用户补**：判定不看满一整天、曝光到门槛就判，所以哪天复盘哪天起投）：工单建好后**用户没有后台修改权限**，起始日只能在创建时定对——写成明天 = 白少一天曝光 |
| `businessLine`（在 `controls.defaults`） | 类型默认（blog-page-t0），一般不需改 |
| `channel` | 活动细则 §5（可从活动链接推导） |
| `activityLink` | 用户一开始给的活动链接（已提供则不用再问） |

> 规则：**凡物料/细则/活动链接推不出来的"必填填充字段"，都进待确认清单**；用户没说就生成 = 违规。
> 若用户一开始就主动给了这些值，则跳过对应项。
>
> `taskOrder.channelSizeId`（渠道尺寸/ID）**不进待确认清单**：它是后台「点渠道即自动带上」的值，脚本不单独填，只是 yaml 里记一笔用来核对渠道。

---

## 与后台 4 实体 / 5 步流程的对应

| 后台实体 | 数据来源（yaml） | 步骤 |
|---|---|---|
| 任务组 | `campaign.taskGroupName` | 1. 建任务组 |
| 资源 | `audiences[].resources[]`（N 桶 × 3 条） | 2. 新建资源 |
| 客群 | `audiences[].keywordGroup.keywords` | 3. 圈选用户 |
| 任务工单 | `taskOrder`（channel + abGroups + deliveryDate + distributionList + exposureCaps 等） | 4. 建任务工单（`run_taskorder.py`） |

> 资源创建脚本（`run_ads.py`）消费 `resources[]`；此后客群/工单脚本也消费同一份 yaml，无需多份数据。

---

## `taskOrder`（执行层第 4 步 · 建任务工单专用配置）

`run_taskorder.py` 读取这一段；`run_ads.py` / `run_audience.py` 不读。只在需要跑「建任务工单」时才写。

| 字段 | 说明 |
| --- | --- |
| `businessLine` | 业务线（事业部），显式选，如 `企业服务事业部` |
| `taskGroup` | 任务组：**选已有的**（如 `华为云码道-博客T0`），不给就搜不到 |
| `taskName` | *(可不填，脚本按 `audiences[]` 逐桶派生)* 工单任务名 = `{audiences[].taskName} · {topic}`（活动命名前缀），如 `{品牌}{负责人}-A类 · 模型部署 / GPU 基础设施`。`run_taskorder.py` **逐桶（7 个）**建工单，不再只跑单个 |
| `channel` | 渠道（穿梭框），如 `PC-博客-详情页-相关推荐T0` |
| `channelSizeId` | 该渠道的 尺寸/ID，如 `58`（正常点渠道即带上，非单独勾选项） |
| `abGroups` | *(全局兜底)* AB 测试三组 `[{label, resource, weightPct}]`。**权重按本桶资源条数算**：3 条 = 对照组 34 / 实验组1 33 / 实验组2 33；**2 条 = 对照组 50 / 实验组1 50**（合计必须 100，后台会校验）。**优先用 `audiences[].abGroups`**，本桶没写才用这里。详见下方「AB 组三条硬规则」 |
| `price` | 计费价格（CPM）。**必填、由用户当期给**（2026-09-22 起不再固定数值，历史用过 `20` / `30` 都不套用）——见下方「生成前确认」 |
| `deliveryDate` | 投放日期=设置时间：`{mode: set_time, start, end}`，如 `2026-09-09`~`2026-09-11`。⚠️ **`start` = 建批当天 = 复盘当天**（工单建好后用户没有后台修改权限，起始日只能创建时定对；见「生成前确认」） |
| `distributionList` | *(可不填，全局兜底)* 分发方式=分发名单时选的**用户名单**名。优先级：`audiences[].distributionList` → 本字段 → **本桶客群名**（= `{audiences[].taskName} · {topic}`，也就是圈选任务名；「一键创建分发名单」的产物名与它一致）——正式跑走最后这条。⚠️ 填**真名**，别抄后台显示的「… 用户名」——那个后缀是后台自己加的，带上就搜不到 |
| `exposureCaps` | 每日/每周/总曝光上限，默认 `100000 / 500000 / 500000` |

> **依赖顺序**：任务组(可能自动创建) → 资源 → 客群(圈选) → 任务名单(一键创建分发名单) → 任务工单。
> 工单这一步要等**用户名单**生成后，`分发方式 = 分发名单 → 选用户名单` 才选得到；用户名单名与圈选任务名保持一致。

### AB 组三条硬规则（2026-10-08 真踩到，务必按这三条生成）

1. **权重按资源条数算**：3 条 = `34/33/33`；**2 条 = `50/50`**。合计不是 100 后台会直接拒
   （原文：`资源流量占比累计为67%，请将流量占比总量调整为100%`）。**别用固定序列取前 N 个**——
   2 资源桶取 `[34, 33]` 正好踩中这个坑。
2. **AB 行位次不能跳**：三行的行名固定是 `对照组 → 实验组1 → 实验组2`，只能"从前往后填满"；
   所以 **2 资源桶永远是 `对照组 + 实验组1`**，把第二条标成"实验组2"会报 `实验组1资源ID不能为空`。
3. **资源名的角色段要和它所在的 AB 行一致**（`对照` / `实验1` / `实验2`）：复盘是拿名字认谱系的，
   名字与槽位错位会让跨批对比看错对象。2 资源桶里"从实验2 谱系改过来的"那条，**按槽位命名成 `实验1-<后缀>`**，
   并在台账里记 lineage（例：`实验2-2 → 实验1-4（小改）`）。

> **生成后先自检**：`automation/scripts/check_batch_plan.py --config <批次 YAML>`（离线、秒级，
> 就是把上面三条 + naming + 工单字段一起过一遍）。跑 `run_ads` / `run_taskorder` 之前跑它。

> 其余后台字段（签呈号/渠道类型/资源平台/尺寸/产品页面/形式/价格上限/频次控制/门槛频次控制/展示概率/用户排除）
> 默认不填，脚本留空。

## 圈调优（`--tune`）

客群圈选会先算"预估圈选总数"。若某桶超出正常范围（默认 `10000–200000`），
`run_audience.py --tune` 会自动升"曝光/点击"阈值（**只升、每次重跑分析、读取新总数**），
取**第一个 ≤ 上限且 ≥ 下限**的阈值（尽量多圈选、靠近上限）；若整数阈值无法落入区间
（调高后反而 < 下限），则标记 `needs_keywords` 建议改词，**不硬选**。

调优结果写入 `activities/{活动名}/配置/{品牌}{负责人}.thresholds.yaml`（每桶 `click/exposure/count/status/base`，
栏位形状只有一处定义：`scripts/campaign.py` 的 `threshold_record()`——策略结果对象与记录字典都收），
由 `--submit` 自动读取；未写出的桶按默认 `0/1`。写回是**盖格子**：只改这次跑到的桶，其余桶的记录保留
（2026-09-23 前 `--tune` 是整批覆盖，没跑到的桶会被抹掉）。
