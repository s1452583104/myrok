"""激活码编解码：base32 无填充 + 5 字符分组 + 输入清洗。纯标准库。

布局（spec §6.1）：

    code_bytes = payload(12) + signature(64) = 76 字节
    code       = base32_nopad(code_bytes)     = 122 字符

签名**必须是完整的 64 字节**：Ed25519 验签要算 [S]B == R + [k]A，
R 与 S 都不能截断（spec §6.2）。本模块只负责编解码，不验签。
"""
from __future__ import annotations

import base64
import binascii
import struct

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

PAYLOAD_BYTES = 12
SIG_BYTES = 64
CODE_BYTES = PAYLOAD_BYTES + SIG_BYTES     # 76
CODE_CHARS = 122                            # ceil(76 * 8 / 5)
GROUP_SIZE = 5

FORMAT_VERSION = 0x01
KIND_EXTEND = 0x01
KIND_PERMANENT = 0x02

# 用户粘贴时最常见的四种误抄字符。它们**不在** RFC4648 字母表
# （A-Z2-7）里，所以映射不会和任何合法字符冲突，是无损的。
_CONFUSION = {"0": "O", "1": "I", "8": "B", "9": "G"}

# ver(1) + fp_main 前 6 字节(6) + kind(1) + days(2) + serial(2) = 12
_PAYLOAD_FMT = ">B6sBHH"

_STRIPPED = "- \t\r\n"


def clean_input(text: str) -> str:
    """转大写、去空白与连字符、映射易混字符。非字母表字符原样保留。"""
    out = []
    for ch in (text or ""):
        if ch in _STRIPPED:
            continue
        out.append(_CONFUSION.get(ch, ch.upper()))
    return "".join(out)


def format_code(text: str) -> str:
    """清洗后按 5 字符一组显示（122 字符 → 25 组）。"""
    clean = clean_input(text)
    return "-".join(clean[i:i + GROUP_SIZE]
                    for i in range(0, len(clean), GROUP_SIZE))


def b32encode_nopad(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=")


def b32decode_nopad(text: str) -> bytes:
    # b32decode 要求长度是 8 的倍数，补回被 rstrip 掉的填充
    return base64.b32decode(text + "=" * ((-len(text)) % 8))


def build_payload(*, ver: int, fp_main: bytes, kind: int, days: int,
                  serial: int) -> bytes:
    if len(fp_main) < 6:
        raise ValueError(f"主指纹不足 6 字节：{len(fp_main)}")
    return struct.pack(_PAYLOAD_FMT, ver, bytes(fp_main[:6]), kind, days, serial)


def parse_payload(payload: bytes) -> dict:
    if len(payload) != PAYLOAD_BYTES:
        raise ValueError(f"payload 长度应为 {PAYLOAD_BYTES}，实际 {len(payload)}")
    ver, fp6, kind, days, serial = struct.unpack(_PAYLOAD_FMT, payload)
    if kind not in (KIND_EXTEND, KIND_PERMANENT):
        raise ValueError(f"未知的授权类型 {kind}")
    return {"ver": ver, "fp6": fp6, "kind": kind, "days": days, "serial": serial}


def encode_code(payload: bytes, signature: bytes) -> str:
    """返回未分组的 122 字符；显示时再过 `format_code()`。"""
    if len(payload) != PAYLOAD_BYTES:
        raise ValueError(f"payload 长度应为 {PAYLOAD_BYTES}，实际 {len(payload)}")
    if len(signature) != SIG_BYTES:
        raise ValueError(f"签名长度应为 {SIG_BYTES}，实际 {len(signature)}")
    return b32encode_nopad(payload + signature)


def split_code(text: str) -> tuple[bytes, bytes]:
    """清洗 → 校验长度 → base32 解码 → 切成 (payload, signature)。

    任何一步不合法都抛 `ValueError`；调用方统一映射成
    「激活码格式不正确」（spec §6.4）。
    """
    clean = clean_input(text)
    if len(clean) != CODE_CHARS:
        raise ValueError(f"激活码长度应为 {CODE_CHARS} 字符，实际 {len(clean)}")
    try:
        raw = b32decode_nopad(clean)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"激活码包含非法字符：{e}") from e
    if len(raw) != CODE_BYTES:
        raise ValueError(f"解码后长度应为 {CODE_BYTES}，实际 {len(raw)}")
    return raw[:PAYLOAD_BYTES], raw[PAYLOAD_BYTES:]


def serial_of(code_text: str) -> int | None:
    """**不验签**，只取 serial。

    用途有两个：记录合并时按 serial 去重、计算到期日时按 serial 排序
    （spec §5.3 / §7.2）。不验签是安全的——验不过的条目稍后一律丢弃，
    排序结果只影响丢弃顺序。解析失败返回 None。
    """
    try:
        payload, _ = split_code(code_text)
        return parse_payload(payload)["serial"]
    except ValueError:
        return None
