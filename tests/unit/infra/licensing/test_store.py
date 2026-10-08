import json
import os

import pytest

from rok_assistant.infra.licensing import codec, store

FP = bytes(range(32))
OTHER_FP = bytes(range(100, 132))


@pytest.fixture
def loc(tmp_path):
    return store.Locations(registry=None,
                           program_data=tmp_path / "pd" / "license.dat",
                           user_file=tmp_path / ".roklicense")


@pytest.fixture
def st(loc):
    return store.Store(loc)


def _rec(trial_start=1000, last_seen=2000, licenses=None):
    return store.Record(trial_start=trial_start, last_seen=last_seen,
                        licenses=list(licenses or []))


# ---- 基本读写 ----

def test_write_then_read_roundtrip(st):
    st.write(FP, _rec(trial_start=1234, last_seen=5678))
    res = st.read(FP)
    assert res.valid is True
    assert res.tampered is False
    assert res.record.trial_start == 1234
    assert res.record.last_seen == 5678


def test_read_reports_absent_when_nothing_written(st):
    res = st.read(FP)
    assert res.exists is False
    assert res.valid is False
    assert res.tampered is False
    assert res.record is None


def test_default_locations_has_all_three_slots():
    loc = store.default_locations()
    assert loc.registry is not None
    assert loc.program_data is not None
    assert loc.user_file is not None


# ---- 取最早 / 并集去重 ----

def test_read_takes_earliest_trial_start(st, loc):
    """取最早 = 剩余试用期最少，是保守方向。"""
    st.write(FP, _rec(trial_start=1000, last_seen=2000))
    loc.program_data.write_text(
        store._serialize(_rec(trial_start=500, last_seen=2000), FP),
        encoding="utf-8")
    assert st.read(FP).record.trial_start == 500


def test_read_takes_latest_last_seen(st, loc):
    st.write(FP, _rec(trial_start=1000, last_seen=2000))
    loc.program_data.write_text(
        store._serialize(_rec(trial_start=1000, last_seen=9000), FP),
        encoding="utf-8")
    assert st.read(FP).record.last_seen == 9000


def test_licenses_merged_as_union_by_serial(st, loc, sign_code):
    c1 = sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=1)
    c2 = sign_code(FP, kind=codec.KIND_EXTEND, days=7, serial=2)
    st.write(FP, _rec(licenses=[{"code": c1, "applied_at": 10}]))
    loc.program_data.write_text(
        store._serialize(_rec(licenses=[{"code": c2, "applied_at": 20}]), FP),
        encoding="utf-8")
    got = {codec.serial_of(i["code"]) for i in st.read(FP).record.licenses}
    assert got == {1, 2}


def test_same_serial_keeps_smaller_applied_at(st, loc, sign_code):
    c1 = sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=1)
    st.write(FP, _rec(licenses=[{"code": c1, "applied_at": 10}]))
    loc.program_data.write_text(
        store._serialize(_rec(licenses=[{"code": c1, "applied_at": 99}]), FP),
        encoding="utf-8")
    items = st.read(FP).record.licenses
    assert len(items) == 1
    assert items[0]["applied_at"] == 10


def test_self_heal_rewrites_missing_location(st, loc):
    """重新解压清掉了第 3 处 → 下次启动补写回来（spec §5.3 自愈）。"""
    st.write(FP, _rec())
    loc.user_file.unlink()
    assert st.read(FP).valid is True
    assert loc.user_file.exists()


# ---- HMAC ----

def test_hmac_rejects_record_from_other_machine(st):
    """HMAC 密钥由主指纹派生 → 记录拷到别的机器上验不过（spec §5.2）。"""
    st.write(FP, _rec())
    res = st.read(OTHER_FP)
    assert res.tampered is True
    assert res.record is None


# ---- 判定边界四态（spec §5.3.1，本设计的要害）----

def test_all_absent_is_first_run(st):
    res = st.read(FP)
    assert res.exists is False
    assert res.tampered is False


def test_all_present_but_invalid_is_tamper_not_reset(st, loc):
    """三处都在、都验不过 → 判篡改，**绝不重置试用期**。

    这一条要是实现成「有效记录为空 = 首次运行」，用户把 JSON 改坏就能重置
    试用期，整套防重置机制当场失效。
    """
    st.write(FP, _rec(trial_start=1000, last_seen=2000))
    for p in (loc.program_data, loc.user_file):
        obj = json.loads(p.read_text(encoding="utf-8"))
        obj["trial_start"] = 1                      # 改一个字节，HMAC 就对不上
        p.write_text(json.dumps(obj), encoding="utf-8")
    res = st.read(FP)
    assert res.exists is True
    assert res.valid is False
    assert res.tampered is True
    assert res.record is None


def test_unknown_version_is_treated_as_absent(st, loc):
    """将来升级到 v2 时，v1 记录不能被判成篡改——否则用户一升级就被锁死。"""
    st.write(FP, _rec())
    for p in (loc.program_data, loc.user_file):
        obj = json.loads(p.read_text(encoding="utf-8"))
        obj["v"] = 2
        p.write_text(json.dumps(obj), encoding="utf-8")
    res = st.read(FP)
    assert res.tampered is False
    assert res.record is None


def test_broken_json_is_treated_as_absent(st, loc):
    st.write(FP, _rec())
    loc.program_data.write_text("{不是 JSON", encoding="utf-8")
    loc.user_file.write_text("", encoding="utf-8")
    assert st.read(FP).tampered is False


def test_missing_field_is_treated_as_absent(st, loc):
    st.write(FP, _rec())
    obj = json.loads(loc.user_file.read_text(encoding="utf-8"))
    del obj["licenses"]
    loc.user_file.write_text(json.dumps(obj), encoding="utf-8")
    loc.program_data.write_text("{}", encoding="utf-8")
    assert st.read(FP).tampered is False


# ---- 写失败 / 指纹缓存 ----

def test_write_failure_is_silent_and_other_slots_still_work(tmp_path):
    """ProgramData 无权限时静默跳过，剩两处照常工作（spec §5.1）。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("我是文件不是目录", encoding="utf-8")
    loc = store.Locations(registry=None,
                          program_data=blocker / "license.dat",
                          user_file=tmp_path / ".roklicense")
    st = store.Store(loc)
    st.write(FP, _rec())                       # 不抛
    assert loc.user_file.exists()
    assert st.read(FP).valid is True


def test_cached_fp_main_returns_full_fingerprint(st):
    assert st.cached_fp_main() is None
    st.write(FP, _rec())
    assert st.cached_fp_main() == FP           # 完整 32 字节，不是摘要


def test_cached_fp_main_ignores_broken_records(st, loc):
    loc.user_file.write_text("{坏的", encoding="utf-8")
    assert st.cached_fp_main() is None


def test_newest_mtime(st, loc):
    assert st.newest_mtime() is None
    st.write(FP, _rec())
    assert st.newest_mtime() is not None


# ---- 注册表那一处（真跑一次）----

@pytest.mark.skipif(os.name != "nt", reason="注册表是 Windows 专有")
def test_registry_slot_roundtrip(tmp_path):
    """注册表是「重新解压清不掉」的关键，必须真跑一次。

    用临时键名并在 finally 里删掉，不碰真实授权记录。
    """
    import winreg
    path = rf"Software\RoKAssistant\_pytest_{os.getpid()}"
    try:
        loc = store.Locations(registry=(path, "state"), program_data=None,
                              user_file=tmp_path / ".roklicense")
        st = store.Store(loc)
        st.write(FP, _rec(trial_start=1234))
        assert st.read(FP).record.trial_start == 1234
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass
