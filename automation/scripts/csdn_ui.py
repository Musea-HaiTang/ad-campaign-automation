# -*- coding: utf-8 -*-
"""CSDN 后台 · 页面驱动共用层。

四个 run_* 脚本（任务组 / 资源 / 圈选 / 工单）共享的**「跟后台页面打交道」**的知识
都在这里：会话（浏览器 + 登录态）、下拉选择、穿梭框、弹窗清场、字段回读、截图。

这里**只放与「这次要办什么」无关的动作**；办事顺序（先选业务线 → 再选渠道 → …）
留在各脚本里。

浏览器：所有脚本共用**一只公共浏览器**（`browser_broker`，CDP 挂上去、各开各的标签页），
看板取数 / 建任务 / 重新登录互不挤（2026-10-16 用户定）。

用法：
    with csdn_ui.session(headed=args.headed, dry_run=not args.submit,
                         shot_dir=SHOT_DIR) as s:
        csdn_ui.select(s, s.page.locator("input[placeholder='请选择任务组']").first,
                       "华为云码道hang")
        csdn_ui.shot(s, "taskgroup_filled.png")

彩排 / 正式的规矩也在这里：`dry_run=True` 才截图（截图是测试专用），
动作本身不会因为你传错而误点「确定」——点不点由脚本的业务步骤决定。
"""
import datetime
import os
import sys
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import browser_broker as broker  # noqa: E402
import runtime_state  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

# 写后台的锁：真办事（--submit）时同一时刻只允许一个脚本（见 _write_lock）
WRITE_LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_tmp", "write.lock")
DEFAULT_TIMEOUT_MS = 8000
BROWSER_PROBE_TIMEOUT_MS = 4000
POLL_SECONDS = 6.0
_RUN_LOG_FH = None

# ---------- 术语表：后台表单上的中文提示词（按 placeholder 定位比 CSS 稳） ----------
PH_DEPT = "请选择事业部"
PH_SUBLINE = "请选择子业务线/用户组"
PH_TASK_GROUP = "请选择任务组"
PH_TASKGROUP_NAME = "请输入任务组名称"
PH_SIGN = "请输入签呈号"
PH_TASK_NAME = "请输入任务名称"
PH_RESOURCE_NAME = "请输入资源名称"
PH_RESOURCE_SEARCH = "请输入资源名称搜索"
PH_AD_TITLE = "解析自动生成标题"
PH_AD_SUMMARY = "解析自动生成描述"
PH_AD_USERNAME = "解析自动生成用户名"
PH_AD_LINK = "请输入URL解析"
PH_KEYWORDS = "请输入关键词,按（中英文）逗号分割"
PH_USER_NAME = "请输入用户名称"
PH_TRANSFER_SEARCH = "请输入搜索内容"
PH_WEIGHT = "请输入流量占比"
PH_DIST_MODE = "请选择分发方式"
PH_DIST_LIST = "请输入名单名称，查询用户名单"
PH_PRICE = "请输入计费价格"
PH_CAP_DAILY = "请输入每日曝光上限"
PH_CAP_WEEKLY = "请输入每周曝光"
PH_CAP_TOTAL = "请输入总曝光上限"

# ---------- 后台通用选择器（Element UI） ----------
SEL_DROPDOWN = ".el-select-dropdown:visible"
SEL_DROPDOWN_ITEM = ".el-select-dropdown__item"
SEL_DIALOG = ".el-dialog:visible"
SEL_MSG_BOX = ".el-message-box:visible"     # 确认框（Element UI 的 MessageBox，不是 el-dialog）
SEL_DIALOG_CLOSE = ".el-dialog__headerbtn"


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    if _RUN_LOG_FH:
        try:
            _RUN_LOG_FH.write(line + "\n")
            _RUN_LOG_FH.flush()
        except OSError:
            pass


@contextmanager
def run_log(shot_dir, script=""):
    """本次执行的 stdout 同步落一份日志，返回日志路径。

    日志放 `{活动}/日志/runs/`；没有活动目录时放 `automation/_tmp/runs/`。
    页面卡死、自动恢复、RESULT 都在同一条时间线上，后续排查不用再靠人工回忆。
    """
    global _RUN_LOG_FH
    base = os.path.dirname(os.path.abspath(shot_dir)) if shot_dir else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "_tmp")
    root = os.path.join(base, "runs")
    ensure_dir(root)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    name = (script or os.path.splitext(os.path.basename(sys.argv[0]))[0] or "run").strip()
    name = name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    path = os.path.join(root, "%s-%s-%d.log" % (stamp, name, os.getpid()))
    _RUN_LOG_FH = open(path, "a", encoding="utf-8")
    try:
        log("运行日志:", path)
        yield path
    finally:
        try:
            _RUN_LOG_FH.close()
        finally:
            _RUN_LOG_FH = None


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


@dataclass
class Session:
    """一次运行的手柄：页面 + 这次是彩排还是真办（+ 截图存哪）。"""

    page: object
    dry_run: bool = True
    shot_dir: str = ""
    playwright: object = None
    headed: bool = False


class BrowserUnresponsive(RuntimeError):
    """CDP 端口通，但页面层已经不能执行新动作。"""


def is_browser_failure(exc):
    """异常是否属于「浏览器/导航失活」，而不是后台某个元素没等到。"""
    if isinstance(exc, BrowserUnresponsive):
        return True
    text = str(exc).lower()
    markers = (
        "page.goto: timeout",
        "page.set_content: timeout",
        "target page, context or browser has been closed",
        "browser has disconnected",
        "browser has been closed",
        "websocket error",
        "connection closed",
        "connect econnrefused",
    )
    return any(marker in text for marker in markers)


def _open_checked_page(pw, headed=False):
    """新开一页并做页面级健康探针；CDP 能连不等于渲染进程能干活。"""
    broker.ensure("headed" if headed else "headless")
    page = None
    try:
        ctx = broker.connect(pw)
        page = ctx.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        page.set_content("<html><title>broker-ok</title></html>",
                         timeout=BROWSER_PROBE_TIMEOUT_MS)
        return page
    except Exception as e:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        raise BrowserUnresponsive(
            "公共浏览器页面无响应：%s" % str(e).strip().splitlines()[0][:160]) from e


def open_healthy_page(pw, headed=False):
    """打开健康页；页面层失活时重启公共浏览器，只重试一次。"""
    try:
        return _open_checked_page(pw, headed=headed)
    except BrowserUnresponsive as e:
        log("⚠ %s" % str(e).splitlines()[0])
        log("公共浏览器页面层失活 → 重启一次")
        broker.stop()
        return _open_checked_page(pw, headed=headed)


def recover(s):
    """当前页或浏览器失去响应后重启公共浏览器，再换一张健康页。

    目标页面导航已经超时的情况下，空白页探针通常仍能通过；只换页会继续撞同一段
    卡死的渲染进程，因此浏览器失活的恢复动作直接重启 broker，只重试一次。
    """
    old = s.page
    try:
        old.close()
    except Exception:
        pass
    log("公共浏览器 → 重启一次")
    broker.stop()
    s.page = open_healthy_page(s.playwright, headed=s.headed)
    return s.page


def retry_reset(s, exc, url):
    """逐项重试前重置页面：浏览器失活就恢复，再回列表页。"""
    if is_browser_failure(exc):
        log("↻ 浏览器失活 → 恢复公共浏览器后重试")
        recover(s)
    goto(s.page, url)


def retry_browser_action(s, action, what="页面动作"):
    """循环外动作：只对浏览器失活重试一次；后台元素错误原样抛出。"""
    try:
        return action()
    except Exception as e:
        if not is_browser_failure(e):
            raise
        log("⚠ %s遇到浏览器失活：%s" % (what, str(e).splitlines()[0][:160]))
        recover(s)
        return action()


@contextmanager
def _write_lock():
    """真办事时的一把锁：同一时刻只允许一个脚本往后台建东西。

    两个脚本一起点后台、"到底谁把这条建重了"根本查不出来——直接拦下来说清楚。
    使用当前平台的进程锁：进程一死锁自动放掉，不会留下"过期锁"要人手工清。
    """
    path = os.path.abspath(WRITE_LOCK)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = runtime_state.acquire_file_lock(path)
    if handle is None:
        raise RuntimeError("已有另一个脚本在往后台建东西——同一时刻只允许一个（等它跑完再跑）")
    try:
        yield
    finally:
        runtime_state.release_file_lock(handle)


@contextmanager
def session(*, headed=False, dry_run=True, shot_dir=""):
    """挂到公共浏览器上开**自己的标签页**；退出时只关这个标签页。

    公共浏览器（`browser_broker`）是一只独立进程：看板取数、建任务、wait_login 同时挂上去、
    各开各的标签页——不会再出现"开建任务的浏览器就把看板挤掉"（2026-10-16 用户定）。
    真办事（`dry_run=False`，即 `--submit`）时再拿一把写锁，同一时刻只允许一个脚本动后台。
    """
    with run_log(shot_dir):
        with sync_playwright() as p:
            page = open_healthy_page(p, headed=headed)
            s = Session(page, dry_run, shot_dir, playwright=p, headed=headed)
            try:
                with (nullcontext() if dry_run else _write_lock()):
                    yield s
            finally:
                # 只关自己这一页；ctx 是**公共的**，绝不能 ctx.close()（那是把整只浏览器关了）
                try:
                    s.page.close()
                except Exception as e:
                    log("page.close:", e)


LOGIN_IDENTITY_JS = r"""
() => {
  const cookieNames = document.cookie.split(";").map(x => x.trim().split("=")[0]);
  let vue = document.querySelector("#app") && document.querySelector("#app").__vue__;
  while (vue && !(vue.$store && vue.$store.getters)) vue = vue.$parent;
  return {
    userName: String((vue && vue.$store && vue.$store.getters.userName) || "").trim(),
    hasToken: cookieNames.includes("MPToken"),
    hasUser: cookieNames.includes("MPUser"),
    url: location.href,
  };
}
"""


def login_identity(page):
    """只读读取当前后台登录身份；不返回 token / cookie 值。"""
    try:
        data = page.evaluate(LOGIN_IDENTITY_JS)
    except Exception:
        return {"userName": "", "hasToken": False, "hasUser": False, "url": ""}
    return data if isinstance(data, dict) else {
        "userName": "", "hasToken": False, "hasUser": False, "url": ""
    }


def require_login_identity(page, timeout=15.0):
    """创建资源/工单前的硬闸：必须拿到非空用户名和 MPToken/MPUser。"""
    deadline = time.time() + timeout
    info = login_identity(page)
    while time.time() < deadline:
        if info["userName"] and info["hasToken"] and info["hasUser"]:
            log("登录身份 OK | 当前用户:%s" % info["userName"])
            return info["userName"]
        page.wait_for_timeout(250)
        info = login_identity(page)
    raise RuntimeError(
        "登录身份不完整：MPToken=%s | MPUser=%s | userName=%r。"
        "请先运行 automation/scripts/wait_login.py 重新登录，"
        "否则后台会把申请人写成空值。"
        % (info["hasToken"], info["hasUser"], info["userName"])
    )


def goto(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=25000)


def dialog(page, text=None):
    """取最上层的可见弹窗；给了 text 就按标题过滤。"""
    dialogs = page.locator(SEL_DIALOG)
    return dialogs.filter(has_text=text).last if text else dialogs.last


def shot(s, name):
    """留档截图。**只在彩排时拍**；正式跑不拍（快，也不往本地留后台截图）。"""
    if not s.dry_run:
        return None
    try:
        ensure_dir(s.shot_dir)
        path = os.path.join(s.shot_dir, name)
        s.page.screenshot(path=path, full_page=False)
        log("  📸", path)
        return path
    except Exception as e:
        log("  截图失败:%s" % str(e).splitlines()[0][:90])
        return None


def read_field(scope, placeholder):
    """回读输入框/文本域里现在的值；找不到就返回空串。"""
    for tag in ("input", "textarea"):
        loc = scope.locator("%s[placeholder='%s']" % (tag, placeholder)).first
        if loc.count():
            return loc.input_value()
    return ""


def wait_for(page, condition, timeout=8.0, interval=0.15, what=""):
    """轮询等一个条件成立：成立返回 True，超时返回 False（**不抛错**）。

    2026-09-22 起用它取代各脚本里的「固定 `wait_for_timeout`」——页面早就好了就不用干等，
    页面真的慢就等到上限为止（比固定值既快又稳，工单那次已验证这套有效）。
    `condition` 是**无参可调用**，里面自己判断（通常配合下面的 `is_visible` / `visible_input`）；
    条件里读页面时可能抛（元素闪断/重渲染），一律当作"还没好"继续等。
    超时会打一行日志写清楚在等什么，方便事后从日志定位是哪一步慢。
    """
    deadline = time.time() + timeout
    while True:
        try:
            if condition():
                return True
        except Exception:
            pass
        if time.time() >= deadline:
            if what:
                log("  ⏱ 等「%s」超过 %.1f 秒（继续走，由后面的显式校验兜底）" % (what, timeout))
            return False
        page.wait_for_timeout(int(interval * 1000))


def is_visible(loc):
    """这个 locator 可见吗（0 个匹配也算 False，不抛错）。传 `.first` 这类单元素定位。"""
    try:
        return loc.count() > 0 and loc.is_visible()
    except Exception:
        return False


def visible_input(page, placeholder):
    """取页面上**可见**那一份输入框（后台常有隐藏副本：固定列/克隆）。找不到返回 None。"""
    cands = page.locator("input[placeholder='%s']" % placeholder)
    for i in range(min(cands.count(), 8)):
        try:
            el = cands.nth(i)
            if el.is_visible():
                return el
        except Exception:
            continue
    return None


def fill_visible(page, placeholder, value):
    """往可见那份输入框填值；找不到返回 False（不抛错，由调用点决定怎么报）。"""
    el = visible_input(page, placeholder)
    if el is None:
        return False
    el.fill(value)
    return True


def table_has_rows(page, scope=""):
    """（scope 容器里的）表格有没有数据行 —— 读正文前用它兜一下。

    2026-09-22 踩到：**筛选框比表格行先渲染**，把"等 1500ms"换成"等筛选框出现"之后，
    `run_distribution --verify` 会读到**空表**并误报「名单未建」（实测 5/5 全误报）。
    ⚠ 这个后台把**所有页签都留在 DOM 里**（隐藏面板里的表也有行）：不传 scope 时
    `.el-table__body-wrapper tbody tr` 会被**别的页签的表**满足，等于没等。传
    `scope=".el-tab-pane:visible"` 才是"当前这张表真的出数据了"。
    """
    pre = (scope + " ") if scope else ""
    return page.locator("%s.el-table__body-wrapper tbody tr" % pre).count() > 0


def click_query(page, floor_ms=1200, timeout=8.0, scope=""):
    """点「查询」→ 等这次查询落地（**只在能证明后台已经答完时**提前返回）。

    2026-09-22：各脚本原来都是固定死等（活动体检 2200ms / 圈选 1200ms）。现在看 Element UI 的
    加载遮罩：这次查询**转圈了**（`.el-loading-mask` 出现 → 消失）就等它消失再走；
    **没转圈**就按原来的固定底 `floor_ms` 收尾，最多等到 `timeout`。
    ⛔ 不做"乐观提前返回"——宁可慢一点，也不能读到上一次查询的旧数据去判达标（2026-09-21 踩过）。

    2026-09-23：只认**看得见**的遮罩（`:visible`）。真机实测（`_tmp/probe_mask.py`）：加载完之后
    遮罩元素**留在 DOM 里、只是 `display:none`**——原来数元素个数（`.count()`）会永远判成"还在转圈"，
    于是每个查询白等 3 秒、还误报"这次数可能是旧的"；更糟的是那个 3 秒兜底几乎贴着真实耗时
    （工单页实测要 2.5 秒），后台真慢一点就会读到旧数。现在按可见性判：圈选页 0.5 秒答完就走，
    工单页等它 2.5 秒真的答完；只有遮罩**一直看得见**时才等到 `timeout` 并说清"数可能是旧的"。
    `scope` 传容器选择器（例：圈选页签 `#pane-blogKeywordManage`），不传就在整页找「查询」按钮。
    """
    pre = (scope + " ") if scope else ""
    page.locator("%sbutton:visible" % pre).filter(has_text="查询").first.click()
    t0 = time.time()
    floor = floor_ms / 1000.0
    saw_mask = False
    while True:
        if page.locator("%s.el-loading-mask:visible" % pre).count():
            saw_mask = True
        elif saw_mask:
            page.wait_for_timeout(150)     # 遮罩没了再垫一下，等表格重绘完
            return True
        elif time.time() >= t0 + floor:
            return True                    # 没转圈（或遮罩来得比底还晚）：按原来的固定底收尾
        if time.time() >= t0 + timeout:
            # 遮罩**一直看得见**（后台真慢/卡住）→ 收手，并把"数可能是旧的"说清楚
            log("  ⏱ 查询等了 %.1f 秒还没落地（加载遮罩一直看得见）→ 按超时收尾，这次数可能是旧的"
                % (time.time() - t0))
            return False
        page.wait_for_timeout(100)


def dismiss_dialogs(page):
    """关掉页面上所有可见弹窗，避免残留遮罩挡住下一步（治连锁失败）。"""
    # 2026-09-22：没有任何可见弹窗时直接返回 —— 原来也要按一次 Escape + 等 400ms
    # （每个桶都调一次，7 桶白等 ~3 秒；按 Escape 还可能误关别的浮层）。
    # ⚠ 确认框（message-box）也算"有弹窗"：老行为是会给它按一次 Escape 的，别漏掉。
    if not page.locator("%s, %s" % (SEL_DIALOG, SEL_MSG_BOX)).count():
        return
    for _ in range(4):
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        if page.locator(SEL_DIALOG).count() == 0:
            return
    for _ in range(4):
        dlg = page.locator(SEL_DIALOG).last
        if dlg.count() == 0:
            break
        x = dlg.locator(SEL_DIALOG_CLOSE).last
        if x.count():
            try:
                x.click(force=True)
            except Exception:
                try:
                    x.click()
                except Exception:
                    page.keyboard.press("Escape")
        page.wait_for_timeout(400)


def _wait_dropdown_closed(page):
    expect(page.locator(SEL_DROPDOWN)).to_have_count(0, timeout=6000)


def close_dropdown(page):
    """把还开着的下拉收起来 —— **多选下拉（如「分发名单」）选完不会自动收**。

    2026-09-22 优化：以前靠 `_wait_dropdown_closed` 干等 6 秒超时（条件永远不成立）。
    实测（`_tmp/probe_close_dropdown.py`）三种点法：**点弹窗正文左上角空白 ✓ 收起**、
    点表单 label ✓ 收起、**点标题栏点不动**（被浮层盖住会超时）、**按 Tab 反而又打开**。
    所以这里点正文空白，点不到就原样返回，交给调用点后面的显式等待兜底。
    """
    try:
        if not page.locator(SEL_DROPDOWN).count():
            return
        body = page.locator(".el-dialog:visible .el-dialog__body").last
        if body.count():
            body.click(position={"x": 8, "y": 8}, timeout=3000)
            return
        label = page.locator(".el-form-item__label:visible").first
        if label.count():
            label.click(timeout=3000)
    except Exception:
        pass


def _option_snapshot(page):
    """一次读回当前可见下拉的 (items, [每项文本])。

    **必须批量读**：逐项 `inner_text()` 会吃满 8 秒默认超时（下拉是边加载边重排的，
    读取时元素不稳定），30 项能耗掉一分钟以上，而轮询的截止时间是扫完才检查的，根本拦不住。
    文本优先取 `.opt-name`（Element UI 把名字放这里），数量对不上就用整项文本。
    """
    items = page.locator(SEL_DROPDOWN).locator(SEL_DROPDOWN_ITEM)
    n = items.count()
    if not n:
        return items, []
    try:
        texts = items.locator(".opt-name").all_inner_texts()
    except Exception:
        texts = []
    if len(texts) != n:
        try:
            texts = items.all_inner_texts()
        except Exception:
            texts = []
    return items, [t.strip() for t in texts]


def dropdown_options(page):
    """读当前可见下拉里的选项文本（跑前校验、报错提示用）。"""
    _, texts = _option_snapshot(page)
    return [t for t in texts if t]


def _pick_option(page, value, poll, interval=0.3):
    """在当前可见的下拉里点中 value 那一项。

    选项文本可能带系统加的后缀（例：用户名单显示成「鸿蒙稿事节征文短信（万粉以上） 用户名」，
    而配置里只存真名），所以**只认两种命中**：① 与 value 完全相等；② `value + 分隔符 + 类型标签`
    （分隔符 = 空格 / 全角半角括号 / 制表符）。
    ⛔ **不做纯前缀匹配**（2026-09-22 五桶对比批彩排踩到）：首屏拿到的是**还没被关键词过滤的全量列表**，
    纯前缀会立刻把同前缀的另一项抢走——`…A类 · AI 编程 / Agent 工具` 命中了 `…A类 · AI 编程 / Agent 工具-4`
    （排在被过滤后的正主前面），工单就挂错名单了。改成「等过滤后的正确项出现」，
    poll 秒内等不到就抛错（消息里带看到的选项），**宁可报错也不选错**。
    选项是异步加载的，所以**轮询等它出现**；实在没有就报错，并把看到的选项列出来。
    """
    deadline = time.time() + poll
    seen = []
    while True:
        items, texts = _option_snapshot(page)
        pairs = [(items.nth(i), t) for i, t in enumerate(texts) if t]
        seen = [txt for _, txt in pairs]
        # 完全相等优先
        for it, txt in pairs:
            if txt == value:
                it.click()
                return True
        # 其次：真名 + 分隔符（「… 博客ID」/「…（用户名）」这种展示后缀）
        for it, txt in pairs:
            if txt.startswith(value) and txt[len(value):len(value) + 1] in (" ", "（", "(", "\t"):
                it.click()
                return True
        if time.time() >= deadline:
            raise RuntimeError("下拉无此选项: %s | 可见选项(%d): %s" % (value, len(seen), seen[:20]))
        page.wait_for_timeout(int(interval * 1000))


def _type_into(page, select_input, value):
    try:
        page.keyboard.insert_text(value)  # 输入到已聚焦的检索框，中文也行
    except Exception:
        try:
            select_input.fill(value)
        except Exception:
            select_input.press_sequentially(value)


def _clear_input(page):
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.wait_for_timeout(300)


def wait_input_ready(page, select_input, timeout=0.8, settle=0.15):
    """等 el-select 的检索框**真的拿到焦点**再输入。

    2026-09-22：原来这里是一个 250 ms 死等——不输入的话，紧接着插入的关键词可能不触发后台过滤，
    选值只能以空轮询收场。改成条件：`document.activeElement === 那个 input`；实测这个条件**常常判不成立**
    （Element UI 把焦点放在包裹层上），所以超时上限压到 0.8 秒、等不到就垫一个短 settle 再继续。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if page.evaluate("e => document.activeElement === e", select_input.element_handle()):
                return True
        except Exception:
            pass
        page.wait_for_timeout(50)
    page.wait_for_timeout(int(settle * 1000))
    return False


def _open_dropdown(page, select_input):
    """点开一个 el-select 的下拉。

    readonly 的输入框有时被同容器里的检索框盖住（Element UI 的 `.el-select__tags`），
    普通点击会被它拦下（Playwright 报 "... intercepts pointer events"）；这时改点外层容器。
    先等它出现（该等多久等多久），再给第一次点击设短超时（免得被拦时白等 8 秒）。
    2026-09-22：首次点击超时 2000 → **300 ms**——用户名单那个 readonly 输入框必然被 `.el-select__tags`
    盖住（每次都点不动），2 秒是纯浪费；真点不动就立刻改点包裹层。
    """
    select_input.wait_for(state="visible", timeout=8000)
    first_err = None
    try:
        select_input.click(timeout=300)
        return
    except Exception as e:
        first_err = e
    wrap = select_input.locator("xpath=ancestor::div[contains(@class,'el-select')]").first
    if not wrap.count():
        wrap = select_input.locator("xpath=ancestor::div[contains(@class,'el-input')]").first
    if not wrap.count():
        raise first_err
    wrap.click(timeout=8000)


def select(s, select_input, value):
    """一次 el-select：点开 → 选 value → 等浮层收起。"""
    page = s.page
    _open_dropdown(page, select_input)
    page.wait_for_selector(SEL_DROPDOWN, timeout=8000)
    page.wait_for_timeout(200)
    _pick_option(page, value, POLL_SECONDS)
    # 2026-09-22 试过"不等它收"（省 ~0.3 s/次）：5 桶里出现一次「子业务线」点击被残留浮层挡住而超时（8 s），
    # 所以这 0.3 s **是安全垫不是浪费** —— 留着。
    _wait_dropdown_closed(page)


def search_select(s, select_input, value, poll=POLL_SECONDS, close=True):
    """可搜索的 el-select：点开 → 输入过滤 → 选 value（选项极多时用）。

    注意：选项文本可能带后缀（例：用户名单显示成「华为码道分发名单社区运营分组_17 用户名」，
    但真名只有前半截），而后台检索**只认真名**。所以先拿原值搜，搜不到就去掉最后一个词再搜。
    `close=False`：选完**不收下拉**（用户名单是多选、收一次要 0.3~0.8 s）——调用方把它放在最后一步、
    选完直接提交时用；这时由提交/取消那一下负责（点不动就先 `close_dropdown()` 再点）。
    """
    page = s.page
    _open_dropdown(page, select_input)
    page.wait_for_selector(SEL_DROPDOWN, timeout=8000)
    wait_input_ready(page, select_input)   # 原来这里死等 250ms；改成"等检索框拿到焦点"

    queries = [value]
    head = value.rsplit(" ", 1)[0].strip()  # 去掉「用户名」这类展示后缀
    if head and head != value:
        queries.append(head)

    last_err = None
    for query in queries:
        _type_into(page, select_input, query)
        try:
            # 原来这里死等 400ms；改成直接**轮询目标项**（100ms 步长，比 300ms 更早发现）
            _pick_option(page, value, poll, interval=0.1)
            break
        except RuntimeError as e:
            last_err = e
            if query != queries[-1]:
                log("  ⚠ 按 %r 搜不到，去掉最后一个词改搜 %r…" % (query, queries[-1]))
                _clear_input(page)
    else:
        raise last_err
    if close:
        close_dropdown(page)      # 多选下拉不自动收 → 点弹窗正文空白处（别干等 6 秒超时）
        try:
            _wait_dropdown_closed(page)
        except Exception:
            pass


def pick_option(s, value, poll=POLL_SECONDS, interval=0.3):
    """在**当前已打开**的下拉里选一项（找不到抛错，消息里带看到的选项）。"""
    _pick_option(s.page, value, poll, interval=interval)


def transfer(s, scope, value):
    """穿梭框：左侧搜索 → 勾选 → 移到右侧。scope 是包含穿梭框的容器。"""
    page = s.page
    trans = scope.locator(".el-transfer").first
    if not trans.count():
        trans = scope
    expect(trans).to_be_visible(timeout=8000)

    left = trans.locator(".el-transfer-panel").first
    left.locator("input[placeholder='%s']" % PH_TRANSFER_SEARCH).fill(value)
    cb = left.locator("label.el-checkbox").filter(has_text=value).first
    expect(cb).to_be_visible(timeout=8000)
    cb.locator(".el-checkbox__inner").click()
    expect(cb.locator("input[type='checkbox']")).to_be_checked(timeout=6000)

    # 移到右侧：优先找『>』那个按钮，再退而求其次；点不动就重试 3 轮
    moved = False
    for _ in range(3):
        btns = trans.locator(".el-transfer__buttons button")
        n = btns.count()
        order = [i for i in range(n) if btns.nth(i).locator(".el-icon-arrow-right").count()]
        order += [i for i in range(n) if i not in order]
        for i in order:
            b = btns.nth(i)
            if b.is_enabled():
                b.click()
                moved = True
                break
        if moved:
            break
        page.wait_for_timeout(400)
    if not moved:
        raise RuntimeError("穿梭框没有可用的『>』移动按钮: %s" % value)

    right = trans.locator(".el-transfer-panel").nth(1)
    try:
        expect(right.locator(".el-checkbox__label").filter(has_text=value).first).to_be_visible(
            timeout=6000
        )
    except Exception:
        log("  ⚠ 右侧未确认到:%s（可能已内联）" % value)
