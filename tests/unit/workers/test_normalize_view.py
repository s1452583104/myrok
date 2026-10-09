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
    sm = LeaderStateMachine(handle, recs, target_levels=[7], march_preset=1,
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
    sm = LeaderStateMachine(handle, recs, target_levels=[7], march_preset=1,
                            march_troop_types=["infantry"], publisher_id="c1")
    _probe_stub(monkeypatch, sm, View.MODAL)
    with pytest.raises(RuntimeError, match=r"卡在\[弹窗遮罩\]视图"):
        sm._form_troop({})


def _rec_seq(*flags):
    """按顺序返回 matched，用尽后保持最后一个值。"""
    rec = MagicMock()
    state = {"i": 0}

    def recognize(_img):
        i = min(state["i"], len(flags) - 1)
        state["i"] += 1
        r = MagicMock()
        r.matched = flags[i]
        r.confidence = 1.0 if flags[i] else 0.0
        r.bbox = MagicMock(center=lambda: (50, 50))
        return r

    rec.recognize.side_effect = recognize
    return rec


class _NoSleepTime:
    """本文件**不** patch time（既有用例靠真实时间跑），所以新用例自己补一个。

    `_click_net_error` 里有一次 `time.sleep(self._human.jitter(1.5))`——默认
    profile 是 debug_no_jitter，jitter(1.5) 就是 1.5，真睡的话这两条用例
    各慢 1.5 秒。
    """

    @staticmethod
    def time():
        return 1000.0

    @staticmethod
    def sleep(_s):
        pass


def test_leader_normalize_dismisses_net_error_first(monkeypatch):
    """断网弹框在最前面处理：点「确定」后才走清理清单。

    回归 2026-10-09 实机：弹框是居中模态、四周地图仍可见，search_icon
    可能露出来 —— 旧实现第一行 `if self._find("search_icon"): return`
    直接返回，永远不会去点「确定」，后续识别全在模态底下落空。
    """
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _NoSleepTime)
    sm = _leader(monkeypatch, View.MAP, search_icon_matched=True)
    sm._rec["net_error_confirm"] = _rec_seq(True, True, False)
    sm._rec["alliance_btn"] = _rec(matched=True)   # 点掉后地图就绪，立即返回
    sm._normalize_view({})
    assert (960, 711) in sm._handle.clicks


def test_member_normalize_dismisses_net_error_first(monkeypatch):
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _NoSleepTime)
    sm = _member(monkeypatch, View.MAP)
    sm._rec["net_error_confirm"] = _rec_seq(True, True, False)
    sm._rec["alliance_btn"] = _rec(matched=True)
    sm._normalize_view({})
    assert (960, 711) in sm._handle.clicks
