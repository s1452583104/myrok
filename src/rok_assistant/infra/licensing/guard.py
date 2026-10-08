"""授权门面：GUI 与 worker **只认这个模块**。

这是唯一的接缝——测试可以整体替换它（`_set_guard_for_tests`），实现改动
也不会渗到界面代码里。

**不提供环境变量旁路**：`ROK_LICENSE_OFF=1` 这种开关用户一样能设，等于送
一个一键破解，宁可不留（spec §8.2）。测试隔离走依赖注入。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import date

from ..logger import get_logger
from . import codec
from . import fingerprint as fp_mod
from . import state
from . import store as store_mod
from . import verify

logger = get_logger(__name__)


@dataclass(frozen=True)
class LicenseStatus:
    kind: str                     # "trial" | "licensed" | "permanent" | "expired"
    expiry: date | None
    days_left: int | None
    machine_code: str

    @property
    def allows_run(self) -> bool:
        return self.kind != "expired"

    def label(self) -> str:
        """状态栏常驻标签的文案。"""
        if self.kind == "permanent":
            return "永久授权"
        if self.kind == "expired":
            return "试用已结束，请输入激活码"
        if self.kind == "licensed":
            return f"已授权，剩余 {self.days_left} 天"
        return f"试用剩余 {self.days_left} 天"


class Guard:
    def __init__(self, store, fp, clock=time.time, public_key_b64=None):
        self._store = store
        self._fp = fp
        self._clock = clock
        # 生产恒为 None → 用内嵌 shipped 公钥；测试注入固定测试公钥。
        # 与 verify / state 里那几个函数的同名参数是同一个形状（spec §8.2 的
        # 「测试隔离走依赖注入」）。
        self._key = public_key_b64

    def machine_code(self) -> str:
        return self._fp.machine_code

    def _expired(self) -> LicenseStatus:
        return LicenseStatus("expired", None, None, self._fp.machine_code)

    def _mtime_in_future(self, now: int) -> bool:
        """交叉校验：任一存储文件的 mtime 比当前时间晚 24h 以上（spec §5.4）。"""
        newest = self._store.newest_mtime()
        return newest is not None and newest > now + state.TAMPER_TOLERANCE_SECONDS

    def status(self) -> LicenseStatus:
        now = int(self._clock())
        fp = self._fp.fp_main
        # 必须在 read() 之前采样：read() 会把合并后的记录补写回三处，
        # 那次写入会把每个文件的 mtime 刷成当前时间，之后再看就永远是
        # 「不在未来」——spec §5.4 的 mtime 交叉校验会变成死代码。
        mtime_future = self._mtime_in_future(now)
        res = self._store.read(fp)

        if res.tampered:
            logger.warning("授权记录判定为篡改，状态强制为 expired")
            return self._expired()

        rec = res.record
        if rec is None:
            # 三处都不存在 → 首次运行，试用起点就是现在
            rec = store_mod.Record(trial_start=now, last_seen=now, licenses=[])
            self._store.write(fp, rec)

        if state.clock_rolled_back(now, rec.last_seen) or mtime_future:
            logger.warning("时钟回拨超过容差，判定为篡改")
            return self._expired()

        eff = state.effective_now(now, rec.last_seen)
        if eff != rec.last_seen:               # last_seen 只增不减
            rec = replace(rec, last_seen=eff)
            self._store.write(fp, rec)

        ev = state.evaluate(trial_start=rec.trial_start, last_seen=rec.last_seen,
                            licenses=rec.licenses, fp_main=fp, now=eff,
                            public_key_b64=self._key)
        return LicenseStatus(ev.kind, ev.expiry, ev.days_left,
                             self._fp.machine_code)

    def activate(self, code_text: str) -> tuple[bool, str]:
        now = int(self._clock())
        fp = self._fp.fp_main
        res = self._store.read(fp)

        if res.tampered:
            # 记录被判篡改时**不能**拿 now 当 trial_start 新建记录——那正是
            # 「把记录改坏即可重置试用期」这条路径。从 epoch 起算：试用永久
            # 结束，但用户买的码照常生效（base = max(epoch+30d, applied_at)）。
            rec = store_mod.Record(trial_start=0, last_seen=now, licenses=[])
        else:
            rec = res.record or store_mod.Record(trial_start=now, last_seen=now,
                                                 licenses=[])

        # 时钟回拨**不拦激活**：主板电池没电的用户会被误判篡改，但必须还能
        # 靠买码自救（spec §12 已知局限 4）。effective_now 已经保证回拨不给好处。
        eff = state.effective_now(now, rec.last_seen)
        payload, reason = verify.check_code(code_text, fp,
                                            state.used_serials(rec, fp, self._key),
                                            self._key)
        if payload is None:
            return False, reason

        merged = state.apply_activation(rec,
                                        code_text=codec.clean_input(code_text),
                                        payload=payload, now=eff,
                                        last_seen=rec.last_seen)
        merged = replace(merged, last_seen=eff)
        self._store.write(fp, merged)
        logger.info("激活成功：kind=%s serial=%s", payload["kind"],
                    payload["serial"])
        return True, "激活成功"


_guard: Guard | None = None


def build_default_guard() -> Guard:
    st = store_mod.Store(store_mod.default_locations())
    # 先读记录里的指纹缓存，再算 WMI——顺序见 spec §4.4
    return Guard(st, fp_mod.compute(cached_fp_main=st.cached_fp_main()))


def current_guard() -> Guard:
    """进程内单例。**第一次调用**才去查 WMI（冻结包里 1~2s），所以启动
    路径只查一次。"""
    global _guard
    if _guard is None:
        _guard = build_default_guard()
    return _guard


def _set_guard_for_tests(g: Guard | None) -> None:
    """测试专用：整体替换门面。**刻意不提供环境变量旁路**（spec §8.2）。"""
    global _guard
    _guard = g
