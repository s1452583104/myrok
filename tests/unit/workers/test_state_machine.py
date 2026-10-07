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


import random
from unittest.mock import MagicMock

from rok_assistant.infra.anti_detection import AntiDetectionConfig, HumanProfile


class _SM(StateMachine):
    def _setup(self):
        pass


def _sm(human=None):
    return _SM("IDLE", human=human)


def test_default_profile_is_deterministic():
    """不注入 profile 时走 debug_no_jitter：轮询恰好 1.0s，与改动前一致。"""
    sm = _sm()
    assert sm._human.poll_interval() == 1.0
    assert sm._human.retry_attempts(3) == 3


def test_find_retry_uses_profile_poll_interval(monkeypatch):
    import rok_assistant.workers.state_machine as sm_mod
    slept = []
    monkeypatch.setattr(sm_mod.time, "sleep", slept.append)
    p = HumanProfile(AntiDetectionConfig(state_delay_min=0.5, state_delay_max=0.5),
                     rng=random.Random(0))
    sm = _sm(human=p)
    sm._handle = MagicMock()
    sm._rec = {}
    assert sm._find_retry("nope", attempts=3) is None
    # attempts 经 retry_attempts 抖动后是 2/3/4，等待次数随之是 1/2/3 —— 只钉
    # 「每次等待都取自 profile 的轮询间隔（此处恒 0.5）」，不钉随机次数本身
    # （次数由 Task 5 的 test_retry_attempts_varies_but_stays_positive 覆盖）。
    assert slept and all(s == 0.5 for s in slept)


def test_explicit_interval_is_jittered_not_replaced(monkeypatch):
    import rok_assistant.workers.state_machine as sm_mod
    slept = []
    monkeypatch.setattr(sm_mod.time, "sleep", slept.append)
    p = HumanProfile(AntiDetectionConfig(jitter_ratio=0.3), rng=random.Random(0))
    sm = _sm(human=p)
    sm._handle = MagicMock()
    sm._rec = {}
    sm._find_retry("nope", attempts=2, interval=2.0)
    assert len(slept) == 1
    assert 1.4 <= slept[0] <= 2.6        # 2.0 ± 30%


def test_click_result_passes_recognizer_id_as_anchor():
    sm = _sm()
    sm._handle = MagicMock()
    bbox = MagicMock()
    bbox.center.return_value = (10, 20)
    result = MagicMock()
    result.bbox = bbox
    result.recognizer_id = "march_btn"
    sm._click_result(result)
    sm._handle.click.assert_called_once_with(10, 20, anchor="march_btn",
                                             rapid=False)

    # rapid=True 必须透传到 handle：等级连点段靠它换更短的节奏（Task 3/4）
    sm._handle.click.reset_mock()
    sm._click_result(result, rapid=True)
    sm._handle.click.assert_called_once_with(10, 20, anchor="march_btn",
                                             rapid=True)


def test_click_xy_passes_anchor():
    sm = _sm()
    sm._handle = MagicMock()
    sm._click_xy(100, 200, anchor="preset_slot")
    sm._handle.click.assert_called_once_with(100, 200, anchor="preset_slot")
