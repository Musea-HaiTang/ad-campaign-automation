# -*- coding: utf-8 -*-
"""命名规则（唯一实现）——资源名 / 客群任务名 / 工单任务名 / 物料文件名都从这里出。

背景：同一套名字原先在 gen_yaml.py、gen_material.py、run_audience.py、run_taskorder.py
各拼一遍，而文档写的是另一套公式。后台按**精确字符串**匹配（工单选 AB 资源靠它），
对不上就选不中——所以名字必须只有一个出处。

规则（契约见 `../campaigns/README.md`）：

    桶名    = {前缀}-{id}类          如 SenseNova征文hang-A类
    客群名  = 桶名 · {topic}          如 SenseNova征文hang-A类 · 模型部署 / GPU 基础设施
    工单名  = 与客群名同一个字符串
    资源名  = 桶名 · {角色中文}        如 SenseNova征文hang-A类 · 对照
    活动标签 / 物料文件名 = {前缀}-{N}类[投放物料.html]
    重投后缀 = audiences[].nameSuffix 追加在客群名/工单名/资源名末尾（桶名不带，见 name_suffix）

前缀以 `campaign.namePrefix` 为准；没有它才退回 YAML 里手写的 `audiences[].taskName`。
纯函数，不碰文件、不读 YAML、不 import 别的模块 → 可以直接测（tests/test_naming.py）。
"""


def prefix(campaign):
    """活动命名前缀（`campaign.namePrefix`）；没有就返回空串。"""
    return (campaign.get("namePrefix") or "").strip().rstrip("-")


def require_prefix(campaign):
    """生成器用：前缀必填——缺了直接报错，不许猜一个名字写到后台。"""
    p = prefix(campaign)
    if not p:
        raise ValueError("campaign.namePrefix 缺失：资源/客群/工单/物料都靠它命名，请在活动定义里补上")
    return p


def bucket_name(campaign, audience):
    """桶名段 `{前缀}-{id}类`；没有前缀时用 YAML 里手写的 `audiences[].taskName`。"""
    p = prefix(campaign)
    if p:
        aid = str(audience.get("id") or "").strip()
        return ("%s-%s类" % (p, aid)) if aid else p
    return (audience.get("taskName") or "").strip().rstrip("-")


def name_suffix(audience):
    """重投/二期的名字后缀（`audiences[].nameSuffix`，如 `-2`）。

    追加在**客群名 / 工单名 / 资源名**末尾——同一活动二次起投时，后台这些对象**重名建不了**
    （2026-09-17 火山引擎MediaKit 的 D 桶换词重投就是这种情况）。
    桶名本体（`bucket_name`）**不带**它：后台回读工单是按桶名找的，桶名带上后缀反而搜不到。
    """
    return str(audience.get("nameSuffix") or "").strip()


def audience_task_name(campaign, audience):
    """圈选任务名（= 后台客群名）：`桶名 · {topic}`；没写 topic 就只有桶名。"""
    base = bucket_name(campaign, audience)
    topic = (audience.get("topic") or "").strip()
    name = ("%s · %s" % (base, topic)) if (base and topic) else base
    return name + name_suffix(audience)


def order_task_name(campaign, audience):
    """任务工单名：规则上就该和圈选任务名**一模一样**（同一个字符串）。"""
    return audience_task_name(campaign, audience)


def resource_name(campaign, audience, label):
    """资源名：`桶名 · {角色中文}`（对照 / 实验1 / 实验2）。"""
    base = bucket_name(campaign, audience)
    label = str(label or "").strip()
    name = ("%s · %s" % (base, label)) if (base and label) else base
    return name + name_suffix(audience)


def campaign_label(campaign, bucket_count):
    """活动标签：`{前缀}-{N}类`（N = 桶数）；campaign.label 与物料文件名都用它。"""
    return "%s-%d类" % (require_prefix(campaign), bucket_count)


def material_file_name(campaign, bucket_count):
    """投放物料 HTML 文件名：`{前缀}-{N}类投放物料.html`。"""
    return campaign_label(campaign, bucket_count) + "投放物料.html"


def name_warning(campaign, audience):
    """执行层用：YAML 手写的 `taskName` 和命名规则对不上时给一句提醒；一致/判断不了返回 None。

    只提醒、不中止——后台要按规则算出来的名字找，提醒是给对手改过数据的人看的。
    """
    if not prefix(campaign):
        return None
    given = (audience.get("taskName") or "").strip()
    want = bucket_name(campaign, audience)
    if not given or given == want:
        return None
    return ("⚠ audiences[%s].taskName=%r 与命名规则 %r 不一致；后台按 %r 找，请核对"
            % (audience.get("id", "?"), given, want, want))
