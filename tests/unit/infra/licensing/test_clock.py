import os

from rok_assistant.infra.licensing import codec

DAY = 86400
FP = bytes(range(32))


def test_rollback_beyond_tolerance_gives_no_benefit_and_no_punishment(
        make_guard, base_time):
    """调回 10 天：不给好处（天数不倒退），也不罚（2026-11-01 前会判篡改锁死）。"""
    make_guard(clock=lambda: base_time + 10 * DAY).status()
    st = make_guard(clock=lambda: base_time).status()
    assert st.kind == "trial"
    assert st.days_left == 30
    assert st.allows_run is True


def test_rollback_within_tolerance_gives_no_benefit_and_no_punishment(
        make_guard, base_time):
    """回拨 1 小时：不罚，但也不给好处——剩余天数不倒退。"""
    make_guard(clock=lambda: base_time + 3600).status()
    st = make_guard(clock=lambda: base_time).status()
    assert st.kind == "trial"
    assert st.days_left == 30


def test_future_file_mtime_is_not_tamper(make_guard, tmp_path, base_time):
    """存储文件的 mtime 在将来**不再**判篡改（spec §5.4 的交叉校验已移除）。

    它在真实场景里只会误伤：用户拿错误的时钟跑过一次，文件 mtime 就落在将来，
    之后把时间改对反而被判篡改。
    """
    make_guard().status()
    target = tmp_path / ".roklicense"
    future = base_time + 48 * 3600
    os.utime(target, (future, future))
    assert make_guard().status().kind == "trial"


def test_activated_code_survives_clock_restored(make_guard, base_time, sign_code):
    """调时间测试的完整路径：调到未来 → 到期 → 激活 → 把时间改回来。

    这是线上反馈的现场（2026-11-01）：激活确实写进了记录，但 `last_seen` 被钉在
    那个未来的时间上，改回正确时间后 `status()` 判「回拨 = 篡改」→ 状态仍是
    expired，用户看到的是「点激活没有任何效果」，连买新码都救不回来。
    """
    fut = base_time + 60 * DAY
    make_guard().status()                                  # 首启在真实时间写记录
    assert make_guard(clock=lambda: fut).status().kind == "expired"

    g = make_guard(clock=lambda: fut)
    ok, msg = g.activate(sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=1))
    assert ok, msg

    st = make_guard(clock=lambda: base_time).status()      # 时钟改回正确时间
    assert st.kind == "licensed"
    assert st.allows_run is True
    assert st.days_left == 30                              # 60d 锚点 + 30d = 90d
