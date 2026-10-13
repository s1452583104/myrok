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

# 试用期天数：**代码常量，绝不进 config.yaml**（spec §5.5）——配置是用户能直接
# 编辑的文本文件，放进去等于送一个「一键改试用期」的开关。
# 打包时可用 `tools/build_package.py --trial-days N` 注入：构建脚本在 PyInstaller
# 之前生成下面这个模块（生成物，.gitignore 忽略），源码运行 / 未指定时走默认 30。
try:
    from ._trial_override import TRIAL_DAYS
except ImportError:
    # 只吞 ImportError：文件不存在=没注入，用默认值。文件存在但坏了（语法错等）
    # **照常抛**——静默退回 30 会把试用期变长，是反向失效。
    TRIAL_DAYS = 30

_SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class Evaluation:
    kind: str                      # "trial" | "licensed" | "permanent" | "expired"
    expiry: date | None
    days_left: int | None


def effective_now(now: int, last_seen: int) -> int:
    """把系统时间调回过去不给任何好处（spec §5.4）。

    **只此一条**：回拨本身不再判篡改（2026-11-01 改，见 spec §5.4）——到期日是
    绝对日期、`applied_at` 又被 `last_seen` 夹住，所以「不给好处」已经足够，
    判死只会误伤（而且会把记录锚点钉在未来，真实时间追上前连买码都救不回来）。
    """
    return max(int(now), int(last_seen))


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

    幂等是刻意的——用户可能重复购买，报错会引发售后（spec §7.3）。**防重放
    就靠这一条**：同一个 serial 加不上第二次时间（没有别的地方拦「已用过的
    serial」，`verify` 只管解码/验签/比对本机，见 spec §6.4）。
    `applied_at` 记激活当时的 `effective_now`；计算到期日时它会被
    `last_seen` 夹住，所以这里不需要额外钳制。

    去重用的是 `codec.serial_of`（**不验签**）：伪造条目要先有记录里的 HMAC
    密钥（已知局限 3），而伪造的后果只是自己那条 serial 占位、加不上真码——
    伤不到别人，不值得为它每次激活都多验一遍签。
    """
    serial = payload["serial"]
    for item in rec.licenses:
        if codec.serial_of(item["code"]) == serial:
            return rec
    return Record(trial_start=rec.trial_start,
                  last_seen=rec.last_seen,
                  licenses=list(rec.licenses) + [{"code": code_text,
                                                  "applied_at": int(now)}])
    return out
