from unittest.mock import MagicMock

import numpy as np
import pytest

from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.core.recognizers.view_probe import View, ViewVerdict
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.member_sm import MemberStateMachine

_RESIDUAL_IDS = ("war_title", "queue_panel", "rally_attack_popup", "ap_refill",
                 "form_title", "replace_popup", "menu_expanded",
                 "warning_panel", "search_back", "map_btn", "alliance_btn")


@pytest.fixture(autouse=True)
def _no_pace(monkeypatch):
    monkeypatch.setattr("rok_assistant.workers.leader_sm._LEVEL_CLICK_PACE", 0.0)


def _rec(matched=True):
    rec = MagicMock()
    rec.recognize.return_value.matched = matched
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec


def _probe_stub(monkeypatch, sm, view):
    """把探针钉死成固定视图，隔离「清理清单有没有清干净」这个变量。"""
    monkeypatch.setattr(
        sm._view_probe, "probe",
        lambda _img: ViewVerdict(view, 0.9, ("stub",), {}))


def _leader(monkeypatch, view, search_icon_matched=False):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _rec(matched=False) for k in _RESIDUAL_IDS}
    recs["search_icon"] = _rec(matched=search_icon_matched)
    sm = LeaderStateMachine(handle, recs, target_level=7, march_preset=1,
                            march_troop_types=["infantry"], publisher_id="c1")
    _probe_stub(monkeypatch, sm, view)
    return sm


def _member(monkeypatch, view):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _rec(matched=False) for k in _RESIDUAL_IDS}
    recs["search_icon"] = _rec(matched=False)
    sm = MemberStateMachine(handle, recs, fill_target_leaders=[], char_id="c1")
    _probe_stub(monkeypatch, sm, view)
    return sm


def test_probe_map_counts_as_normalized(monkeypatch):
    """放大镜模板失配但探针确认在地图 → 归一化成功。
    同帧 alliance_btn 匹配而 search_icon 不匹配时，旧实现会判失败。"""
    sm = _leader(monkeypatch, View.MAP, search_icon_matched=False)
    sm._normalize_view({})          # 不得抛异常


def test_probe_failure_names_the_view(monkeypatch):
    sm = _leader(monkeypatch, View.TROOP_FORM, search_icon_matched=False)
    with pytest.raises(RuntimeError, match=r"卡在\[创建部队\]视图"):
        sm._normalize_view({})


def test_unknown_view_also_named(monkeypatch):
    """一个锚点都不命中时说「未知」，不能默认成「地图」。"""
    sm = _leader(monkeypatch, View.UNKNOWN, search_icon_matched=False)
    with pytest.raises(RuntimeError, match=r"卡在\[未知\]视图"):
        sm._normalize_view({})


def test_member_normalize_failure_names_the_view(monkeypatch):
    sm = _member(monkeypatch, View.RALLY_POPUP)
    with pytest.raises(RuntimeError, match=r"卡在\[集结弹窗\]视图"):
        sm._normalize_view({})


def test_form_troop_failure_names_the_view(monkeypatch):
    """`march_btn 不可见`（日志 5 次）同样说不出卡在哪，一并修。"""
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _rec(matched=False) for k in _RESIDUAL_IDS}
    recs["search_icon"] = _rec(matched=False)
    recs["march_btn"] = _rec(matched=False)
    sm = LeaderStateMachine(handle, recs, target_level=7, march_preset=1,
                            march_troop_types=["infantry"], publisher_id="c1")
    _probe_stub(monkeypatch, sm, View.MODAL)
    with pytest.raises(RuntimeError, match=r"卡在\[弹窗遮罩\]视图"):
        sm._form_troop({})
