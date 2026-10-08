import datetime

from rok_assistant.infra.licensing import codec, state, verify
from rok_assistant.infra.licensing.store import Record

FP = bytes(range(32))
DAY = 86400
T0 = 1_700_000_000          # 固定基准时间戳


def _rec(trial_start=T0, last_seen=T0, licenses=()):
    return Record(trial_start=trial_start, last_seen=last_seen,
                  licenses=list(licenses))


def _lic(sign_code, serial, *, days=30, kind=codec.KIND_EXTEND, applied_at=None):
    return {"code": sign_code(FP, kind=kind, days=days, serial=serial),
            "applied_at": T0 if applied_at is None else applied_at}


# ---- 试用期边界 ----

def test_trial_lasts_30_days(test_public_b64):
    kw = dict(trial_start=T0, last_seen=T0, licenses=[], fp_main=FP,
              public_key_b64=test_public_b64)
    ev = state.evaluate(now=T0 + 29 * DAY, **kw)
    assert ev.kind == "trial"
    assert ev.days_left == 1
    ev = state.evaluate(now=T0 + 30 * DAY, **kw)
    assert ev.kind == "expired"
    assert ev.days_left == 0


def test_expiry_is_a_date(test_public_b64):
    ev = state.evaluate(trial_start=T0, last_seen=T0, licenses=[], fp_main=FP,
                        now=T0, public_key_b64=test_public_b64)
    assert isinstance(ev.expiry, datetime.date)


# ---- 叠加语义 ----

def test_extend_stacks_on_remaining_trial(sign_code, test_public_b64):
    """试用还剩 20 天时输入「延长 30 天」→ 共 50 天（spec §7.3）。"""
    ev = state.evaluate(trial_start=T0, last_seen=T0,
                        licenses=[_lic(sign_code, 1, days=30)], fp_main=FP,
                        now=T0 + 10 * DAY, public_key_b64=test_public_b64)
    assert ev.kind == "licensed"
    assert ev.days_left == 50


def test_extend_starts_from_today_when_expired(sign_code, test_public_b64):
    now = T0 + 100 * DAY
    ev = state.evaluate(trial_start=T0, last_seen=now,
                        licenses=[_lic(sign_code, 1, days=7, applied_at=now)],
                        fp_main=FP, now=now, public_key_b64=test_public_b64)
    assert ev.days_left == 7


def test_two_codes_are_order_independent(sign_code, test_public_b64):
    """按 serial 升序累加——否则「先加 30 再加 7」和反过来结果不同（spec §7.2）。"""
    a = _lic(sign_code, 1, days=30, applied_at=T0)
    b = _lic(sign_code, 2, days=7, applied_at=T0 + 200 * DAY)
    kw = dict(trial_start=T0, last_seen=T0 + 200 * DAY, fp_main=FP,
              now=T0 + 200 * DAY, public_key_b64=test_public_b64)
    assert state.evaluate(licenses=[a, b], **kw).days_left == 7
    assert state.evaluate(licenses=[b, a], **kw).days_left == 7


def test_applied_at_is_clamped_by_last_seen(sign_code, test_public_b64):
    """把 applied_at 改大占不到便宜：它被 last_seen 夹住（spec §5.2.1）。"""
    ev = state.evaluate(
        trial_start=T0, last_seen=T0,
        licenses=[_lic(sign_code, 1, days=30, applied_at=T0 + 100 * DAY)],
        fp_main=FP, now=T0, public_key_b64=test_public_b64)
    assert ev.days_left == 60          # 不是 130


# ---- 永久 / 无效码 ----

def test_permanent_never_expires(sign_code, test_public_b64):
    ev = state.evaluate(
        trial_start=T0, last_seen=T0,
        licenses=[_lic(sign_code, 1, days=0, kind=codec.KIND_PERMANENT)],
        fp_main=FP, now=T0 + 10000 * DAY, public_key_b64=test_public_b64)
    assert ev.kind == "permanent"
    assert ev.expiry is None
    assert ev.days_left is None


def test_invalid_code_is_discarded(test_public_b64):
    ev = state.evaluate(trial_start=T0, last_seen=T0,
                        licenses=[{"code": "坏码", "applied_at": T0}],
                        fp_main=FP, now=T0, public_key_b64=test_public_b64)
    assert ev.kind == "trial"
    assert ev.days_left == 30


def test_code_for_other_machine_is_discarded(sign_code, test_public_b64):
    other = sign_code(FP, kind=codec.KIND_EXTEND, days=3650, serial=1,
                      fp6=bytes(range(100, 132)))
    ev = state.evaluate(trial_start=T0, last_seen=T0,
                        licenses=[{"code": other, "applied_at": T0}],
                        fp_main=FP, now=T0, public_key_b64=test_public_b64)
    assert ev.kind == "trial"


# ---- used_serials / apply_activation ----

def test_used_serials_only_counts_valid_codes(sign_code, test_public_b64):
    good = sign_code(FP, kind=codec.KIND_EXTEND, days=1, serial=9)
    rec = _rec(licenses=[{"code": good, "applied_at": T0},
                         {"code": "坏的", "applied_at": T0}])
    assert state.used_serials(rec, FP, test_public_b64) == {9}


def test_apply_activation_is_idempotent(sign_code, test_public_b64):
    code = sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=3)
    payload, _ = verify.verify_code(code, FP, test_public_b64)
    once = state.apply_activation(_rec(), code_text=code, payload=payload,
                                  now=T0, last_seen=T0)
    twice = state.apply_activation(once, code_text=code, payload=payload,
                                   now=T0, last_seen=T0)
    assert len(once.licenses) == 1
    assert len(twice.licenses) == 1


def test_apply_activation_keeps_trial_start(sign_code, test_public_b64):
    """激活**绝不**动 trial_start——动了就是把试用期重置了。"""
    code = sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=3)
    payload, _ = verify.verify_code(code, FP, test_public_b64)
    out = state.apply_activation(_rec(trial_start=111, last_seen=222),
                                 code_text=code, payload=payload,
                                 now=333, last_seen=222)
    assert out.trial_start == 111
    assert out.licenses[0]["applied_at"] == 333


# ---- 时钟 ----

def test_effective_now_never_goes_backwards():
    assert state.effective_now(100, 500) == 500
    assert state.effective_now(900, 500) == 900


def test_clock_rolled_back_has_24h_tolerance():
    assert state.clock_rolled_back(500, 1000) is False           # 容差内
    assert state.clock_rolled_back(0, 48 * 3600) is True         # 超过 24h
    assert state.clock_rolled_back(1, 48 * 3600) is True
    assert state.clock_rolled_back(48 * 3600, 48 * 3600) is False
