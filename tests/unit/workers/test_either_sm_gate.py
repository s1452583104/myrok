import time
from unittest.mock import MagicMock

import numpy as np
import pytest

from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.coordination.action_ledger import ActionLedger
from rok_assistant.workers.either_sm import EitherStateMachine
from rok_assistant.workers.queue_gate import GateDecision


@pytest.fixture(autouse=True)
def _no_pace(monkeypatch):
    monkeypatch.setattr("rok_assistant.workers.either_sm.random.uniform",
                        lambda a, b: 0.0)


def _rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec


def _sm(ledger=None, char_id="c1"):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = _rec()
    recs = {k: rec for k in ("search_icon", "map_btn", "search_back",
                             "level_plus", "search_btn", "alliance_btn")}
    return EitherStateMachine(handle_source=handle, recognizers=recs,
                              target_levels=[7], march_preset=1,
                              march_troop_types=["infantry"],
                              fill_target_leaders=[], char_id=char_id,
                              ledger=ledger)


def test_gate_uses_ledger_instead_of_grace(monkeypatch):
    """unknown 三帧 + 账本在家 → 放行，子状态机离开 IDLE。
    这是本任务的核心：把「等 900s」换成「问账本」。"""
    led = ActionLedger()
    led.mark_troops_home("c1", now=0.0)
    sm = _sm(led)
    monkeypatch.setattr(sm, "_queue_verdict", lambda: "unknown")
    for _ in range(3):
        sm.step()
    # 门槛放行后 step 才委托给 _leader，子状态机开始推进
    assert sm._leader.current != "IDLE"


def test_gate_still_blocks_when_ledger_says_out(monkeypatch):
    led = ActionLedger()
    # 账本时间戳是墙钟（Task 2 语义）：now=0.0 会被 QueueGate 判为「在外
    # 超过 3600s，账本不可信」而放行，与用例意图（WAIT）相反。故用「刚
    # 发生」的时刻，让账本记录的在外时长落在可信窗内。
    led.mark_troops_out("c1", now=time.time())
    sm = _sm(led)
    monkeypatch.setattr(sm, "_queue_verdict", lambda: "unknown")
    # 直接问门槛，钉住「WAIT 的**理由**是账本说在外」——只断言 IDLE 不够：
    # 投票未采信、账本无记录走宽限，也都停在 IDLE。账本一旦被清空/未注入
    # 而退化成无记录，source 会变成 "grace"，本断言即挂
    outcome = None
    for _ in range(3):
        outcome = sm._gate.observe("unknown")
    assert outcome.decision is GateDecision.WAIT
    assert outcome.source == "ledger"
    for _ in range(3):
        sm.step()
    # 门槛 WAIT → step 提前 return，_leader 一拍都没跑
    assert sm._leader.current == "IDLE"


def test_wait_return_empty_queue_marks_troops_home(monkeypatch):
    """返城等待判定队列已空 → 账本必须记回城，否则部队永远「在外」。"""
    led = ActionLedger()
    led.mark_troops_out("c1", now=0.0)
    sm = _sm(led)
    monkeypatch.setattr(sm, "_queue_verdict", lambda: "none")
    sm._phase = "wait_return"
    sm._wait_deadline = 9e9
    sm._next_check = 0.0
    sm._step_wait_return()
    assert led.troops_out("c1") is False


def test_wait_return_gather_does_not_mark_home(monkeypatch):
    """仅采集队列在外时部队并未全回：写「回城」会让下一轮门槛
    误判为可搜。"""
    led = ActionLedger()
    led.mark_troops_out("c1", now=0.0)
    sm = _sm(led)
    monkeypatch.setattr(sm, "_queue_verdict", lambda: "gather")
    sm._phase = "wait_return"
    sm._wait_deadline = 9e9
    sm._next_check = 0.0
    sm._step_wait_return()
    assert led.troops_out("c1") is True
