from rok_assistant.infra.licensing import codec, fingerprint

MB = "03000200-0400-0500-0006-000700080009"
CPU = "BFEBFBFF000306A9"


def test_normalize_is_deterministic():
    assert fingerprint.normalize("  ab-cd  ") == "ABCD"
    assert fingerprint.normalize("ab cd") == "ABCD"
    assert fingerprint.normalize("0x1a2b") == "1A2B"
    assert fingerprint.normalize("") == ""


def test_normalize_pads_odd_length():
    # 奇数长度补零，避免 "ABC" 与 "0ABC" 算出两个不同指纹
    assert fingerprint.normalize("ABC") == "0ABC"
    assert fingerprint.normalize("0ABC") == "0ABC"


def test_fp_main_is_32_bytes_and_deterministic():
    a = fingerprint.fp_main_from(MB, CPU)
    b = fingerprint.fp_main_from("03000200040005000006000700080009", CPU)
    assert len(a) == 32
    assert a == b          # 大小写/连字符/0x 归一化后必须同值


def test_fp_main_changes_when_hardware_changes():
    assert fingerprint.fp_main_from(MB, CPU) != fingerprint.fp_main_from(MB, "DEADBEEF")


def test_machine_code_shape():
    fp = fingerprint.fp_main_from(MB, CPU)
    mc = fingerprint.machine_code_from(fp)
    groups = mc.split("-")
    assert len(groups) == 5
    assert [len(g) for g in groups] == [4, 4, 4, 4, 1]
    assert all(c in codec.ALPHABET for g in groups for c in g)


def test_machine_code_check_char_catches_typo():
    """手抄错一位 → 校验字符对不上（这是给人工环节兜底的）。

    校验字符只吃前 10 字节，所以**光凭这 17 个字符就能验**——
    发码工具正是靠这一点在发码前拦住抄错的机器码（spec §9）。
    """
    fp = fingerprint.fp_main_from(MB, CPU)
    mc = fingerprint.machine_code_from(fp)
    assert fingerprint.is_valid_machine_code(mc)
    body = codec.clean_input(mc)
    typo = ("B" if body[0] != "B" else "C") + body[1:]
    assert not fingerprint.is_valid_machine_code(
        f"{typo[:4]}-{typo[4:8]}-{typo[8:12]}-{typo[12:16]}-{body[16]}")


def test_is_valid_machine_code_rejects_garbage():
    assert not fingerprint.is_valid_machine_code("")
    assert not fingerprint.is_valid_machine_code("ABC")
    assert not fingerprint.is_valid_machine_code("A" * 17)


def test_compute_uses_wmi_when_available():
    fp = fingerprint.compute(wmi_runner=lambda: (MB, CPU))
    assert fp.degraded is False
    assert fp.fp_main == fingerprint.fp_main_from(MB, CPU)


def test_compute_prefers_cache_when_wmi_fails():
    """WMI 偶发失败**不能**换指纹——换了会让三处记录全部验不过（spec §4.4）。"""
    cached = fingerprint.fp_main_from(MB, CPU)
    fp = fingerprint.compute(cached_fp_main=cached, wmi_runner=lambda: None)
    assert fp.degraded is True
    assert fp.fp_main == cached


def test_compute_prefers_cache_when_wmi_raises():
    cached = fingerprint.fp_main_from(MB, CPU)
    def boom():
        raise OSError("powershell 不见了")
    fp = fingerprint.compute(cached_fp_main=cached, wmi_runner=boom)
    assert fp.fp_main == cached


def test_compute_falls_back_to_machine_guid_without_cache():
    fp = fingerprint.compute(wmi_runner=lambda: None)
    assert fp.degraded is True
    assert "MachineGuid" in fp.reason
    assert fp.fp_main != fingerprint.fp_main_from(MB, CPU)


def test_compute_ignores_all_F_uuid():
    """部分主板/虚拟机把 UUID 报成全 F——那不是唯一标识，必须降级。"""
    cached = fingerprint.fp_main_from(MB, CPU)
    fp = fingerprint.compute(cached_fp_main=cached,
                             wmi_runner=lambda: ("FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF", CPU))
    assert fp.fp_main == cached


def test_compute_never_raises(monkeypatch):
    """两条路都断掉时也不能抛——启动路径抛异常等于程序打不开。"""
    monkeypatch.setattr(fingerprint, "_machine_guid", lambda: None)
    fp = fingerprint.compute(wmi_runner=lambda: None)
    assert len(fp.fp_main) == 32
    assert fp.degraded is True
