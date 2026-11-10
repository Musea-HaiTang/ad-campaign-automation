# -*- coding: utf-8 -*-
"""公共浏览器（broker）：一只独立 Edge/Chrome 挂在登录 profile 上，谁要用就挂上去。

为什么有它（用户 2026-10-16 定）
------------------------------
一个 `.browser-profile` **同时只能被一个浏览器进程用**（Chromium 的独占锁）。以前每个程序
（建任务 `run_*`、取数 `fetch_perf`、看板 `web/app.py`、`wait_login`、`record_*`）各自
`launch_persistent_context` 起一只，谁先起谁占锁 ——→「开建任务的浏览器，看板就把取数全失败」，
只能手工"停看板 → 跑脚本 → 起看板"。

现在改成：**只有这一只浏览器进程**，由本模块起（不属于任何脚本 / 服务），其余程序一律用 CDP
（`connect_over_cdp`）挂上去、各开各的标签页。锁的唯一持有者变成这只浏览器本身——看板重启、
建任务脚本跑完，都不会再动它；公共浏览器只在真的挂了、或要切窗口模式时才重启。

谁在什么时候读：改「谁能碰后台浏览器」这件事的人；日常用不着看——`csdn_ui` / `fetch_perf` /
`web/app.py` 已经接好了。

用法（程序里）
-------------
    import browser_broker as broker
    broker.ensure("headless")                 # 没起就起、已经起着就复用
    with sync_playwright() as p:
        ctx = broker.connect(p)               # 公共浏览器的主 context
        page = ctx.new_page()                 # 每次用都开自己的标签页
        ...
        page.close()                          # 只关自己的标签页；别关 ctx / browser

命令行
------
    python browser_broker.py --status    看实际端口、模式、浏览器和页面数
    python browser_broker.py --headless  起（或复用）无窗口的
    python browser_broker.py --headed    起成有窗口的（要把无窗口切成有窗口会重启一次）
    python browser_broker.py --stop      关掉（下次谁要用会自动再起）
    python browser_broker.py --browser chrome --headless   临时指定 Chrome
"""
import argparse
import json
import os
import posixpath
import shutil
import subprocess
import sys
import time
import urllib.request

import cleanup
import runtime_state

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))              # automation/scripts
REPO = os.path.dirname(os.path.dirname(HERE))
PROFILE = os.path.join(REPO, ".browser-profile")
# 清残留时按**这个仓库的完整 profile 路径**匹配，别用 '.browser-profile' 泛匹配——
# 别的项目也可能有同名目录，一刀切会把人家的浏览器杀掉。
PROFILE_MATCH = "*" + PROFILE + "*"
TMP = os.path.join(os.path.dirname(HERE), "_tmp")              # automation/_tmp（不进 git）
STATE = str(runtime_state.state_path("browser"))
CONFIG = os.path.join(REPO, ".local", "browser.json")
START_LOCK = os.path.join(TMP, "broker.start.lock")

PREFERRED_PORT = 9222
WINDOW = (1680, 1000)                                          # 跟以前 session 的视口一致
START_SECONDS = 25.0                                           # 等 CDP 端口的最长时间
PS_PATHS = (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",)
BROWSER_ENV = "AD_MANAGEMENT_BROWSER"


def log(*a):
    print(*a, flush=True)


# ---------- 端口探活 / 状态 ----------

def _opener():
    # 走本机地址别让系统代理插一脚（公司网络下 127.0.0.1 被代理接管会假"端口不通"）
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def cdp_url(port=None):
    return "http://127.0.0.1:%d" % int(port or _state_port())


def _state_port():
    try:
        return int(_state().get("port") or PREFERRED_PORT)
    except (TypeError, ValueError):
        return PREFERRED_PORT


def _responsive(port, timeout=1.5):
    try:
        with _opener().open(cdp_url(port) + "/json/version", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def is_up(timeout=1.5):
    """只有状态、进程身份和 CDP 响应都对上，才认为是本项目公共浏览器。"""
    state = _state()
    if not state:
        return False
    try:
        pid = int(state["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    port = _state_port()
    if not runtime_state.process_matches(
        pid, [PROFILE, "--remote-debugging-port=%d" % port], allow_unknown=True
    ):
        return False
    return _responsive(port, timeout)


def current_mode():
    """公共浏览器现在是有窗口还是无窗口；没跑就 None。"""
    if not is_up():
        return None
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f).get("mode") or "headless"
    except Exception:
        return "headless"


def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def status():
    """给命令行看的一行摘要：在没在跑 / 有窗口没 / 开了几个**页面**。

    页面数故意分开数：`/json/list` 里的 `service_worker` 是 profile 里装的扩展后台，一直都在、
    不算页面。刚起来时是 1 个（about:blank）；脚本干活时会临时多几个、跑完自己关；
    **停在那儿一直不降就是被强杀留下的页**——双击 `web/browser-stop.bat` 一把清掉即可。
    """
    if not is_up():
        pids = stray_pids()
        tail = ("" if not pids else
                "；但有 %d 个残留浏览器占着登录 profile（%s）——下次起时会自动清掉"
                % (len(pids), "、".join(map(str, pids))))
        return "没在跑（CDP 127.0.0.1:%d 不通）%s" % (_state_port(), tail)
    mode = current_mode()
    state = _state()
    browser = os.path.basename(state.get("browserPath") or current_browser_path()) or "浏览器"
    try:
        with _opener().open(cdp_url() + "/json/list", timeout=2) as r:
            items = json.loads(r.read().decode("utf-8"))
    except Exception:
        return "在跑：%s，%s（端口 %d，页面数读不到）" % (
            browser, "有窗口" if mode == "headed" else "无窗口", _state_port())
    pages = sum(1 for t in items if t.get("type") == "page")
    return "在跑：%s，%s，端口 %d，页面 %d 个（另有 %d 个扩展后台）" % (
        browser, "有窗口" if mode == "headed" else "无窗口",
        _state_port(), pages, len(items) - pages)


# ---------- 起 / 关 ----------

def browser_kind(path):
    name = os.path.basename(str(path)).lower()
    if "chrome" in name:
        return "Chrome"
    if "edge" in name or "msedge" in name:
        return "Edge"
    return "Chromium"


def _browser_candidates(kind):
    paths = []
    if sys.platform == "darwin":
        apps = ("/Applications", os.path.expanduser("~/Applications"))
        relatives = {
            "Edge": ("Microsoft Edge.app", "Contents", "MacOS", "Microsoft Edge"),
            "Chrome": ("Google Chrome.app", "Contents", "MacOS", "Google Chrome"),
        }
        paths = [posixpath.join(root, *relatives[kind]) for root in apps]
        found = ""
    elif kind == "Edge":
        for name in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(name)
            if base:
                paths.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
        found = shutil.which("msedge")
    else:
        for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(name)
            if base:
                paths.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        found = shutil.which("chrome")
    if found:
        paths.append(found)
    out = []
    for path in paths:
        if path and os.path.isfile(path) and path not in out:
            out.append(path)
    return out


def _configured_browser():
    raw = os.environ.get(BROWSER_ENV, "").strip()
    if raw:
        if os.path.isfile(raw):
            return raw
        kind = "Chrome" if raw.lower() == "chrome" else (
            "Edge" if raw.lower() == "edge" else ""
        )
        if not kind:
            raise RuntimeError("%s 只能是 edge、chrome 或浏览器程序路径" % BROWSER_ENV)
        found = _browser_candidates(kind)
        if found:
            return found[0]
        raise RuntimeError("指定的浏览器未安装：%s" % raw)

    try:
        with open(CONFIG, encoding="utf-8") as f:
            path = str(json.load(f).get("path") or "")
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return ""


def browser_exe(kind="auto"):
    if kind != "auto":
        found = _browser_candidates("Chrome" if kind == "chrome" else "Edge")
        if found:
            return found[0]
        raise RuntimeError("指定的浏览器未安装：%s" % kind)
    configured = _configured_browser()
    if configured:
        return configured
    for kind in ("Edge", "Chrome"):
        found = _browser_candidates(kind)
        if found:
            return found[0]
    raise RuntimeError(
        "找不到 Edge 或 Chrome。请安装其中一个，或在 .local/browser.json 配置浏览器路径。"
    )


def current_browser_path():
    path = str(_state().get("browserPath") or "")
    return path if path and os.path.isfile(path) else browser_exe()


def stray_pids(exe_path=None):
    """占着这个登录 profile 的浏览器进程号（查不到就空——权限不够时不猜）。"""
    exe_path = exe_path or current_browser_path()
    if not runtime_state.IS_WINDOWS:
        profile = os.path.normcase(PROFILE).replace("\\", "/")
        found = []
        for pid, command in runtime_state.process_commands().items():
            normalized = os.path.normcase(command).replace("\\", "/")
            if profile in normalized and "--user-data-dir" in normalized:
                found.append(pid)
        return sorted(found)
    process_name = os.path.basename(exe_path).lower()
    ps_exe = shutil.which("powershell") or shutil.which("pwsh")
    if not ps_exe:
        ps_exe = next((p for p in PS_PATHS if os.path.isfile(p)), None)
    if not ps_exe:
        log("  ! 找不到 PowerShell，查不了残留浏览器")
        return []
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='%s'\" | "
          "Where-Object { $_.CommandLine -like '%s' } | "
          "Select-Object -ExpandProperty ProcessId") % (process_name, PROFILE_MATCH)
    try:
        out = runtime_state.run_hidden(
            [ps_exe, "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=40,
        )
    except Exception as e:
        log("  ! 查残留浏览器失败：%s" % str(e).splitlines()[0][:100])
        return []
    return [int(x) for x in out.stdout.split() if x.strip().isdigit()]


def _kill_strays(what="清残留", exe_path=None):
    """杀掉占着本仓库登录 profile 的浏览器。`what` 只影响打出来的字。"""
    exe_path = exe_path or current_browser_path()
    pids = stray_pids(exe_path)
    if not pids:
        return 0
    log("  %s：%d 个浏览器进程（%s）" % (what, len(pids), "、".join(map(str, pids))))
    for pid in pids:
        runtime_state.terminate_process(pid, force=True)
    time.sleep(1.5)
    return len(pids)


def _write_state(mode, pid, browser_path, port):
    os.makedirs(TMP, exist_ok=True)
    runtime_state.write_state("browser", {
        "mode": mode,
        "pid": pid,
        "port": int(port),
        "cdpUrl": cdp_url(port),
        "browser": browser_kind(browser_path),
        "browserPath": browser_path,
        "profile": PROFILE,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


def _launch(mode, port):
    """起一只**独立**浏览器（脱离本进程：脚本 / 看板关了它也不跟着关）。"""
    browser_path = browser_exe()
    args = [browser_path, "--user-data-dir=" + PROFILE,
            "--remote-debugging-port=%d" % port, "--remote-allow-origins=*",
            "--no-first-run", "--no-default-browser-check",
            "--disable-session-crashed-bubble"]
    if mode == "headed":
        args.append("--start-maximized")
    else:
        args += ["--headless=new", "--window-size=%d,%d" % WINDOW]
    args.append("about:blank")
    process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            **runtime_state.detached_process_kwargs())
    process.browser_path = browser_path
    process.browser_port = port
    return process


def _start(mode, port):
    """起一只并等 CDP 端口通；通了 True，没通 False（端口不通就是没起成）。"""
    proc = _launch(mode, port)
    t0, deadline = time.time(), time.time() + START_SECONDS
    while time.time() < deadline:
        if _responsive(port):
            _write_state(mode, proc.pid, proc.browser_path, port)
            return True
        # 启动器秒退 = 系统把命令转给了已经在跑的那只浏览器（profile 被占），别干等
        if proc.poll() is not None and time.time() > t0 + 2:
            break
        time.sleep(0.3)
    return _responsive(port)


def _acquire_start_lock(seconds=START_SECONDS + 10):
    """起浏览器时排他：两个程序同时 ensure 时只让一个去起，另一个等端口通。"""
    os.makedirs(TMP, exist_ok=True)
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            os.close(os.open(START_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(START_LOCK) > START_SECONDS + 5:
                    os.remove(START_LOCK)
                    continue
            except OSError:
                continue
            if is_up():
                return False
            time.sleep(0.3)
    return False


def _release_start_lock():
    try:
        os.remove(START_LOCK)
    except OSError:
        pass


def ensure(mode="headless"):
    """确保公共浏览器在跑：没有就起、有就复用；要把无窗口切成有窗口时重启一次。

    返回 True＝这次动过手（起或重启），False＝直接复用了现成的。
    """
    mode = "headed" if mode == "headed" else "headless"
    if is_up():
        state_browser = str(_state().get("browserPath") or "")
        wanted_browser = browser_exe()
        if state_browser and os.path.normcase(state_browser) != os.path.normcase(wanted_browser):
            log("公共浏览器：浏览器配置已变化，重启一次")
            stop()
        elif not (mode == "headed" and current_mode() != "headed"):
            return False
        else:
            log("公共浏览器：从无窗口切成有窗口（重启一次；别的程序下次取数会自动挂回来）")
            stop()
    state = _state()
    if state:
        runtime_state.clear_state("browser", pid=state.get("pid"))
    port = runtime_state.next_free_port(PREFERRED_PORT)
    got = _acquire_start_lock()
    try:
        if is_up():                                   # 等锁的时候别人起好了
            return False
        if not got:
            raise RuntimeError("等公共浏览器的启动锁超时（%s）" % START_LOCK)
        if not _start(mode, port):
            _kill_strays()
            if not _start(mode, port):
                raise RuntimeError(
                    "公共浏览器起不来（CDP 127.0.0.1:%d 没通）。请先运行 "
                    "automation/scripts/browser_broker.py --stop 清理本项目残留进程后重试。" % port)
        log("公共浏览器：已就绪（%s，CDP 127.0.0.1:%d）"
            % ("有窗口" if mode == "headed" else "无窗口", port))
        return True
    finally:
        if got:
            _release_start_lock()


def stop():
    """关掉公共浏览器（下次谁要用会自动再起）。返回杀掉的进程数。"""
    state = _state()
    try:
        pid = int(state["pid"])
    except (KeyError, TypeError, ValueError):
        log("公共浏览器：没有可验证的本项目运行状态")
        return 0
    if not runtime_state.process_matches(pid, [PROFILE], allow_unknown=True):
        log("公共浏览器：状态中的 PID %d 不是本项目浏览器，拒绝结束" % pid)
        return 0
    port = _state_port()
    runtime_state.terminate_process(pid, force=True)
    time.sleep(1)
    runtime_state.clear_state("browser", pid=pid)
    if _responsive(port):
        raise RuntimeError(
            "公共浏览器仍可访问（CDP %s），这次关闭没有生效。"
            "请检查当前终端是否有权限结束浏览器，或在非沙箱终端运行。"
            % cdp_url(port))
    try:
        result = cleanup.maybe_clean_browser_profile(PROFILE)
        if result["status"] == "cleaned":
            log(
                "浏览器缓存：已清理 %d -> %d bytes"
                % (result["cache_bytes_before"], result["cache_bytes_after"])
            )
        elif result["status"] == "needs_confirmation":
            python_hint = (
                ".venv\\Scripts\\python.exe"
                if runtime_state.IS_WINDOWS else ".venv/bin/python"
            )
            log(
                "浏览器 profile 超过 1 GB，未自动清理。确认后运行："
                "%s automation/scripts/cleanup.py "
                "--browser-profile --deep"
                % python_hint
            )
    except Exception as exc:
        log("浏览器缓存：清理失败（不影响关闭）：%s" % str(exc).splitlines()[0][:160])
    return 1


def connect(pw):
    """挂到公共浏览器上，返回它的**主 context**。

    ⚠ 这个 context 是公共的：**别 `ctx.close()`、别 `browser.close()`**（CDP 连上的 browser
      一关就把整只浏览器关了，别的程序全跟着断）。用完只关自己开的标签页，然后 `pw.stop()`
      （或退出 `with sync_playwright()`）断开连接就行。
    """
    return pw.chromium.connect_over_cdp(cdp_url()).contexts[0]


def main():
    ap = argparse.ArgumentParser(description="公共浏览器（看板取数 / 建任务 / 登录共用这一只）")
    ap.add_argument("--status", action="store_true", help="看它跑没跑")
    ap.add_argument("--headless", action="store_true", help="起（或复用）无窗口的")
    ap.add_argument("--headed", action="store_true", help="起成有窗口的（要显示页面时用）")
    ap.add_argument("--stop", action="store_true", help="关掉（下次自动再起）")
    ap.add_argument("--browser", choices=["auto", "edge", "chrome"],
                    help="本次指定浏览器；auto 使用配置或自动检测")
    a = ap.parse_args()
    if a.browser:
        if a.browser == "auto":
            os.environ.pop(BROWSER_ENV, None)
        else:
            os.environ[BROWSER_ENV] = a.browser
    if a.stop:
        log("公共浏览器：已关闭（%d 个进程）" % stop())
    elif a.status:
        log("公共浏览器：%s" % status())
    elif a.headed:
        ensure("headed")
    else:
        ensure("headless")
        log("公共浏览器：%s" % status())


if __name__ == "__main__":
    main()
