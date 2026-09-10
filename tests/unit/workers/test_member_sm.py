import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def _mock_rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    return rec

def _make_sm():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _mock_rec() for k in ("map_btn", "search_icon", "alliance_btn",
                                     "war_btn", "sort_nearest", "join_btn",
                                     "march_btn")}
    # 录桩（守卫用户要求 2026-09-09「填兵不使用预设」）：preset_1/troop_cavalry
    # 同样永远命中 —— 基类 _find 用 .get() 取识别器，缺键只会静默 no-op 而非
    # KeyError，所以必须靠「recognize 从未被调用」来让回归大声失败。
    rec_preset = _mock_rec()
    rec_troop = _mock_rec()
    recs["preset_1"] = rec_preset
    recs["troop_cavalry"] = rec_troop
    sm = MemberStateMachine(handle_source=handle, recognizers=recs,
                            fill_target_leaders=[{"instance": "i1", "name": "Boss"}])
    return sm, handle, rec_preset, rec_troop

def test_member_receives_event_and_joins_without_preset():
    sm, handle, rec_preset, rec_troop = _make_sm()
    sm.on_rally_launched({"rally_id": "r1", "fortress_level": 8, "march_preset": 1})
    for _ in range(40):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    # 5 次点击：OPEN_ALLIANCE + OPEN_WAR + SORT + JOIN + LAUNCH。
    # （IDLE->WAIT_LAUNCH_EVENT、SWITCH_TO_SELF、SWITCH_BACK 无点击；
    #  NORMALIZE 命中 search_icon，不点 map_btn；FILTER 无点击；
    #  FORM_TROOP 只等弹窗，无点击。）
    assert len(handle.clicks) == 5
    # 预设槽位与兵种图标从未被识别（识别必先于点击，未被识别即绝无点击）
    assert rec_preset.recognize.call_count == 0
    assert rec_troop.recognize.call_count == 0
    # launch 事件已被消费并留存
    assert sm._pending_event is None
    assert sm.last_event["rally_id"] == "r1"

def test_member_form_troop_does_not_click_preset_or_troops():
    sm, handle, rec_preset, rec_troop = _make_sm()
    sm.on_rally_launched({"rally_id": "r1"})
    for _ in range(9):
        sm.step()
    assert sm.current == "FORM_TROOP"
    clicks_before = len(handle.clicks)
    sm.step()  # FORM_TROOP -> LAUNCH：只点 march_btn，不点预设/兵种
    assert len(handle.clicks) == clicks_before + 1
    assert rec_preset.recognize.call_count == 0
    assert rec_troop.recognize.call_count == 0

def test_filter_exhaustion_exits_to_end_with_failure_marker():
    sm, handle, _, _ = _make_sm()
    sm.on_rally_launched({"rally_id": "r1"})
    sm._ctx["war_attempts"] = 11  # 白盒预置：直接命中耗尽守卫（ctx 为内部状态）
    for _ in range(40):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    # END 出口必须赢过 FILTER->OPEN_WAR 重试边（耗尽守卫与重试守卫同时为真，
    # step 按注册顺序取第一个命中 —— 耗尽边注册在前）
    assert sm.history[-2] == "FILTER"
    assert sm._ctx["failed"] is True
    assert sm._ctx["fail_reason"] == "no_rally_found"
