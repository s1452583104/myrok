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


def test_unsettled_vote_is_bounded_never_holds_forever():
    """投票迟迟无法采信（判读在两态间反复）不能无限死等：超过
    unsettled_after 就按 unknown 处理，让账本 / 宽限接手。
    旧实现 `settled is None` 没有出口，会静默卡死。"""
    g = _gate(unsettled_after=30.0)
    out = None
    for i in range(20):
        # 交替 none/unknown，永远凑不出连续 VOTE_SIZE 帧同结论
        out = g.observe("none" if i % 2 == 0 else "unknown", now=float(i))
    assert out.decision is GateDecision.WAIT
    assert out.source == "vote"          # 界内仍走投票延迟
    out = g.observe("none", now=31.0)
    assert out.source != "vote"          # 越过界：不再是无出口的投票等待


def test_unsettled_vote_with_ledger_home_proceeds_via_ledger():
    """投票无法采信但账本说部队在家 → 越过界立刻按账本放行。"""
    led = ActionLedger()
    led.mark_troops_home("c1", now=0.0)
    g = _gate(led, unsettled_after=30.0)
    out = None
    for i in range(20):
        out = g.observe("none" if i % 2 == 0 else "unknown", now=float(i))
    assert out.source == "vote"
    out = g.observe("none", now=31.0)
    assert out.decision is GateDecision.PROCEED
    assert out.source == "ledger"


def test_unsettled_vote_without_ledger_follows_grace_and_releases():
    """投票无法采信且账本无记录 → 走旧 fail-closed + 宽限，到点仍放行。"""
    g = _gate(unsettled_after=30.0, unknown_grace=100.0)
    out = None
    for i in range(20):
        out = g.observe("none" if i % 2 == 0 else "unknown", now=float(i))
    assert out.source == "vote"
    out = g.observe("none", now=31.0)
    assert out.decision is GateDecision.WAIT
    assert out.source == "grace"
    # 宽限到点仍放行（不会因投票不采信而卡死）
    assert g.observe("unknown", now=131.0).decision is GateDecision.PROCEED


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


def test_returning_passes_like_gather():
    """返程中放行（2026-10-09 用户拍板，推翻 2026-09-16 的阻塞结论）。

    放行的安全阀在车头侧：返程中的主将载不出预设，_select_preset 会
    回退到下一个可用预设，全都载不出来则抛异常。
    """
    g = _gate()
    out = _settle(g, "returning", now=0.0)
    assert out.decision is GateDecision.PROCEED
    assert out.verdict == "returning"


def test_returning_does_not_flip_settled_battle():
    """投票「只延迟不翻转」不变：已采信 battle 后来一帧 returning 仍 WAIT。"""
    g = _gate()
    _settle(g, "battle", now=0.0)
    assert g.observe("returning", now=3.0).decision is GateDecision.WAIT
