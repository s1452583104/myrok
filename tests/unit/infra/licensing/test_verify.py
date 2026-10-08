from rok_assistant.infra.licensing import codec, verify

FP = bytes(range(32))
OTHER_FP = bytes(range(100, 132))


def test_valid_code_passes(sign_code, test_public_b64):
    code = sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=1)
    payload, reason = verify.verify_code(code, FP, test_public_b64)
    assert reason is None
    assert payload["days"] == 30
    assert payload["serial"] == 1


def test_tampered_payload_fails_signature(test_private_seed, test_public_b64):
    """改 payload 后签名对不上——这是签名真正要挡的攻击。"""
    good = codec.build_payload(ver=codec.FORMAT_VERSION, fp_main=FP,
                               kind=codec.KIND_EXTEND, days=30, serial=1)
    signature = verify.sign_payload(good, test_private_seed)
    evil = codec.build_payload(ver=codec.FORMAT_VERSION, fp_main=FP,
                               kind=codec.KIND_EXTEND, days=3650, serial=1)
    code = codec.encode_code(evil, signature)
    payload, reason = verify.verify_code(code, FP, test_public_b64)
    assert payload is None
    assert reason == verify.REASON_BAD_SIG


def test_code_for_other_machine_fails(sign_code, test_public_b64):
    code = sign_code(OTHER_FP, kind=codec.KIND_EXTEND, days=30, serial=2)
    payload, reason = verify.verify_code(code, FP, test_public_b64)
    assert payload is None
    assert reason == verify.REASON_WRONG_MACHINE


def test_garbage_input_reports_format(test_public_b64):
    payload, reason = verify.verify_code("随便一串字", FP, test_public_b64)
    assert payload is None
    assert reason == verify.REASON_FORMAT


def test_wrong_format_version_reports_format(test_private_seed, test_public_b64):
    payload_bytes = codec.build_payload(ver=0x02, fp_main=FP,
                                        kind=codec.KIND_EXTEND, days=1, serial=3)
    code = codec.encode_code(payload_bytes,
                             verify.sign_payload(payload_bytes, test_private_seed))
    payload, reason = verify.verify_code(code, FP, test_public_b64)
    assert payload is None
    assert reason == verify.REASON_FORMAT


def test_check_code_rejects_used_serial(sign_code, test_public_b64):
    code = sign_code(FP, kind=codec.KIND_EXTEND, days=30, serial=5)
    payload, reason = verify.check_code(code, FP, {5}, test_public_b64)
    assert payload is None
    assert reason == verify.REASON_USED
    payload, reason = verify.check_code(code, FP, {6}, test_public_b64)
    assert reason is None


def test_check_code_still_reports_format_before_serial(sign_code, test_public_b64):
    _, reason = verify.check_code("坏的", FP, {5}, test_public_b64)
    assert reason == verify.REASON_FORMAT


def test_embedded_public_key_loads():
    """内嵌公钥必须能加载，且是 32 字节的 Ed25519 公钥。

    这是冻结包最容易出问题的地方（cryptography 的 C 扩展没打进去），
    单测在这里兜一道底。
    """
    from rok_assistant.infra.licensing import pubkey
    assert pubkey.PUBLIC_KEY_B64
    key = verify.load_public_key()
    assert key is not None
    import base64
    assert len(base64.b64decode(pubkey.PUBLIC_KEY_B64)) == 32
