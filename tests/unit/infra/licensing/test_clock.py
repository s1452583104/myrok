import os

from rok_assistant.infra.licensing import guard as guard_mod

DAY = 86400


def test_rollback_beyond_tolerance_is_expired(make_guard, base_time):
    """回拨超过 24h 容差 → 判篡改（spec §5.4）。"""
    make_guard(clock=lambda: base_time + 10 * DAY).status()
    assert make_guard(clock=lambda: base_time).status().kind == "expired"


def test_rollback_within_tolerance_gives_no_benefit_and_no_punishment(
        make_guard, base_time):
    """回拨 1 小时：不罚（容差内），但也不给好处——剩余天数不倒退。"""
    make_guard(clock=lambda: base_time + 3600).status()
    st = make_guard(clock=lambda: base_time).status()
    assert st.kind == "trial"
    assert st.days_left == 30


def test_future_file_mtime_is_tamper(make_guard, tmp_path, base_time):
    """交叉校验：存储文件的 mtime 比当前时间晚 24h 以上（spec §5.4）。"""
    make_guard().status()
    target = tmp_path / ".roklicense"
    future = base_time + 48 * 3600
    os.utime(target, (future, future))
    assert make_guard().status().kind == "expired"
