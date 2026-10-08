import inspect

from rok_assistant.infra import selftest


def test_license_status_detail_reports_machine_code():
    """用户报障时直接抄这一行给作者。"""
    detail = selftest._license_status_detail()
    assert "机器码=" in detail
    assert "状态=trial" in detail          # autouse fixture 给了全新试用


def test_license_status_detail_does_not_block_when_expired():
    """诊断工具被授权挡住反而查不了问题——**不做拦截**（spec §8.3）。"""
    from rok_assistant.infra.licensing import guard as guard_mod
    original = guard_mod.current_guard()
    try:
        guard_mod._set_guard_for_tests(_ExpiredStub())
        assert "状态=expired" in selftest._license_status_detail()
    finally:
        guard_mod._set_guard_for_tests(original)


class _ExpiredStub:
    def status(self):
        from rok_assistant.infra.licensing import guard as guard_mod
        return guard_mod.LicenseStatus("expired", None, None, "AAAA-BBBB-CCCC-DDDD-E")


def test_license_chain_detail_passes():
    """冻结包里 cryptography 缺东西的表现是「所有激活码都无效」，极难远程排查。"""
    detail = selftest._license_chain_detail()
    assert "签名往返 OK" in detail
    assert "内嵌公钥可加载" in detail


def test_selftest_registers_the_two_licensing_checks():
    """只查源码文本，**不调用 `_run_checks()`**——那会跑完整的重链路
    （cv2 / onnxruntime / rapidocr / MuMu 诊断），不是单测该干的事。
    """
    src = inspect.getsource(selftest._run_checks)
    assert '"授权状态与机器码"' in src
    assert '"授权链自检"' in src
