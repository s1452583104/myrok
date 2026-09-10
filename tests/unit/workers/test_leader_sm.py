import numpy as np
import pytest
from unittest.mock import MagicMock
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.core.handle_source import MockHandleSource


class _FakeTime:
    """Deterministic clock. state_machine helpers sleep on timeout retries;
    replacing its `time` module makes _wait_for/_click_retry advance instantly
    instead of burning real seconds in tests."""

    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture(autouse=True)
def _fast_time(monkeypatch):
    fake = _FakeTime()
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", fake)
    return fake


def _mock_rec(matched=True):
    rec = MagicMock()
    rec.recognize.return_value.matched = matched
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    return rec


RECOGNIZER_IDS = ("map_btn", "search_icon", "level_plus", "level_minus",
                  "search_btn", "red_rally", "toast_no_fortress",
                  "rally_attack_popup", "preset_1", "troop_cavalry", "march_btn")


def _make_sm(target_level=7, wait=0.0):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _mock_rec() for k in RECOGNIZER_IDS}
    sm = LeaderStateMachine(handle, recs, target_level=target_level,
                            march_preset=1, march_troop_types=["cavalry"],
                            event_bus=None, wait_members_seconds=wait)
    return sm, handle


def test_happy_path_reaches_end_and_publishes():
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    events = []
    bus.subscribe("rally_launched", lambda p: events.append(p))
    sm, handle = _make_sm()
    sm._bus = bus
    for _ in range(30):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    assert len(events) == 1
    assert events[0]["fortress_level"] == 7
    assert sm.last_rally_event["march_preset"] == 1
    # real flow must have clicked red_rally (the fixed bug: old code never did);
    # every mock click lands at (50,50): search, 12x minus, 6x plus, search_btn,
    # red_rally, preset_1, troop_cavalry, march_btn => >= 9 clicks
    assert handle.clicks.count((50, 50)) >= 9


def test_select_level_resets_with_minus_then_plus():
    sm, handle = _make_sm(target_level=3)
    sm.step()  # IDLE -> NORMALIZE (search_icon visible: no map_btn click)
    sm.step()  # NORMALIZE -> SEARCH_FORTRESS (1 click on search_icon)
    sm.step()  # SEARCH_FORTRESS -> SELECT_LEVEL (minus*12 + plus*2 = 14 clicks)
    sm.step()  # SELECT_LEVEL -> CONFIRM_SEARCH (1 click on search_btn)
    # actions fire on the edge into the next state: 1 + 14 + 1 = 16
    assert len(handle.clicks) == 16


def test_no_result_toast_retries_then_ends():
    sm, handle = _make_sm()
    recs = sm._rec
    recs["red_rally"].recognize.return_value.matched = False  # no detail popup ever
    steps = 0
    while not sm.is_terminal() and steps < 60:
        sm.step()
        steps += 1
    assert sm.is_terminal()
    assert sm.history.count("CHECK_RESULT") >= 3  # retried
    assert sm._ctx.get("failed") is True  # give_up sets the member_sm convention
    assert sm._ctx.get("fail_reason") == "no_fortress_found"


def test_locked_fortress_dismisses_and_researches():
    sm, handle = _make_sm()
    recs = sm._rec
    # red_rally visible (detail popup there) but rally_attack_popup never
    # appears => locked: dismiss at empty ground, renormalize, re-search
    recs["rally_attack_popup"].recognize.return_value.matched = False
    steps = 0
    while not sm.is_terminal() and steps < 120:
        sm.step()
        steps += 1
    assert sm.is_terminal()  # locked_count cap reached -> END, no infinite loop
    assert sm._ctx.get("locked_count") == 5
    assert sm._ctx.get("fail_reason") == "locked_fortress"
    assert (960, 540) in handle.clicks  # empty-ground dismiss taps happened


def test_failed_march_click_does_not_publish():
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    events = []
    bus.subscribe("rally_launched", lambda p: events.append(p))
    sm, handle = _make_sm()
    sm._bus = bus
    sm._rec["march_btn"].recognize.return_value.matched = False
    steps = 0
    with pytest.raises(RuntimeError):
        while not sm.is_terminal() and steps < 30:
            sm.step()
            steps += 1
    # a failed march_btn click must never wake members
    assert events == []
    assert sm.last_rally_event is None
