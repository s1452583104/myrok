import threading

from rok_assistant.coordination.action_ledger import ActionLedger


def test_fresh_ledger_has_no_record():
    """新账本必须能区分「我知道我在家」和「我什么都不知道」——
    前者可放行，后者必须沿用 fail-closed。"""
    led = ActionLedger()
    assert led.has_record("c1") is False
    assert led.troops_out("c1") is False
    assert led.troops_out_seconds("c1", now=1000.0) == 0.0


def test_mark_troops_out_then_home():
    led = ActionLedger()
    led.mark_troops_out("c1", now=100.0)
    assert led.has_record("c1") is True
    assert led.troops_out("c1") is True
    assert led.troops_out_seconds("c1", now=160.0) == 60.0

    led.mark_troops_home("c1", now=200.0)
    assert led.troops_out("c1") is False
    assert led.troops_out_seconds("c1", now=260.0) == 0.0


def test_troops_out_seconds_never_negative():
    """时钟回拨 / now 早于写入时刻时返回 0，不返回负数。"""
    led = ActionLedger()
    led.mark_troops_out("c1", now=500.0)
    assert led.troops_out_seconds("c1", now=400.0) == 0.0


def test_rally_launched_and_fill_done_are_independent():
    led = ActionLedger()
    led.mark_rally_launched("c1", now=10.0)
    led.mark_fill_done("c1", now=20.0)
    snap = led.snapshot("c1")
    assert snap.last_rally_launched_ts == 10.0
    assert snap.last_fill_ts == 20.0
    # 只写时间戳不算「部队在外」——出城由 mark_troops_out 单独表达
    assert snap.troops_out is False


def test_fill_count_accumulates_per_character():
    """填兵次数是**累计值**，不是「最后一次填兵的时刻」。

    界面统计条要显示「一共填了几次兵」，`last_fill_ts` 只留最后一次，
    读它答不出这个问题。
    """
    led = ActionLedger()
    assert led.snapshot("c1").fill_count == 0     # 没填过 = 0，不是「未知」
    led.mark_fill_done("c1", now=10.0)
    led.mark_fill_done("c1", now=20.0)
    led.mark_fill_done("c1", now=30.0)
    assert led.snapshot("c1").fill_count == 3
    assert led.snapshot("c1").last_fill_ts == 30.0   # 时间戳语义不变
    assert led.snapshot("c2").fill_count == 0        # 按 char_id 隔离


def test_total_fills_sums_across_characters():
    led = ActionLedger()
    assert led.total_fills() == 0          # 空账本合计 0
    led.mark_fill_done("c1")
    led.mark_fill_done("c1")
    led.mark_fill_done("c2")
    assert led.total_fills() == 3          # 跨角色求和


def test_total_fills_does_not_create_entries():
    """统计必须只读：读一次合计不该给没填过兵的角色凭空建记录。

    建了记录会让 `has_record` 变真，而它正是集结门槛的 L0 准入判据
    ——「我知道我在家」可放行。为了显示一个数字把门槛撬开，是拿安全换好看。
    """
    led = ActionLedger()
    led.total_fills()
    assert led.has_record("c1") is False


def test_ledger_is_per_character():
    """两号共用一本账，按 char_id 隔离——串号会让 A 的部队状态去拦 B 的门槛。"""
    led = ActionLedger()
    led.mark_troops_out("c1", now=1.0)
    assert led.troops_out("c1") is True
    assert led.troops_out("c2") is False
    assert led.has_record("c2") is False


def test_snapshot_is_a_copy():
    led = ActionLedger()
    led.mark_troops_out("c1", now=1.0)
    snap = led.snapshot("c1")
    snap.troops_out = False
    assert led.troops_out("c1") is True


def test_concurrent_writes_do_not_lose_entries():
    """两个 worker 线程并发写不同 char_id，不能丢。"""
    led = ActionLedger()

    def _writer(cid):
        for _ in range(200):
            led.mark_troops_out(cid, now=1.0)

    ts = [threading.Thread(target=_writer, args=(f"c{i}",)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    for i in range(4):
        assert led.has_record(f"c{i}") is True
