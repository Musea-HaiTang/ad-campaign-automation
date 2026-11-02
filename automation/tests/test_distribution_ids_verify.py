from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_distribution_ids as dist  # noqa: E402
import execution_state as es  # noqa: E402


class FakePage:
    pass


class FakeListPage:
    def __init__(self):
        self.page = FakePage()
        self.signature = "old"
        self.filtered = False
        self.row_lookup_after_refresh = False

    def table_text(self):
        return self.signature

    def filter(self, values):
        self.filtered = True

    def query(self, wait_ms=0, wait_rows=True):
        self.signature = "new"
        return True

    def row_by_name(self, name, timeout=8):
        self.row_lookup_after_refresh = self.signature == "new"
        return SimpleNamespace(
            id="207982",
            cells=["207982", name],
            text=lambda: "207982 " + name,
        )


def test_verify_waits_for_filtered_table_to_repaint(monkeypatch):
    page = FakePage()
    lp = FakeListPage()
    monkeypatch.setattr(dist.ui, "goto", lambda page, url: None)
    monkeypatch.setattr(dist, "open_list_page", lambda page: lp)
    monkeypatch.setattr(
        dist.ui,
        "wait_for",
        lambda page, probe, timeout, what: probe(),
    )
    monkeypatch.setattr(dist.ui, "log", lambda *args: None)

    state = dist.verify_created(page, "腾讯云产品-hang-云服务器")
    assert state.kind == es.FOUND
    assert state.object_id == "207982"
    assert lp.filtered is True
    assert lp.row_lookup_after_refresh is True


def test_large_pending_submit_resets_public_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(dist.broker, "stop", lambda: calls.append("stop") or 3)
    monkeypatch.setattr(dist.ui, "log", lambda *args: None)

    dist.reset_browser_after_large_submit(True, True, dist.READBACK_MAX_IDS + 1)

    assert calls == ["stop"]


def test_small_or_unsubmitted_keeps_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(dist.broker, "stop", lambda: calls.append("stop") or 0)
    monkeypatch.setattr(dist.ui, "log", lambda *args: None)

    dist.reset_browser_after_large_submit(False, True, dist.READBACK_MAX_IDS)
    dist.reset_browser_after_large_submit(False, True, dist.READBACK_MAX_IDS + 1)

    assert calls == []


def test_ack_classifies_success_failure_and_unknown():
    assert dist.classify_ack(["保存成功"]) == "success"
    assert dist.classify_ack(["保存失败"]) == "failure"
    assert dist.classify_ack(["提交异常"]) == "failure"
    assert dist.classify_ack(["请稍候"]) == "unknown"
    assert dist.classify_ack([]) == "unknown"


def test_existing_same_name_requires_same_member_count():
    state = es.found("208508", cells=["208508", "测试名单", "1,234", "博客ID"])
    assert dist.existing_list_matches(state, 1234)
    assert not dist.existing_list_matches(state, 2)
