from rok_assistant.coordination.action_ledger import ActionLedger
from rok_assistant.workers.queue_gate import (GateDecision, QueueGate,
                                              VOTE_SIZE)


def _gate(ledger=None, char_id="c1", **kw):
    return QueueGate(ledger if ledger is not None else ActionLedger(),
                     char_id, **kw)


def _settle(gate, verdict, now=0.0):
    """喂够 VOTE_SIZE 帧让投票采信，返回最后一次的结论。"""
    out = None
    for _ in range(VOTE_SIZE):
        out = gate.observe(verdict, now=now)
    return out


def test_vote_needs_three_identical_frames():
    """单帧不采信——这正是原来「偶发一帧噪声导致整轮判错」的入口。"""
    g = _gate()
    assert g.observe("none", now=0.0).decision is GateDecision.WAIT
    assert g.observe("none", now=1.0).decision is GateDecision.WAIT
    assert g.observe("none", now=2.0).decision is GateDecision.PROCEED


def test_vote_only_delays_never_flips():
    """已采信 battle 后插一帧 none 不得翻转成放行：
    battle→none 的误判会开一次注定被拒的车，反向只是多等几拍。"""
    g = _gate()
    _settle(g, "battle", now=0.0)
    out = g.observe("none", now=3.0)
    assert out.decision is GateDecision.WAIT
    assert out.verdict == "battle"


def test_vote_after_settled_unknown_never_proceeds():
    """已采信 unknown 后单帧反向判读不得翻成放行：
    unknown 分支只问账本，投票无权把 unknown 变成 PROCEED。
    （上一个用例只钉住 battle→none 的粘滞，钉不住这条路径。）"""
    led = ActionLedger()
    led.mark_troops_out("c1", now=0.0)
    g = _gate(led, unknown_grace=100000.0, ledger_stale_after=100000.0)
    out = _settle(g, "unknown", now=0.0)
    assert out.decision is GateDecision.WAIT
    assert out.verdict == "unknown"

    # 单帧 none 只是噪声，不足以翻掉已采信的 unknown
    out = g.observe("none", now=1.0)
    assert out.decision is GateDecision.WAIT
    assert out.verdict == "unknown"


def test_battle_blocks_and_gather_passes():
    g = _gate()
    out = _settle(g, "battle", now=0.0)
    assert out.decision is GateDecision.WAIT
    assert "行军/驻扎" in out.reason

    g2 = _gate()
    assert _settle(g2, "gather", now=0.0).decision is GateDecision.PROCEED
    g3 = _gate()
    assert _settle(g3, "none", now=0.0).decision is GateDecision.PROCEED


def test_unknown_without_ledger_record_keeps_old_fail_closed():
    """账本无记录（进程刚起）→ 沿用旧的 fail-closed + 宽限行为。"""
    g = _gate(unknown_grace=100.0)
    out = _settle(g, "unknown", now=0.0)
    assert out.decision is GateDecision.WAIT
    assert out.source == "grace"
    # 宽限到点仍放行（旧行为，防未知良性队列卡死调度）
    assert g.observe("unknown", now=101.0).decision is GateDecision.PROCEED


def test_unknown_with_ledger_home_passes_immediately():
    """账本说部队在家 → 立刻放行，不再等 900s。
    这是本次改动的核心收益：166 次 unknown 由「等计时器」变成「问账本」。"""
    led = ActionLedger()
    led.mark_troops_home("c1", now=0.0)
    g = _gate(led, unknown_grace=900.0)
    out = _settle(g, "unknown", now=5.0)
    assert out.decision is GateDecision.PROCEED
    assert out.source == "ledger"


def test_unknown_with_ledger_out_waits():
    led = ActionLedger()
    led.mark_troops_out("c1", now=0.0)
    g = _gate(led, unknown_grace=900.0)
    out = _settle(g, "unknown", now=100.0)
    assert out.decision is GateDecision.WAIT
    assert out.source == "ledger"


def test_unknown_with_stale_ledger_out_passes():
    """账本说在外超过 1 小时 → 账本本身不可信（例如 WAIT_RETURN 没跑到），
    放行并让调用方记警告，避免永久卡死。"""
    led = ActionLedger()
    led.mark_troops_out("c1", now=0.0)
    g = _gate(led, ledger_stale_after=3600.0)
    out = _settle(g, "unknown", now=4000.0)
    assert out.decision is GateDecision.PROCEED
    assert out.source == "grace"


def test_unknown_grace_still_bounds_ledger_out():
    """账本说在外且未过期，但 unknown 已持续超过宽限 → 放行（最后兜底）。"""
    led = ActionLedger()
    led.mark_troops_out("c1", now=0.0)
    g = _gate(led, unknown_grace=100.0, ledger_stale_after=100000.0)
    assert _settle(g, "unknown", now=0.0).decision is GateDecision.WAIT
    assert g.observe("unknown", now=101.0).decision is GateDecision.PROCEED


def test_unknown_since_resets_after_a_settled_non_unknown():
    """判据恢复正常后，unknown 计时必须清零——否则下一段 unknown
    会带着上一段的累计时长立刻放行。"""
    led = ActionLedger()
    led.mark_troops_out("c1", now=0.0)
    g = _gate(led, unknown_grace=100.0, ledger_stale_after=100000.0)
    _settle(g, "unknown", now=0.0)
    _settle(g, "battle", now=50.0)      # 恢复正常
    _settle(g, "unknown", now=60.0)
    # 若计时没清零，now=110 时会被误判为已等 110s 而放行
    assert g.observe("unknown", now=110.0).decision is GateDecision.WAIT
