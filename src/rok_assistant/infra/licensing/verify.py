"""Ed25519 验签与四步校验的提示语。

本模块是**唯一**依赖 `cryptography` 的地方——绿色包最容易在这里缺东西，
`--selftest` 的「授权链自检」专门盯它。

四步校验的粒度是刻意的（spec §6.4）：必须给用户粗粒度原因，否则无法自助。
区分「无效」和「与本机不匹配」不泄露任何东西——用户拿到别人的真码也照样用不了。
"""
from __future__ import annotations

import base64
import functools

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from . import codec
from .pubkey import PUBLIC_KEY_B64

REASON_FORMAT = "激活码格式不正确"
REASON_BAD_SIG = "激活码无效"
REASON_WRONG_MACHINE = "激活码与本机不匹配"
REASON_USED = "该激活码已被使用"


@functools.lru_cache(maxsize=8)
def load_public_key(b64: str | None = None) -> Ed25519PublicKey:
    """`b64=None` 用内嵌公钥；测试传固定测试公钥。"""
    raw = base64.b64decode(b64 if b64 is not None else PUBLIC_KEY_B64)
    return Ed25519PublicKey.from_public_bytes(raw)


def sign_payload(payload: bytes, private_key_bytes: bytes) -> bytes:
    """**仅发码端与测试**用；客户端只验签、不签。"""
    return Ed25519PrivateKey.from_private_bytes(private_key_bytes).sign(payload)


def verify_code(code_text: str, fp_main: bytes,
                public_key_b64: str | None = None
                ) -> tuple[dict | None, str | None]:
    """前三步：解码 → 验签 → 比对本机指纹。

    返回 `(payload, None)` 或 `(None, 原因)`。
    """
    try:
        payload_bytes, signature = codec.split_code(code_text)
        payload = codec.parse_payload(payload_bytes)
    except ValueError:
        return None, REASON_FORMAT
    if payload["ver"] != codec.FORMAT_VERSION:
        return None, REASON_FORMAT
    try:
        load_public_key(public_key_b64).verify(signature, payload_bytes)
    except InvalidSignature:
        return None, REASON_BAD_SIG
    if payload["fp6"] != bytes(fp_main[:6]):
        return None, REASON_WRONG_MACHINE
    return payload, None


def check_code(code_text: str, fp_main: bytes, used_serials,
               public_key_b64: str | None = None
               ) -> tuple[dict | None, str | None]:
    """四步：`verify_code` + serial 未用过。

    防重放是「一个延长码反复输入无限续期」的唯一手段（spec §7.3）。
    """
    payload, reason = verify_code(code_text, fp_main, public_key_b64)
    if payload is None:
        return None, reason
    if payload["serial"] in set(used_serials):
        return None, REASON_USED
    return payload, None
