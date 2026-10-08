import pytest

from rok_assistant.infra.licensing import codec


def test_code_length_constants_match_spec():
    # 12 字节 payload + 64 字节完整 Ed25519 签名 = 76 字节 → 122 个 base32 字符
    assert codec.PAYLOAD_BYTES == 12
    assert codec.SIG_BYTES == 64
    assert codec.CODE_BYTES == 76
    assert codec.CODE_CHARS == 122


def test_payload_roundtrip():
    payload = codec.build_payload(ver=codec.FORMAT_VERSION,
                                  fp_main=bytes(range(32)),
                                  kind=codec.KIND_EXTEND, days=30, serial=7)
    assert len(payload) == codec.PAYLOAD_BYTES
    parsed = codec.parse_payload(payload)
    assert parsed["ver"] == codec.FORMAT_VERSION
    assert parsed["fp6"] == bytes(range(6))       # 只带前 6 字节
    assert parsed["kind"] == codec.KIND_EXTEND
    assert parsed["days"] == 30
    assert parsed["serial"] == 7


def test_code_roundtrip():
    payload = codec.build_payload(ver=codec.FORMAT_VERSION, fp_main=b"\x11" * 32,
                                  kind=codec.KIND_PERMANENT, days=0, serial=99)
    signature = bytes(range(64))
    code = codec.encode_code(payload, signature)
    assert len(code) == codec.CODE_CHARS
    got_payload, got_sig = codec.split_code(code)
    assert got_payload == payload
    assert got_sig == signature


def test_format_code_groups_by_five():
    code = "A" * codec.CODE_CHARS
    formatted = codec.format_code(code)
    groups = formatted.split("-")
    # 122 不能被 5 整除：ceil(122/5)=25 组，前 24 组各 5 字符，最后一组剩 2 字符
    assert len(groups) == -(-codec.CODE_CHARS // codec.GROUP_SIZE)   # 25 组
    assert all(len(g) == codec.GROUP_SIZE for g in groups[:-1])
    assert len(groups[-1]) == codec.CODE_CHARS % codec.GROUP_SIZE    # 2


def test_clean_input_strips_and_confuses():
    # 用户粘贴时常被输入法/字体换成 0/1/8/9；这四个字符不在 RFC4648
    # 字母表（A-Z2-7）里，所以映射是无损的
    assert codec.clean_input("ab-cd ef") == "ABCDEF"
    assert codec.clean_input("0189") == "OIBG"
    assert codec.clean_input("0-1-8-9") == "OIBG"


def test_format_code_is_reversible_by_clean_input():
    payload = codec.build_payload(ver=codec.FORMAT_VERSION, fp_main=b"\x02" * 32,
                                  kind=codec.KIND_EXTEND, days=1, serial=1)
    code = codec.encode_code(payload, b"\x03" * 64)
    assert codec.clean_input(codec.format_code(code)) == code


def test_split_code_rejects_wrong_length():
    with pytest.raises(ValueError):
        codec.split_code("ABC")


def test_split_code_rejects_illegal_chars():
    # '1' 会被清洗成 'I' 合法；'!' 与 '@' 不在 RFC4648 字母表（A-Z2-7）里，
    # 必须拒绝。注意 'L' 是合法 base32 字符（A-Z 全含），不能拿来当非法样本。
    with pytest.raises(ValueError):
        codec.split_code("!" * codec.CODE_CHARS)
    with pytest.raises(ValueError):
        codec.split_code("@" * codec.CODE_CHARS)


def test_parse_payload_rejects_unknown_kind():
    payload = codec.build_payload(ver=codec.FORMAT_VERSION, fp_main=b"\x00" * 32,
                                  kind=0x7F, days=1, serial=1)
    with pytest.raises(ValueError):
        codec.parse_payload(payload)


def test_build_payload_rejects_short_fingerprint():
    with pytest.raises(ValueError):
        codec.build_payload(ver=codec.FORMAT_VERSION, fp_main=b"\x00" * 3,
                            kind=codec.KIND_EXTEND, days=1, serial=1)


def test_serial_of_returns_none_on_garbage():
    assert codec.serial_of("不是激活码") is None
    payload = codec.build_payload(ver=codec.FORMAT_VERSION, fp_main=b"\x05" * 32,
                                  kind=codec.KIND_EXTEND, days=3, serial=42)
    assert codec.serial_of(codec.encode_code(payload, b"\x00" * 64)) == 42
