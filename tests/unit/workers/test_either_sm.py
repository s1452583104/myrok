import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.either_sm import EitherStateMachine
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource


def _mock_rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec


def _make_sm(fill_targets=None, bus=None):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = _mock_rec()
    recs = {k: rec for k in ("search_icon", "level_plus", "search_btn",
                             "rally_attack_popup", "red_rally", "preset_1",
                             "troop_infantry", "march_btn", "alliance_btn",
                             "war_btn", "sort_nearest", "join_btn")}
    sm = EitherStateMachine(handle_source=handle, recognizers=recs,
                            target_level=8, march_preset=1,
                            march_troop_types=["infantry"],
                            fill_target_leaders=fill_targets or [],
                            event_bus=bus)
    return sm


def test_delegates_to_leader_then_member():
    sm = _make_sm(fill_targets=[{"instance": "i1", "name": "Boss"}])
    assert isinstance(sm._leader, LeaderStateMachine)
    assert isinstance(sm._member, MemberStateMachine)
    for _ in range(60):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    # leader 阶段完整走完（开集结），member 阶段接手到 END
    assert any("LEADER:LAUNCH" in h for h in sm.history)
    assert any(h.startswith("MEMBER:") for h in sm.history)
    # 开完集结不停留：member 收到了 launch 事件
    assert sm._member._pending_event is not None
    assert sm._member._pending_event["rally_id"].startswith("rally_")


def test_not_terminal_during_leader_phase():
    sm = _make_sm()
    sm.step()  # IDLE -> SEARCH_FORTRESS
    assert not sm.is_terminal()
    assert sm.current.startswith("LEADER:")


def test_step_reuses_stored_context():
    sm = _make_sm(fill_targets=[{"instance": "i1", "name": "Boss"}])
    sm.step({"marker": "x"})  # context stored; subsequent bare step() must reuse it
    for _ in range(60):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()


def test_empty_fill_targets_still_reaches_member_end():
    sm = _make_sm()  # fill_targets defaults to []
    for _ in range(60):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    assert sm.current == "MEMBER:END"
