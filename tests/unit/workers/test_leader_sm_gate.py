"""纯 leader 的集结前置门槛（2026-10-04 bug：车头不查队列）。

实机现象：上一轮集结部队还在城外（行军/返程/集结中）时就开下一轮，
「创建部队」表单载不出预设（武将在外），卡在 `预设槽 1 高亮未确认`。
根因是门槛只接在 EitherStateMachine 上，纯 leader 直接返回裸
LeaderStateMachine（factory.py）。

这些用例钉住三件事：门槛拦得住、放行时补写账本回城、没配门槛时行为不变。
"""

import numpy as np
from unittest.mock import MagicMock

from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.coordination.action_ledger import ActionLedger
from rok_assistant.infra.config import CharacterConfig, RoleEnum
from rok_assistant.workers.factory import create_state_machine
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.queue_gate import QueueGate


def _mock_rec(matched=True, center=(50, 50)):
    rec = MagicMock()
    rec.recognize.return_value.matched = matched
    rec.recognize.return_value.bbox = MagicMock(center=lambda: center)
    rec.recognize.return_value.confidence = 0.95
    return rec


def _sm(ledger=None, gate=None, char_id="c1"):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _mock_rec() for k in ("search_icon", "map_btn", "search_back",
                                     "alliance_btn", "queue_badge")}
    return LeaderStateMachine(handle, recs, target_levels=[7], march_preset=1,
                              march_troop_types=["infantry"],
                              publisher_id=char_id, ledger=ledger,
                              queue_gate=gate)


def test_gate_blocks_leader_while_queue_busy(monkeypatch):
    """有行军/返程/集结队列在外 → 门槛 WAIT，状态机留在 IDLE 不开搜。"""
    led = ActionLedger()
    gate = QueueGate(led, "c1")
    sm = _sm(led, gate)
    monkeypatch.setattr(sm, "queue_verdict", lambda: "battle")
    for _ in range(3):
        sm.step()
    assert sm.current == "IDLE"
    assert gate._settled == "battle"


def test_gate_marks_troops_home_when_queue_clear(monkeypatch):
    """门采信「无战斗队列」→ 必须补写账本回城。

    纯 leader 原本只有 mark_troops_out 没有回城写入，账本会永远停在
    「在外」；一旦队列图标不可辨走 unknown 分支，就会 fail-closed 干等
    900s（把「开错车」换成「卡 15 分钟」）。
    """
    led = ActionLedger()
    led.mark_troops_out("c1")
    sm = _sm(led, QueueGate(led, "c1"))
    monkeypatch.setattr(sm, "queue_verdict", lambda: "none")
    for _ in range(3):
        sm.step()
    assert led.troops_out("c1") is False
    # 放行后子状态机确实推进了（不是被别的理由卡住）
    assert sm.current != "IDLE"


def test_gate_does_not_mark_home_on_gather(monkeypatch):
    """仅采集队列在外 → 放行（采集不阻塞开车），但不写回城。

    账本 mark_troops_home 的口径是「派遣队列判空」，gather 是队列非空。
    与 either 的 WAIT_RETURN 同一口径（test_either_sm_gate 的
    test_wait_return_gather_does_not_mark_home）——同一面旗帜、同一个
    问题，两处不该给出不同答案。代价只是后续遇 unknown 会多等一段，
    方向安全（只会多等，不会误放）。
    """
    led = ActionLedger()
    led.mark_troops_out("c1")
    sm = _sm(led, QueueGate(led, "c1"))
    monkeypatch.setattr(sm, "queue_verdict", lambda: "gather")
    for _ in range(3):
        sm.step()
    assert led.troops_out("c1") is True
    # 但仍要放行：采集队列不占主将，不该被门槛拦住
    assert sm.current != "IDLE"


def test_gate_does_not_mark_home_when_unsettled(monkeypatch):
    """投票未采信（unknown 走账本/宽限放行）时不得写回城——那没有画面证据。"""
    led = ActionLedger()
    led.mark_troops_out("c1")
    gate = QueueGate(led, "c1")
    sm = _sm(led, gate)
    monkeypatch.setattr(sm, "queue_verdict", lambda: "unknown")
    for _ in range(3):
        sm.step()
    assert led.troops_out("c1") is True


def test_gate_log_reason_change_beats_throttle(caplog):
    """每轮第一拍的「投票 1/3 帧」不得吃掉随后那条真因。

    2026-10-04 实机验证时被这条节流误导过：日志里只剩「投票 1/3 帧」，
    读起来像「门槛放行了」，其实是被拦住（真因那条被 30s 窗口压掉）。
    理由变了 = 判据状态变了，必须立刻可见；同一条理由仍然节流。
    """
    import logging
    led = ActionLedger()
    sm = _sm(led, QueueGate(led, "c1"))
    with caplog.at_level(logging.INFO):
        sm._gate_log("队列判据尚未采信（投票 1/3 帧）")
        sm._gate_log("有行军/驻扎队列在城外，等待回城后再搜索")
        sm._gate_log("有行军/驻扎队列在城外，等待回城后再搜索")
    msgs = [r.getMessage() for r in caplog.records]
    assert sum("尚未采信" in m for m in msgs) == 1
    assert sum("有行军" in m for m in msgs) == 1   # 换理由立刻打、重复仍节流


def test_leader_without_gate_advances(monkeypatch):
    """未注入门槛（旧行为/未配 ledger）→ 与改动前逐字节一致：直接推进。"""
    sm = _sm(None, None)
    sm.step()
    assert sm.current != "IDLE"


def test_factory_wires_gate_for_leader_role():
    """factory 对纯 leader 必须注入门槛，否则这次修的就是个死代码。"""
    char = CharacterConfig(id="c1", name="H", role=RoleEnum.LEADER,
                           target_levels=[8], march_preset=1,
                           march_troop_types=["infantry"], fill_target_leaders=[])
    sm = create_state_machine(char, MockHandleSource(
        screenshot=np.zeros((10, 10, 3), dtype=np.uint8)), {},
        ledger=ActionLedger())
    assert isinstance(sm, LeaderStateMachine)
    assert sm._queue_gate is not None


def test_factory_leader_without_ledger_has_no_gate():
    """没注入账本 = 特性关闭，保持旧行为（与 ledger 参数既有语义一致）。"""
    char = CharacterConfig(id="c1", name="H", role=RoleEnum.LEADER,
                           target_levels=[8], march_preset=1,
                           march_troop_types=["infantry"], fill_target_leaders=[])
    sm = create_state_machine(char, MockHandleSource(
        screenshot=np.zeros((10, 10, 3), dtype=np.uint8)), {})
    assert isinstance(sm, LeaderStateMachine)
    assert sm._queue_gate is None
