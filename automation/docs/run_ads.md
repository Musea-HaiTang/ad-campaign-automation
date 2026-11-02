# 建资源 · `run_ads.py`（执行层第 2 步）

> **管什么**：怎么跑、后台新建资源的操作链、只有它才会踩的坑。
> **不管什么**：`controls` / `audiences[].resources` 字段怎么填 → [`../campaigns/README.md`](../campaigns/README.md)；排队 / 断点 / 止损 / 回读口径 → [`../README.md`](../README.md)「设计原则」。
> **谁什么时候读**：建资源前——每个进批的桶 2~3 条。

## 开工前

- 一条资源 = 一份文案，走 `页面类 → 新建资源 → 基本信息 → 选渠道 → 动态广告 → 其它 → URL/标题/用户名/描述 → 确定`。
- **前置**：任务组必须已存在（`run_taskgroup.py` 或 CRM 立项自动生成），否则 `preflight` 直接中止。
- **登录身份**：创建前必须拿到非空用户名和 `MPToken/MPUser`；缺任何一项直接中止，避免后台把申请人写成空值。

## 怎么跑

```powershell
# dry-run：填 + 校验 + 截图，点「取消」，不创建（默认）
.venv\Scripts\python.exe -u automation/scripts/run_ads.py --config activities/{活动名}/配置/{品牌}{负责人}.yaml

... --submit                    # 建批：一律直接 --submit
... --only A --submit           # 只跑指定桶（先建一个看效果再批量），也支持 --only A,C
... --reset-progress            # 断点账本不想要了，从头全跑
... --v2-db 别的.db             # 只在测试/排障时覆盖默认数据库
--headed                        # 想看浏览器窗口
```

- **建批一律直接 `--submit`**：它本身就是「填完 → 逐字段回读 → 全过才点确定」，正式跑不截图；彩排只剩"脚本刚改完、不想动后台"这一个用途。
- **preflight**：跑主流程前先开一次弹窗读「任务组」下拉，校验 `campaign.taskGroupName` 存在；**不存在立即中止**并列出实际可选项前 20（免得后续每条连锁失败）。
- **提交前闸门 + 自动重试 + 精确回读**：资源名或任一文案字段回读不过 → 关弹窗、不提交，并整条重开重试一次；第二次仍失败才记 `warn`。`--submit` 跑完后直接复用 `check_campaign.py` 的**日期窗 + 资源名前缀 + 全分页**精确检查，不再使用异步加载不稳定的“任务组”下拉。查不到的记 `warn`（`RESULT: HAS_WARN`、退出码 1）；查询不完整只报“未确认”，不当缺失。
- **中断恢复和提交后不重试**：统一按 [`脚本通用约定.md`](脚本通用约定.md) 执行。
- **申请人回读**：提交后用新增资源 ID 查详情，`createBy` 必须等于当前登录用户名；不一致记 `warn`，防止以后再次出现申请人空白。
- 截图 `item_XX_filled.png` **仅 dry-run 产生**。

## 字段从哪来

| 层 | 内容 | 放哪 |
|---|---|---|
| **类型固定项** | 这类广告固定不变的控件：`channelType`、`channel`、`materialPath`、`username`、`defaults`、`fields` | campaign yaml 的 `controls`（内嵌、自包含） |
| **整活动数据** | 任务组名 / 活动链接（`campaign`）+ 人群桶（`audiences`：关键词 + 每桶资源） | campaign yaml |

> 执行器只认 `controls` + `audiences[].resources`，不写死某类——**加类型 = 换 `controls`**（如图片类改 `materialPath` / `fields`）。字段规范以 `campaigns/README.md` 为准。

动态广告直接填写 URL、标题、用户名、描述；**不点「解析」也能填写和提交**。`username` 默认读取首次登录后保存在 `.local/operator.json` 的 `ad_username`。

## 已知坑

- **业务线必须显式重选**：下拉显示"企业服务事业部"但模型值可能为空，提交会报 `departmentId is required`。执行器在填子业务线**前**重选业务线。
- **渠道勾选**：Element UI 把原生 checkbox 藏了，要点可见的 `.el-checkbox__inner`；移入按钮找**可用**的那个（别点 disabled 的）。
- **下拉查找**：先 `filter(has_text)` 再遍历，避免全页几百项导致很慢。
- `goto` 用 `domcontentloaded`（`networkidle` 会被 SPA 长连接卡住）；运行加 `python -u` 看实时输出。
- **页面失活**：新页会先执行 4 秒页面级探针；目标页 `Page.goto` 超时说明渲染进程可能已卡死，恢复时直接重启公共浏览器一次再重试，不能只靠空白页探针通过。运行日志落 `activities/{活动}/日志/runs/`。
