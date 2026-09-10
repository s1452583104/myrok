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
    rec = _mock_rec()
    # NOTE: no preset_* and no troop_* keys — filling does not use presets
    # (user requirement 2026-09-09). The old flow would raise KeyError on
    # preset_1 here; that is the enforcement of the requirement.
    recs = {k: rec for k in ("map_btn", "search_icon", "alliance_btn", "war_btn",
                             "sort_nearest", "join_btn", "march_btn")}
    sm = MemberStateMachine(handle_source=handle, recognizers=recs,
                            fill_target_leaders=[{"instance": "i1", "name": "Boss"}])
    return sm, handle

def test_member_receives_event_and_joins_without_preset():
    sm, handle = _make_sm()
    sm.on_rally_launched({"rally_id": "r1", "fortress_level": 8, "march_preset": 1})
    for _ in range(40):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    # 5 clicks: OPEN_ALLIANCE + OPEN_WAR + SORT + JOIN + LAUNCH.
    # (IDLE->WAIT_LAUNCH_EVENT, SWITCH_TO_SELF, SWITCH_BACK: no clicks;
    #  NORMALIZE sees search_icon, no map click; FILTER: no clicks;
    #  FORM_TROOP only waits for the popup, no clicks.)
    assert len(handle.clicks) == 5

def test_member_form_troop_does_not_click_preset_or_troops():
    sm, handle = _make_sm()
    assert "preset_1" not in sm._rec
    sm.on_rally_launched({"rally_id": "r1"})
    for _ in range(9):
        sm.step()
    assert sm.current == "FORM_TROOP"
    clicks_before = len(handle.clicks)
    sm.step()  # FORM_TROOP -> LAUNCH: clicks only march_btn, no preset/troop icons
    assert len(handle.clicks) == clicks_before + 1
    # Sanity: the only templates consulted are the 7 in recs — none is preset_N/troop_*
    assert all(k.startswith(("map_", "search_", "alliance_", "war_", "sort_",
                             "join_", "march_")) for k in sm._rec)
