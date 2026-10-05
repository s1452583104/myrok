import pytest
from rok_assistant.workers.state_machine import StateMachine, State, Transition

class Counter(StateMachine):
    def _setup(self):
        self.add_transition("start", "counting", "increment")
        self.add_transition("counting", "counting", "increment", guard=lambda ctx: ctx["n"] < 3)
        self.add_transition("counting", "done", "finish", guard=lambda ctx: ctx["n"] >= 3)

def test_initial_state():
    c = Counter(initial="start")
    assert c.current == "start"

def test_transition():
    c = Counter(initial="start")
    c.step({})
    assert c.current == "counting"

def test_guard_blocks_transition():
    c = Counter(initial="start")
    c.step({})
    c.step({"n": 10})  # would skip counting
    assert c.current == "done"

def test_history():
    c = Counter(initial="start")
    c.step({})
    c.step({"n": 1})
    c.step({"n": 2})
    c.step({"n": 3})
    assert c.history == ["start", "counting", "counting", "counting", "done"]


def _fake_rec(matched=True):
    from unittest.mock import MagicMock
    rec = MagicMock()
    rec.recognize.return_value.matched = matched
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    return rec


def test_base_helpers_click_retry_and_wait_for():
    import numpy as np
    from unittest.mock import MagicMock
    from rok_assistant.core.handle_source import MockHandleSource
    from rok_assistant.workers.leader_sm import LeaderStateMachine

    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = _fake_rec()
    # first two captures miss, third+ hits: switch matched via side_effect
    results = [MagicMock(matched=False), MagicMock(matched=False),
               MagicMock(matched=True, bbox=MagicMock(center=lambda: (50, 50)))]
    rec.recognize.side_effect = results + [results[-1]] * 100
    sm = LeaderStateMachine(handle, {"x": rec}, [7], 1, ["cavalry"])
    assert sm._wait_for("x", timeout=10.0, interval=0.0) is True
    assert sm._click_retry("x", attempts=1, interval=0.0) is True
    assert handle.clicks == [(50, 50)]
    assert sm._find_retry("nope", attempts=2, interval=0.0) is None


def test_wait_for_timeout_bails_false():
    import numpy as np
    from rok_assistant.core.handle_source import MockHandleSource
    from rok_assistant.workers.leader_sm import LeaderStateMachine

    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    sm = LeaderStateMachine(handle, {"x": _fake_rec(matched=False)}, [7], 1, ["cavalry"])
    assert sm._wait_for("x", timeout=0.0, interval=0.0) is False


def test_wait_click_reuses_found_result():
    import numpy as np
    from unittest.mock import MagicMock
    from rok_assistant.core.handle_source import MockHandleSource
    from rok_assistant.workers.leader_sm import LeaderStateMachine

    screenshot = np.zeros((100, 100, 3), dtype=np.uint8)
    # always-miss recognizer: _wait_click gives up, no click
    handle = MockHandleSource(screenshot=screenshot)
    sm = LeaderStateMachine(handle, {"x": _fake_rec(matched=False)}, [7], 1, ["cavalry"])
    assert sm._wait_click("x", timeout=0.0, interval=0.0) is False
    assert handle.clicks == []

    # hit on the 2nd capture; a 3rd recognize (re-find in _click) would raise
    # StopIteration since side_effect is exhausted - proves the found result
    # is clicked directly instead of re-finding.
    rec = _fake_rec()
    rec.recognize.side_effect = [
        MagicMock(matched=False),
        MagicMock(matched=True, bbox=MagicMock(center=lambda: (50, 50))),
    ]
    handle = MockHandleSource(screenshot=screenshot)
    sm = LeaderStateMachine(handle, {"x": rec}, [7], 1, ["cavalry"])
    assert sm._wait_click("x", timeout=10.0, interval=0.0) is True
    assert handle.clicks == [(50, 50)]
