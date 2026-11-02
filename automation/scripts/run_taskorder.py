# -*- coding: utf-8 -*-
"""CSDN 任务工单 · 数据驱动自动化（彩排默认，绝不点「创建」）

读一份整活动 YAML，打开「创建工单」表单，按 `taskOrder` 段填：业务线 / 子业务线 /
任务组 / 任务名称 / 渠道(穿梭框) / AB测试(对照组·实验组1·实验组2 + 流量占比) /
投放类型(流量策略) / 计费价格 / 投放日期(设置时间) / 分发方式(分发名单→用户名单) / 曝光上限，
并逐字段校验+截图。

默认彩排：只填+校验+截图，点「取消」关闭弹窗，不点「创建」不创建。
加 --submit 才真正点「创建」（请谨慎，创建即入后台）。

页面交互（会话/下拉/穿梭框/弹窗/截图）都在 `csdn_ui.py` 里；本脚本只管「这次要办什么」。

用法：
    .venv\\Scripts\\python.exe -u automation/scripts/run_taskorder.py --config activities/华为云码道/华为云码道hang.yaml

    ... --only C --start 2026-09-30
        同一批的桶**隔天补建**时用：规则是「**什么时候发任务，起投日就是哪天**」（= 复盘当天，
        见流程文档 §8），而 YAML 里那份 `start` 是上一批桶的真实参数、不能改 —— 所以建这条工单时覆盖掉。
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bucket_runner  # noqa: E402
import cli  # noqa: E402
import csdn_ui as ui  # noqa: E402
import execution_state as es  # noqa: E402
import naming  # noqa: E402
import remote_lookup  # noqa: E402
import workspace_sync  # noqa: E402
import workspace_repo  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

LIST_URL = "https://mp-admin.csdn.net/silkroad-dist/#/distribute/distApplyOrder/list"
RESOURCE_STYLE = "标题+描述"
PH_ORDER_FILTER = "请输入任务名称模糊查询"


def pre_submit_error(steps):
    """兼容调用点：统一复用执行层的提交前重试异常。"""
    return bucket_runner.pre_submit_error(steps)


# ---------- 表单字段（按 placeholder 定位） ----------
def set_select(s, form, placeholder, value, tag):
    inp = form.locator("input[placeholder='%s']" % placeholder).first
    if not inp.count():
        raise RuntimeError("无下拉框[%s]（%s）" % (placeholder, tag))
    ui.select(s, inp, value)
    ui.log("  %s: %s" % (tag, value))


def set_select_search(s, form, placeholder, value, tag):
    inp = form.locator("input[placeholder='%s']" % placeholder).first
    if not inp.count():
        raise RuntimeError("无输入框[%s]" % placeholder)
    ui.search_select(s, inp, value)
    ui.log("  %s: %s" % (tag, value))


def set_input(form, placeholder, value, tag, mul=False):
    tag_name = "textarea" if mul else "input"
    loc = form.locator("%s[placeholder='%s']" % (tag_name, placeholder)).first
    if not loc.count():
        ui.log("  !! 无 %s[%r]" % (tag_name, placeholder))
        return False
    loc.fill(str(value))
    actual = loc.input_value()
    ok = actual == str(value)
    ui.log("  %s %s | %r" % ("✓" if ok else "✗", tag, actual))
    return ok


# ---------- 打开「创建工单」弹窗 ----------
def open_dialog(page):
    ui.goto(page, LIST_URL)
    btn = page.locator("button.el-button--primary:visible").filter(has_text="创建").first
    expect(btn).to_be_visible(timeout=15000)
    btn.click()
    form = page.locator(".task-form").first
    if not form.count():
        form = page.locator(ui.SEL_DIALOG).last
    expect(form).to_be_visible(timeout=12000)
    # 等「业务线/事业部」下拉出现，确认表单已渲染
    expect(form.locator("input[placeholder='%s']" % ui.PH_DEPT).first).to_be_visible(timeout=12000)
    return form


def progress_key(cfg, aud):
    """账本键 = 本批完整工单名；不同批次天然不同，不再靠人工清账本。"""
    return naming.order_task_name(cfg["campaign"], aud) or (
        "%s|%s" % (cfg["campaign"]["taskGroupName"], aud["id"]))


def payload_for(cfg, aud):
    """只把真正进入工单表单的字段纳入指纹。"""
    t = cfg["taskOrder"]
    return {
        "taskName": progress_key(cfg, aud),
        "subBusinessLine": aud["subBusinessLine"],
        "abTest": t.get("abTest", True),
        "abGroups": aud.get("abGroups") or t.get("abGroups") or [],
        "distributionList": aud.get("distributionList") or t.get("distributionList") or "",
        "businessLine": t["businessLine"],
        "taskGroup": t["taskGroup"],
        "channel": t["channel"],
        "price": t["price"],
        "deliveryDate": t["deliveryDate"],
        "exposureCaps": t["exposureCaps"],
    }


# ---------- AB 测试 ----------
def click_radio_in_item(item, text):
    r = item.locator(".el-radio").filter(has_text=text).first
    expect(r).to_be_visible(timeout=6000)
    r.locator(".el-radio__inner, input[type='radio']").first.click()


def enable_ab_test(form):
    item = form.locator(".el-form-item").filter(has_text="AB测试").first
    expect(item).to_be_visible(timeout=6000)
    click_radio_in_item(item, "是")
    ui.log("  AB测试: 是")


def disable_ab_test(form):
    """AB测试 = 否（**单资源长期单**，2026-10-12 按真机勘察加）。

    后台默认就是「否」（探针 `_tmp/_probe_no_ab.py` 实测）：这种状态下 `资源信息` 块里不是三张 AB 卡片，
    而是一个**必填的单资源下拉** `.resource-row input[placeholder='请输入资源名称搜索']`，**没有流量占比**。
    这里显式点一次「否」，免得将来后台改了默认值。
    """
    item = form.locator(".el-form-item").filter(has_text="AB测试").first
    expect(item).to_be_visible(timeout=6000)
    click_radio_in_item(item, "否")
    ui.log("  AB测试: 否（单资源）")


def set_resource_style(s, scope):
    """资源挂载后选择固定样式「标题+描述」并回读。"""
    sel = scope.locator("input[placeholder='请选择资源样式']:visible").first
    expect(sel).to_be_visible(timeout=8000)
    sel.click()
    s.page.wait_for_selector(ui.SEL_DROPDOWN, timeout=8000)
    ui.pick_option(s, RESOURCE_STYLE)
    actual = sel.input_value()
    if actual.strip() != RESOURCE_STYLE:
        raise RuntimeError("资源样式回读不一致：期望 %r 实际 %r" % (RESOURCE_STYLE, actual))
    ui.log("  [资源样式] %s ✓" % RESOURCE_STYLE)


def set_single_resource(s, form, resource_name):
    """AB测试=否 时的「资源」下拉：搜一条 → 选 → 回读。没有流量占比。"""
    page = s.page
    if not resource_name:
        raise RuntimeError("AB测试=否 但没有资源名（abGroups[0].resource 为空）")
    row = form.locator(".resource-row").first
    if not row.count():
        raise RuntimeError("没找到单资源选择区（.resource-row）")
    sel = row.locator("input[placeholder='%s']" % ui.PH_RESOURCE_SEARCH).first
    expect(sel).to_be_visible(timeout=8000)
    sel.click()
    page.wait_for_selector(ui.SEL_DROPDOWN, timeout=8000)
    page.wait_for_timeout(300)          # 同 pick_ab_resource：垫等在等后台的远程过滤
    try:
        sel.fill(resource_name)
    except Exception:
        sel.press_sequentially(resource_name)
    page.wait_for_timeout(500)
    ui.pick_option(s, resource_name)
    got = ui.read_field(row, ui.PH_RESOURCE_SEARCH)
    if got.strip() != resource_name.strip():
        raise RuntimeError("单资源回读不一致：期望 %r 实际 %r" % (resource_name, got))
    ui.log("  [资源] %s ✓" % resource_name)
    set_resource_style(s, form)


def pick_ab_resource(s, form, group_label, resource_name, weight):
    """点 AB 组标签（对照组/实验组1/实验组2）→ 打开该组弹窗 → 搜资源(异步加载) → 选 →
    填流量占比 → 确定。"""
    page = s.page
    # 有该组卡片则点卡片；没有（实验组2）则点资源区「+」→ 弹「新增实验组」
    tab = form.locator(".abtest-resource-item").filter(has_text=group_label).first
    if tab.count():
        tab.click()
    else:
        add = form.locator(
            "[class*='abtest'] .el-icon-plus, [class*='abtest'] button, .el-form-item .el-icon-plus"
        ).last
        if not add.count():
            add = form.locator("button").filter(has_text="+").last
        expect(add).to_be_visible(timeout=6000)
        add.click()
    page.wait_for_timeout(150)      # 等资源弹窗渲染；真就绪与否由下面 expect(可见) 兜住（2026-09-22 优化：原 500ms）
    # 资源弹窗：用「资源信息搜索框」反查所属弹窗（标题可能是 对照组/实验组1/新增实验组）
    prov_sel = page.locator("input[placeholder='%s']:visible" % ui.PH_RESOURCE_SEARCH).last
    expect(prov_sel).to_be_visible(timeout=8000)
    dlg = prov_sel.locator("xpath=ancestor::div[contains(@class,'el-dialog')]").first
    expect(dlg).to_be_visible(timeout=6000)
    sel = dlg.locator("input[placeholder='%s']" % ui.PH_RESOURCE_SEARCH).first
    expect(sel).to_be_visible(timeout=6000)
    # 资源信息（可搜索 el-select）：点开 → 输入 → 等加载 → 选下拉项
    sel.click()
    page.wait_for_selector(ui.SEL_DROPDOWN, timeout=8000)
    page.wait_for_timeout(300)
    try:
        sel.fill(resource_name)
    except Exception:
        sel.press_sequentially(resource_name)
    page.wait_for_timeout(500)      # 等远程查询返回（2026-09-22 实测：降到 150ms 反而出现 5.7s 的轮询空转，保留原值）
    ui.pick_option(s, resource_name)   # 2026-09-22 试过 interval=0.1：多读 27 次快照、平均反而变慢 → 保留默认 0.3 s
    ui.log("  [%s] 资源: %s ✓" % (group_label, resource_name))
    set_resource_style(s, dlg)
    # 流量占比
    wbox = dlg.locator("input[placeholder='%s']" % ui.PH_WEIGHT).first
    if wbox.count():
        wbox.fill(str(weight))
        ui.log("  [%s] 流量占比: %s" % (group_label, weight))
    # 确定
    btn = dlg.locator("button.el-button--primary").filter(has_text="确定").last
    if btn.count():
        btn.click()
        try:
            expect(dlg).to_be_hidden(timeout=8000)
        except Exception:
            pass
        ui.log("  [%s] 已确定" % group_label)


# ---------- 投放日期（设置时间） ----------
# ---------- 投放日期（按月导航 + 回读自检） ----------
def _ym(text):
    """把 "2026 年 9 月" 解析成 (2026, 9)。"""
    m = re.search(r"(\d{4})\D+(\d{1,2})", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _ymd(s):
    """'2026-09-14' → (2026, 9, 14)。"""
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(s))
    if not m:
        raise RuntimeError("投放日期格式应为 YYYY-MM-DD，收到 %r" % s)
    return tuple(int(x) for x in m.groups())


def _panels(page):
    return page.locator(".el-date-range-picker__content")


def _panel_month(page, idx):
    p = _panels(page).nth(idx)
    return _ym(p.locator(".el-date-range-picker__header").first.inner_text())


def _panel_for_month(page, ym):
    """翻日历直到目标年月出现在某个面板里，返回那个面板（左/右两块）。"""
    for _ in range(30):
        ps = _panels(page)
        for i in range(ps.count()):
            if _panel_month(page, i) == ym:
                return ps.nth(i)
        cur = _panel_month(page, 0)
        if cur is None:
            break
        if ym > cur:
            ps.last.locator(".el-picker-panel__icon-btn.arrow-right").first.click()
        else:
            ps.first.locator(".el-picker-panel__icon-btn.arrow-left").first.click()
        page.wait_for_timeout(250)
    raise RuntimeError("日历翻不到 %s 年 %s 月" % ym)


def _click_day(panel, day):
    cells = panel.locator("table.el-date-table td.available")
    for i in range(cells.count()):
        if cells.nth(i).inner_text().strip() == str(day):
            cells.nth(i).click()
            return
    raise RuntimeError("面板里没有 %s 号可选" % day)


JS_INJECT_HOURS = r"""(args) => {
  const start = args[0], end = args[1], hours = args[2];
  const seen = new Set();
  let owner = null, key = null;
  function walk(vm) {
    if (!vm || seen.has(vm) || owner) return;
    seen.add(vm);
    const d = vm.$data || {};
    for (const k of Object.keys(d)) {
      const v = d[k];
      if (v && typeof v === 'object' && !Array.isArray(v) && ('hourLimits' in v || 'dateLimits' in v)) {
        owner = vm; key = k; return;
      }
    }
    (vm.$children || []).forEach(walk);
  }
  const root = document.querySelector('#app');
  const vm = root && (root.__vue__ || (root.__vue_app__ && root.__vue_app__._instance));
  walk(vm);
  if (!owner) return {err: '没找到持有 hourLimits/dateLimits 的表单组件'};
  const form = owner.$data[key];
  const iso = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
                     String(d.getDate()).padStart(2, '0');
  const toDate = (s) => { const p = s.split('-').map(Number); return new Date(p[0], p[1] - 1, p[2]); };
  const rows = [];
  for (let d = toDate(start); d <= toDate(end); d.setDate(d.getDate() + 1)) {
    rows.push({putDate: iso(d), times: hours.slice()});
  }
  owner.$set(form, 'dateLimits', [{timespan: [start, end]}]);
  owner.$set(form, 'hourLimits', rows);
  if (owner.$forceUpdate) owner.$forceUpdate();
  return {days: rows.length, hoursPerDay: hours.length, want: rows.length * hours.length};
}"""

# 兜底用：清掉已注入的日期/时段，避免"注入一半失败 → 回退点击"时把格子点反
JS_CLEAR_LIMITS = r"""() => {
  const seen = new Set();
  let owner = null, key = null;
  function walk(vm) {
    if (!vm || seen.has(vm) || owner) return;
    seen.add(vm);
    const d = vm.$data || {};
    for (const k of Object.keys(d)) {
      const v = d[k];
      if (v && typeof v === 'object' && !Array.isArray(v) && ('hourLimits' in v || 'dateLimits' in v)) {
        owner = vm; key = k; return;
      }
    }
    (vm.$children || []).forEach(walk);
  }
  const root = document.querySelector('#app');
  const vm = root && (root.__vue__ || (root.__vue_app__ && root.__vue_app__._instance));
  walk(vm);
  if (!owner) return {ok: false};
  owner.$set(owner.$data[key], 'dateLimits', []);
  owner.$set(owner.$data[key], 'hourLimits', []);
  if (owner.$forceUpdate) owner.$forceUpdate();
  return {ok: true};
}"""


def _read_date_inputs(item):
    ins = item.locator(".el-date-editor input")
    vals = []
    for i in range(ins.count()):
        try:
            v = (ins.nth(i).input_value() or "").strip()
        except Exception:
            v = ""
        if v:
            vals.append(v)
    return vals


def set_delivery_date_by_inject(page, form, cfg_date):
    """**传参方式**（2026-09-14 加，用户认可）：直接给表单数据 `dateLimits`/`hourLimits` 赋值，
    不点 464 个格子。字段格式来自后台详情接口 `tTaskInfo/detailPage`：
      dateLimits = [{timespan: ["开始日","结束日"]}]
      hourLimits = [{putDate: "2026-09-14", times: [8..23]}, …每天一条]
    注入后**提交前自检**（日期输入框回读 + 选中格数），不符就抛错——不会带着错日期提交。
    """
    item = form.locator(".el-form-item").filter(has_text="投放日期").first
    expect(item).to_be_visible(timeout=6000)
    rb = item.locator(".el-radio-button").filter(has_text="设置时间").first
    if rb.count():
        rb.click()
    page.wait_for_timeout(400)

    start, end = cfg_date["start"], cfg_date["end"]
    t_start, t_end = int(cfg_date["timeStart"]), int(cfg_date["timeEnd"])
    hours = list(range(t_start, t_end + 1))
    t0 = time.time()
    r = page.evaluate(JS_INJECT_HOURS, [start, end, hours])
    if not r or r.get("err"):
        raise RuntimeError("注入失败：%s" % (r or {}).get("err", r))
    # 等界面把注入的格子刷成 active：**轮询到期望格数**（2026-09-22 优化，原来是死等 1200ms）
    want = r["want"]
    active = -1
    deadline = time.time() + 4
    while time.time() < deadline:
        active = page.evaluate("() => document.querySelectorAll('table.week-time-table td.active').length")
        if active == want:
            break
        page.wait_for_timeout(100)
    vals = _read_date_inputs(item)
    ui.log("  [传参] %s 天 × %s 小时 = %s 格 | 用时 %.2f 秒 | 日期回读=%s | 选中格=%s"
           % (r["days"], r["hoursPerDay"], r["want"], time.time() - t0, vals, active))
    if start not in vals or end not in vals:
        raise RuntimeError("日期自检不符：期望 %s~%s，界面 %s" % (start, end, vals))
    if active != r["want"]:
        raise RuntimeError("时间段自检不符：期望 %s 格，界面 %s 格" % (r["want"], active))


def set_delivery_date_by_click(page, form, cfg_date):
    """**点击兜底方式**：原来的实现——选日期（按月导航）+ 逐格点时间段。注入失败时用它。"""
    item = form.locator(".el-form-item").filter(has_text="投放日期").first
    expect(item).to_be_visible(timeout=6000)
    # 设置时间/今起长投 是 el-radio-button（不是 el-radio）
    rb = item.locator(".el-radio-button").filter(has_text="设置时间").first
    if rb.count():
        rb.click()
    ui.log("  投放日期: 设置时间")
    date = item.locator(".el-date-editor").first
    date.click()
    page.wait_for_timeout(500)

    start = cfg_date["start"]
    end = cfg_date["end"]
    sy, sm, sd = _ymd(start)
    ey, em, ed = _ymd(end)
    # 2026-09-14 修：老实现只按"日号"点，跨月会点到同一个月里（09-14~10-12 被点成 09-12~09-14）。
    # 现在先按月导航（左面板=起始月，右面板=下个月；箭头可翻），再在对应面板里点日号。
    _click_day(_panel_for_month(page, (sy, sm)), sd)
    page.wait_for_timeout(400)
    _click_day(_panel_for_month(page, (ey, em)), ed)
    page.wait_for_timeout(500)
    # 回读输入框自检：必须等于配置里的起止日，不等就报错（别让错日期悄悄提交）
    inputs = item.locator(".el-date-editor input")
    vals = []
    for i in range(inputs.count()):
        try:
            v = (inputs.nth(i).input_value() or "").strip()
        except Exception:
            v = ""
        if v:
            vals.append(v)
    ui.log("  日期区间: %s ~ %s（输入框回读: %s）" % (start, end, vals))
    if start not in vals or end not in vals:
        raise RuntimeError("投放日期回读不符：期望 %s ~ %s，输入框实际 %s" % (start, end, vals))
    # 注意：不要按 Escape（会连整个创建弹窗一起关），日期区间选中后浮层自动收起
    page.wait_for_timeout(600)
    # 时间段表格 <table class="week-time-table time-range">：每日期一行，小时格 data-x=0..23，
    # 点击后加 class active（即选中）。选 08..23 ＝ 8:00-23:00。注意不要点「新增」。
    grid = page.locator("table.week-time-table").first
    if not grid.count():
        grid = item.locator("table").first
    expect(grid).to_be_visible(timeout=8000)
    expect(grid.locator("td[data-x='8']").first).to_be_visible(timeout=6000)  # 选完日期日期行自动出现
    t_start = int(cfg_date["timeStart"])
    t_end = int(cfg_date["timeEnd"])
    clicked = 0
    for h in range(t_start, t_end + 1):
        cells = grid.locator("td[data-x='%d']" % h)
        for i in range(cells.count()):
            cells.nth(i).click()
            clicked += 1
        page.wait_for_timeout(60)
    act = grid.locator("td.active").count()
    n_rows = grid.locator("td[data-x='0']").count()   # 日期行数（每行 1 个 data-x=0 格）
    n_hours = t_end - t_start + 1
    ui.log("  时间段: %02d:00-%02d:00 | %d 个日期行 × %d 小时/天 = %d 格（每格 1 小时）| active=%d"
           % (t_start, t_end + 1, n_rows, n_hours, clicked, act))
    if clicked != n_rows * n_hours:
        ui.log("  ⚠ 时段格数自检不符（预期 %d = %d 行 × %d 小时，实际点 %d）"
               % (n_rows * n_hours, n_rows, n_hours, clicked))


def set_delivery_date(page, form, cfg_date):
    """投放日期 + 时间段：**先试传参注入，失败回退点击**（用户 2026-09-14 定）。

    传参快（约 1.3 秒 vs 点击 26 秒），而且日期是字符串直接给，从根上不会出现"跨月点错月"；
    代价是依赖页面 Vue 内部数据模型（后台改版可能失效）——所以**自检不过就清干净改走点击**，
    功能不会因为页面改版而断。
    """
    try:
        set_delivery_date_by_inject(page, form, cfg_date)
        return "传参"
    except Exception as e:
        ui.log("  ⚠ 传参方式失败（%s）→ 回退点击方式" % str(e).splitlines()[0][:120])
    try:
        page.evaluate(JS_CLEAR_LIMITS)     # 清掉可能注入了一半的状态，避免回退时点反
        page.wait_for_timeout(300)
    except Exception:
        pass
    set_delivery_date_by_click(page, form, cfg_date)
    return "点击"


# ---------- 分发方式（分发名单→用户名单） ----------
def set_distribution(s, form, list_name):
    page = s.page
    item = form.locator(".el-form-item").filter(has_text="分发方式").first
    expect(item).to_be_visible(timeout=6000)
    inp = item.locator("input[placeholder='%s']" % ui.PH_DIST_MODE).first
    if inp.count():
        ui.select(s, inp, "分发名单")
        ui.log("  分发方式: 分发名单")
    # 分发名单选中后出现用户名单选择：**等它真的可见**（而不是死等 600ms）
    list_input = page.locator("input[placeholder='%s']:visible" % ui.PH_DIST_LIST).last
    deadline = time.time() + 8
    while time.time() < deadline and not list_input.count():
        page.wait_for_timeout(150)
    if not list_input.count():
        raise RuntimeError("未找到用户名单下拉（%s）" % list_name)
    try:
        # 名单是这一步的最后动作（曝光上限已经填完了），选完**不收下拉**，直接接着提交
        ui.search_select(s, list_input, list_name, close=False)
    except Exception as e:
        ui.log("  ⚠ 用户名单选择失败:%s（尝试直接输入）" % str(e).splitlines()[0][:90])
        list_input.click()
        list_input.fill(list_name)
        page.wait_for_timeout(400)
        ui.pick_option(s, list_name, poll=3.0)
    ui.log("  用户名单: %s" % list_name)


def close_dialog(page, form):
    x = form.locator(".el-dialog__headerbtn").first
    if x.count():
        try:
            x.click(timeout=1500)
        except Exception:
            ui.close_dropdown(page)      # 用户名单下拉还开着时先收掉再关弹窗
            x.click()
    else:
        c = page.locator("button").filter(has_text="取消").last
        if c.count():
            c.click()
    try:
        expect(form).to_be_hidden(timeout=6000)
    except Exception:
        page.keyboard.press("Escape")


def _task_api_state(page, task_name):
    """接口按完整任务名查一次；滞后时由调用方与页面结果合并。"""
    try:
        body = page.context.request.get(
            "https://csdn-distadmin.csdn.net/admin/tTaskInfo/list",
            params={
                "taskName": task_name,
                "needPage": 1,
                "pageNumber": 1,
                "pageSize": 30,
                "channelType": 0,
            },
            headers={"Accept": "application/json"},
        ).json()
    except Exception as e:
        return es.unknown("工单接口查询失败：%s" % str(e).splitlines()[0][:100])
    for row in ((body.get("data") or {}).get("list") or []):
        if (row.get("taskName") or "").strip() == task_name:
            return es.found(
                row.get("id") or row.get("taskId") or "",
                reason="接口精确名称命中",
                createBy=(row.get("createBy") or "").strip(),
            )
    return es.absent("接口查询成功，无精确任务名")


def task_create_by(page, task_name):
    """从任务列表接口读取完整任务名对应的 createBy；查不到返回 None。"""
    state = _task_api_state(page, task_name)
    return state.metadata.get("createBy") if state.is_found else None


def lookup_task(page, task_name):
    """中断对账合并页面与接口：任一确认存在即 FOUND，两边都确认无才 ABSENT。"""
    try:
        lp = remote_lookup.open(page, LIST_URL, filter_placeholder=PH_ORDER_FILTER)
        ui_state = remote_lookup.exact(lp, task_name, PH_ORDER_FILTER)
    except Exception as e:
        ui_state = es.unknown(str(e).splitlines()[0][:100])
    api_state = _task_api_state(page, task_name)
    if ui_state.is_found:
        return es.found(
            ui_state.object_id or api_state.object_id,
            reason="页面/接口确认存在",
            createBy=api_state.metadata.get("createBy", ""),
        )
    if api_state.is_found:
        return api_state
    if ui_state.is_absent and api_state.is_absent:
        return es.absent("页面和接口都确认不存在")
    return es.unknown("页面=%s；接口=%s" % (ui_state.reason, api_state.reason))


def verify_created(page, task_name, expected_user=""):
    """提交后**回读工单列表**核对任务名是否真的存在（防"假成功"，同 run_audience 的修法）。

    2026-09-14：老实现点完『创建』只等弹窗关闭 + 读提示文字，后台没落库也会记 submitted。
    ⚠ **2026-09-24 修假通过**：老实现只搜「桶名」（如 `火山引擎MediaKit-hang-A类`）——老工单名字里就含
    这个串，新工单**没建成也会打 ✓**（当天真踩到）。现在只认**完整任务名精确行**；
    整页包含或尾号匹配都不能作为成功依据。
    ⚠ 别拿后台 `taskPageList` 接口来核这一步：**它滞后**（新建工单要等生效才进列表），
    用它会得到假阴性 → 下次重跑就建重复工单。界面列表才是这一步的准。
    """
    try:
        lp = remote_lookup.open(page, LIST_URL, filter_placeholder=PH_ORDER_FILTER)
        state = remote_lookup.exact(lp, task_name, PH_ORDER_FILTER)
        if state.is_found:
            ui.log("  回读核对: ✓ 精确命中完整任务名")
            if expected_user:
                actual = task_create_by(page, task_name)
                if actual is None:
                    page.creator_mismatch = True
                    ui.log("  ⚠ 申请人回读未确认（按告警处理）")
                elif actual == expected_user:
                    ui.log("  ✓ 申请人 | %s" % actual)
                else:
                    page.creator_mismatch = True
                    ui.log("  ✗ 申请人 | 期望:%r | 实际:%r" % (expected_user, actual))
        elif state.is_absent:
            ui.log("  回读核对: ✗ 列表中确认没有完整任务名")
        else:
            ui.log("  回读核对: ? 未确认（%s）" % state.reason)
        return state
    except Exception as e:
        reason = str(e).splitlines()[0][:120]
        ui.log("  回读核对异常（记未确认）: %s" % reason)
        return es.unknown(reason)


def run_bucket(s, cfg, aud):
    page = s.page
    t = cfg["taskOrder"]
    # 子业务线来源只有一个：本桶的 subBusinessLine（工单用它填「子业务线/用户组」）
    sub_line = aud["subBusinessLine"]
    aid = aud["id"]
    # 工单任务名：与圈选任务名是同一个字符串（命名规则见 naming.py）；规则算不出来才回退 YAML
    task_name = progress_key(cfg, aud) or t.get("taskName", "")
    # AB 三组资源：**优先用本桶自己的**（audiences[].abGroups，每桶挂自己那 3 份）；
    # 本桶没写才回落到 taskOrder.abGroups（全活动共用一组资源）。
    groups = aud.get("abGroups") or t.get("abGroups") or []
    # AB 测试开关（2026-10-12 加）：缺省 true = 老路（三组资源）；false = **单资源长期单**，
    # 只挂 groups 的第一条、没有流量占比（后台那一步选「AB测试 = 否」）。
    ab_test = t.get("abTest", True)
    # 用户名单名：**正式跑不用写**——默认用本桶的客群名（＝圈选任务名；「一键创建分发名单」的
    # 产物名与它一致）。audiences[].distributionList / taskOrder.distributionList 写了就用写的值
    # （彩排时拿后台现成的测试名单验流程，就靠这个；逐桶写的优先）。
    dist_name = aud.get("distributionList") or t.get("distributionList") or task_name
    steps = []

    ui.log("[%s] %s" % (aid, task_name))
    s.submitted = False      # 重试闸门：点过「提交」之后不许重试（防重复创建）
    name_warning = naming.name_warning(cfg["campaign"], aud)
    if name_warning:
        ui.log("  %s" % name_warning)
    form = open_dialog(page)

    def step(name, fn):
        try:
            fn()
            steps.append((name, "ok"))
        except Exception as e:
            ui.log("  ⚠ [%s] 失败:%s" % (name, str(e).splitlines()[0][:140]))
            steps.append((name, "fail"))
            ui.dismiss_dialogs(page)  # 关掉可能残留的弹窗，避免挡住后续步骤

    # 1) 业务线
    step("业务线", lambda: set_select(s, form, ui.PH_DEPT, t["businessLine"], "业务线"))
    # 2) 子业务线/用户组（label 为空，按 placeholder 定位）
    step("子业务线", lambda: set_select(s, form, ui.PH_SUBLINE, sub_line, "子业务线"))
    # 3) 任务组
    step("任务组", lambda: set_select_search(s, form, ui.PH_TASK_GROUP, t["taskGroup"], "任务组"))
    # 4) 任务名称
    step("任务名称", lambda: set_input(form, ui.PH_TASK_NAME, task_name, "任务名称"))
    # 签呈号选填，不填

    # 5) 渠道（穿梭框）
    step("渠道", lambda: ui.transfer(s, form, t["channel"]))

    # 6) AB 测试（或：单资源）
    if ab_test:
        step("AB测试", lambda: enable_ab_test(form))
        for g in groups:
            label = g.get("label")
            step("AB[%s]" % label,
                 lambda g=g: pick_ab_resource(s, form, g.get("label"), g.get("resource"), g.get("weightPct")))
    else:
        step("AB测试", lambda: disable_ab_test(form))
        one = (groups[0].get("resource") if groups else "")
        step("资源", lambda: set_single_resource(s, form, one))

    # 7) 投放类型 = 流量策略（当前渠道只开放此项；等级规则由后台带默认值）
    step("投放类型",
         lambda: click_radio_in_item(form.locator(".el-form-item").filter(has_text="投放类型").first, "流量策略"))
    # 8) 计费价格
    step("计费价格", lambda: set_input(form, ui.PH_PRICE, t["price"], "计费价格"))
    # 9) 投放日期（设置时间）
    step("投放日期", lambda: set_delivery_date(page, form, t["deliveryDate"]))
    # 10) 曝光上限（**放在用户名单之前**：多选下拉展开会盖住下面这几格，放最后才顺 —— 2026-09-22 用户建议）
    caps = t["exposureCaps"]
    step("每日曝光", lambda: set_input(form, ui.PH_CAP_DAILY, caps["daily"], "每日曝光上限"))
    step("每周曝光", lambda: set_input(form, ui.PH_CAP_WEEKLY, caps["weekly"], "每周曝光"))
    step("总曝光", lambda: set_input(form, ui.PH_CAP_TOTAL, caps["total"], "总曝光上限"))
    # 11) 分发方式（分发名单→用户名单）—— **最后一步**：选完名单直接提交，不用等它收起来
    step("分发方式", lambda: set_distribution(s, form, dist_name))

    # 截图（仅彩排；正式 --submit 由 csdn_ui 决定不拍）
    ui.shot(s, "taskorder_%s.png" % aid)
    ui.log("  [%s] 填表+校验完成。" % aid)
    ui.log("  步骤结果:" + " | ".join("%s=%s" % (n, r) for n, r in steps))

    if s.dry_run:
        close_dialog(page, form)
        status = bucket_runner.steps_status(steps)
        if status == bucket_runner.WARN:
            ui.log("  ⚠ 上面的 ✗ 步骤没全过 → 记 warn（下次会重跑，结尾 RESULT: HAS_WARN）")
        ui.log("  彩排：未提交，已关闭（未创建任务工单）")
        return status

    # ⛔ 提交前闸门（2026-09-22 加）：**有任何一步没通过就不提交**。
    # 原来只把步骤结果写进 steps，正式提交照样往下点「提交」——某步失败（如残留浮层挡住点击超时）就会
    # 建出一条**缺字段的工单**，而事后的 verify_created() 只查"工单名在不在列表里"，查不出字段缺失。
    if bucket_runner.steps_status(steps) == bucket_runner.WARN:
        bad = "、".join(n for n, r in steps if r != "ok")
        ui.log("  !! 有步骤未通过（%s）→ **不提交**，关闭表单后整桶重试" % bad)
        close_dialog(page, form)
        raise bucket_runner.pre_submit_error(steps)

    # 2026-09-14 真机勘察：表单底部的主按钮文案是「提交」（不是「创建」；「创建」是列表页开弹窗那个）
    btn = form.locator("button.el-button--primary:visible").filter(has_text="提交").last
    if not btn.count():
        ui.log("  !! 未找到『提交』按钮 → 记 warn（下次重跑，别当成功）")
        return "warn"
    try:
        s.submitted = True   # 就这一下之后失败不能再重试
        btn.click(timeout=1500)
    except Exception:
        ui.close_dropdown(page)     # 用户名单下拉还开着、挡住按钮时先收起再点
        btn.click()
    try:
        expect(form).to_be_hidden(timeout=15000)
    except Exception:
        errs = form.locator(".el-form-item__error").all_inner_texts()
        ui.log("  ✗ 提交失败，表单错误:%s" % errs)
        return False
    msgs = page.locator(".el-message").all_inner_texts()
    ui.log("  已提交任务工单 | 提示:%s" % msgs)
    # 必须回读后台确认（同圈选步骤 2026-09-14 的修法），别把"点了创建"当"建成了"
    state = verify_created(page, task_name,
                           expected_user=getattr(s, "login_user", ""))
    if not state.is_found:
        ui.log("  ⚠ 提交后回读未确认该工单 → 下次先远端对账，不盲重建")
        return bucket_runner.NEEDS_RECONCILE
    if getattr(page, "creator_mismatch", False):
        s.creator_mismatch = True
    return "submitted"   # 真创建了 → 账本记 submitted，再跑时永远跳过


def main():
    ap = cli.parser("真正点『创建』建任务工单（默认彩排）", only=True)
    ap.add_argument("--start", default="", help="覆盖 config 的投放起始日 YYYY-MM-DD（同一批的桶隔天补建时用）")
    ap.add_argument("--end", default="", help="覆盖 config 的投放结束日 YYYY-MM-DD")
    ap.add_argument("--v2-db", default=workspace_repo.V2_DB, help="数据库 v2 路径")
    args = ap.parse_args()

    ctx = cli.context(args, shots="taskorder_shots", progress="taskorder_progress.json")
    t = ctx.cfg["taskOrder"]
    if args.start or args.end:      # 用户 2026-09-30 定：什么时候发任务，起投日就是哪天（= 复盘当天）
        dd = t.setdefault("deliveryDate", {})
        if args.start:
            dd["start"] = args.start
        if args.end:
            dd["end"] = args.end
        ui.log("投放日期覆盖：%s ~ %s（--start/--end；YAML 里那份不动，是上一批桶的真实参数）"
               % (dd.get("start"), dd.get("end")))

    ui.log("任务组:%s | 渠道:%s | 桶数:%d | 模式:%s"
           % (t["taskGroup"], t["channel"], len(ctx.auds),
              "SUBMIT" if args.submit else "彩排"))
    if ctx.only:
        ui.log("--only %s → 只建 %d 个桶（%s）" % (",".join(ctx.only), len(ctx.auds),
                                              ", ".join(str(a["id"]) for a in ctx.auds)))

    try:
        with ctx.session(args) as s:
            ui.goto(s.page, LIST_URL)
            s.login_user = ui.require_login_identity(s.page)

            ctx.report = bucket_runner.run_buckets(
                ctx.auds,
                lambda aud: run_bucket(s, ctx.cfg, aud),
                key_of=lambda aud: progress_key(ctx.cfg, aud),
                describe=lambda aud: "[%s] %s" % (aud["id"], t["taskGroup"]),
                progress=ctx.progress,
                reconcile=lambda aud: lookup_task(
                    s.page, progress_key(ctx.cfg, aud)),
                payload_of=lambda aud: payload_for(ctx.cfg, aud),
                on_item_fail=lambda aud: ui.dismiss_dialogs(s.page),  # 关残留弹窗，别影响下一桶
                on_retry=lambda aud, e: ui.retry_reset(s, e, LIST_URL),
                retry=1,
                should_retry=lambda aud, e: not getattr(s, "submitted", False),
                log=ui.log,
                dry_run=not args.submit,
                unit="桶", rest="桶")
            if getattr(s, "creator_mismatch", False):
                ctx.report.warned += 1
        if args.v2_db:
            submitted = [
                aud for aud in ctx.auds
                if ctx.progress.get(progress_key(ctx.cfg, aud)) == bucket_runner.SUBMITTED
            ]
            if submitted:
                started_on = args.start or t["deliveryDate"]["start"]
                workspace_sync.sync_config_batch(
                    args.v2_db, ctx.cfg, submitted, started_on,
                    change_reason=os.path.basename(args.config),
                    status="running",
                )
    except Exception as e:
        cli.fatal(ctx, e)
    cli.finish(ctx.report)


if __name__ == "__main__":
    main()
