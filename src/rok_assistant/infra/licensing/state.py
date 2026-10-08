"""授权状态计算：试用起点 / 到期日 / 永久 / 已用 serial。

**到期日不落盘**，每次启动从 `licenses` 里的签名激活码现算（spec §5.2.1）。
伪造它需要**私钥**，而不只是 HMAC 密钥——HMAC 密钥 = SHA256(主指纹 + 固定
salt)，主指纹的输入全在用户自己的机器上，理论上算得出来；私钥则永远只在
发码端。所以「到期日现算」比「到期日落盘 + HMAC」严格更强。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

from . import codec, verify
from .store import Record

TRIAL_DAYS = 30                    # **代码常量，绝不进 config.yaml**（spec §5.5）
TAMPER_TOLERANCE_SECONDS = 24 * 3600
_SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class Evaluation:
    kind: str                      # "trial" | "licensed" | "permanent" | "expired"
    expiry: date | None
    days_left: int | None


def effective_now(now: int, last_seen: int) -> int:
    """把系统时间调回过去不给任何好处（spec §5.4）。"""
    return max(int(now), int(last_seen))


def clock_rolled_back(now: int, last_seen: int) -> bool:
    """回拨超过 24h 容差 → 判篡改。

    24h 容差是为了不误伤时区 / 夏令时 / NTP 微调 / 用户手动校时。
    """
    return int(now) < int(last_seen) - TAMPER_TOLERANCE_SECONDS


def _to_date(ts: int) -> date:
    return datetime.fromtimestamp(ts).date()


def evaluate(*, trial_start: int, last_seen: int, licenses: list[dict],
             fp_main: bytes, now: int,
             public_key_b64: str | None = None) -> Evaluation:
    expiry_ts = int(trial_start) + TRIAL_DAYS * _SECONDS_PER_DAY
    applied = False

    # 按 serial 升序累加：否则「先加 30 再加 7」与「先加 7 再加 30」在已过期
    # 的边界上结果不同，而记录合并（store._merge）后列表顺序可能变（spec §7.2）。
    entries: list[tuple[int, dict]] = []
    for item in licenses:
        serial = codec.serial_of(item["code"])
        entries.append((-1 if serial is None else serial, item))
    entries.sort(key=lambda t: t[0])

    for _serial, item in entries:
        payload, _reason = verify.verify_code(item["code"], fp_main,
                                              public_key_b64)
        if payload is None:
            continue                  # 验签失败 → 丢弃，不给时间
        if payload["kind"] == codec.KIND_PERMANENT:
            return Evaluation("permanent", None, None)
        applied = True
        # applied_at 被 last_seen 夹住：改大占不到便宜，改小也没用（spec §5.2.1）
        base = max(expiry_ts, min(int(item["applied_at"]), int(last_seen)))
        expiry_ts = base + int(payload["days"]) * _SECONDS_PER_DAY

    if int(now) >= expiry_ts:
        return Evaluation("expired", _to_date(expiry_ts), 0)
    days_left = math.ceil((expiry_ts - int(now)) / _SECONDS_PER_DAY)
    return Evaluation("licensed" if applied else "trial",
                      _to_date(expiry_ts), days_left)


def apply_activation(rec: Record, *, code_text: str, payload: dict,
                     now: int, last_seen: int) -> Record:
    """把一条**已验签**的码并入记录。幂等：serial 已在列表里则原样返回。

    幂等是刻意的——用户可能重复购买，报错会引发售后（spec §7.3）。
    `applied_at` 记激活当时的 `effective_now`；计算到期日时它会被
    `last_seen` 夹住，所以这里不需要额外钳制。
    """
    serial = payload["serial"]
    for item in rec.licenses:
        if codec.serial_of(item["code"]) == serial:
            return rec
    return Record(trial_start=rec.trial_start,
                  last_seen=rec.last_seen,
                  licenses=list(rec.licenses) + [{"code": code_text,
                                                  "applied_at": int(now)}])


def used_serials(rec: Record, fp_main: bytes,
                 public_key_b64: str | None = None) -> set[int]:
    """已用过的 serial 集合——防「一个延长码反复输入无限续期」（spec §7.3）。

    只统计**验签通过**的码：验不过的本来就加不上时间，没必要占着 serial
    把用户后来的真码拒掉。
    """
    out: set[int] = set()
    for item in rec.licenses:
        payload, _reason = verify.verify_code(item["code"], fp_main,
                                              public_key_b64)
        if payload is not None:
            out.add(payload["serial"])
    return out
