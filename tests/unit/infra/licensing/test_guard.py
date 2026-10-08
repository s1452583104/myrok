import json

from rok_assistant.infra.licensing import codec, guard as guard_mod, store as store_mod, verify

FP = bytes(range(32))
DAY = 86400


def _corrupt_all(tmp_path):
    """把两处文件记录都改坏 → 触发「有记录但验不过」。

    写之前必须先摘掉 HIDDEN|SYSTEM 属性：本机上带这两个属性的文件无法以
    O_TRUNC 打开（`write_text` 就是 O_TRUNC），而 `store._FileSlot.save`
    刚给它们设过——这与 Task 4 在 test_store.py 里 `_write_raw` 的做法同一
    回事。读不受影响，只有截断写受影响。
    """
    for p in (tmp_path / "pd" / "license.dat", tmp_path / ".roklicense"):
        obj = json.loads(p.read_text(encoding="utf-8"))
        obj["trial_start"] = 1
        store_mod._set_attrs(p, store_mod._ATTR_NORMAL)
        p.write_text(json.dumps(obj), encoding="utf-8")


def test_first_run_is_trial_with_30_days(make_guard):
    st = make_guard().status()
    assert st.kind == "trial"
    assert st.days_left == 30
    assert st.allows_run is True
    assert st.label() == "试用剩余 30 天"


def test_trial_expires_after_30_days(make_guard, base_time):
    make_guard().status()                                  # 首启写记录
    st = make_guard(clock=lambda: base_time + 31 * DAY).status()
    assert st.kind == "expired"
    assert st.allows_run is False
    assert st.label() == "试用已结束，请输入激活码"


def test_activate_stacks_on_trial(make_guard, base_time, sign_code):
    g = make_guard()
    g.status()
    ok, msg = g.activate(sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=1))
    assert ok, msg
    st = g.status()
    assert st.kind == "licensed"
    assert st.days_left == 60
    assert st.label() == "已授权，剩余 60 天"


def test_activation_persists_across_guards(make_guard, sign_code):
    g = make_guard()
    g.status()
    assert g.activate(sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=1))[0]
    assert make_guard().status().days_left == 60           # 换一个 Guard 重读


def test_permanent_code(make_guard, sign_code):
    g = make_guard()
    g.status()
    assert g.activate(sign_code(FP, kind=codec.KIND_PERMANENT, days=0, serial=1))[0]
    st = g.status()
    assert st.kind == "permanent"
    assert st.label() == "永久授权"


def test_extend_after_permanent_is_accepted_silently(make_guard, sign_code):
    """用户可能重复购买，报错会引发售后（spec §7.3）。"""
    g = make_guard()
    g.status()
    g.activate(sign_code(FP, kind=codec.KIND_PERMANENT, days=0, serial=1))
    ok, _ = g.activate(sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=2))
    assert ok is True
    assert g.status().kind == "permanent"


def test_replay_is_rejected(make_guard, sign_code):
    """同一个码不能吃两次——防「一个延长码反复输入无限续期」（spec §7.3）。"""
    g = make_guard()
    g.status()
    code = sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=7)
    assert g.activate(code)[0] is True
    ok, msg = g.activate(code)
    assert ok is False
    assert msg == verify.REASON_USED
    assert g.status().days_left == 60                      # 没有被加第二次


def test_activate_reports_wrong_machine(make_guard, sign_code):
    g = make_guard()
    g.status()
    code = sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=1,
                     fp6=bytes(range(100, 132)))
    ok, msg = g.activate(code)
    assert ok is False
    assert msg == verify.REASON_WRONG_MACHINE


def test_activate_accepts_formatted_code_with_dashes(make_guard, sign_code):
    """用户从对话框复制的是分组带连字符的形态。"""
    g = make_guard()
    g.status()
    code = sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=1)
    ok, msg = g.activate(codec.format_code(code))
    assert ok, msg


def test_tampered_record_is_expired_and_never_reset(make_guard, tmp_path, base_time):
    """改坏记录 → 判篡改、强制 expired；**绝不重置试用期**（spec §5.3.1）。"""
    g = make_guard()
    g.status()
    _corrupt_all(tmp_path)
    st = make_guard().status()
    assert st.kind == "expired"
    assert st.allows_run is False
    # 再往后 31 天仍然 expired——说明没有被当成「首次运行」重新起算
    assert make_guard(clock=lambda: base_time + 31 * DAY).status().kind == "expired"


def test_activation_still_works_on_tampered_record(make_guard, tmp_path, sign_code):
    """判篡改不能让用户连买来的码都用不了（spec §12 已知局限 4）。

    但试用起点必须保持「永久结束」，不能顺手重置成 now。
    """
    g = make_guard()
    g.status()
    _corrupt_all(tmp_path)
    g2 = make_guard()
    assert g2.status().kind == "expired"
    ok, msg = g2.activate(sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=1))
    assert ok, msg
    assert g2.status().kind == "licensed"
    assert g2._store.read(FP).record.trial_start == 0      # 不是 now
