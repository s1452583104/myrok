from __future__ import annotations
import threading
import time
from dataclasses import dataclass


@dataclass
class ActionLedgerEntry:
    """单个角色的「我做过什么」记录。全字段默认 = 尚无记录。"""
    troops_out: bool = False
    troops_out_since: float = 0.0
    last_rally_launched_ts: float = 0.0
    last_fill_ts: float = 0.0
    written: bool = False


class ActionLedger:
    """进程级动作账本：按 char_id 记录「我做过什么」，跨 SM 重建存活。

    为什么必须是进程级：WorkerRunner 在每轮终态后会重建状态机
    （runner.py 的 sm_factory），账本若挂在 SM 上就随重建清空，集结
    门槛的 L0 准入判据会退化成「每轮开头一律认为部队在家」，把
    rally_rejected 又放回来。旧 RallyEventTracker 做成进程级也是同一个
    原因，它是被本账本取代的。

    `written` 单独记，是为了区分「我知道我在家」和「我什么都不知道」：
    前者可以立刻放行搜索，后者必须沿用 fail-closed 的旧行为（进程刚起、
    或换了账号，账本里没有任何依据）。

    **写入约束**：只在动作**已确认生效**后调用。写不进去（点击未确认）
    就不写——账本的全部价值在于「它是已知事实」，一旦掺入猜测就退化回
    像素判据，那正是这次要消掉的东西。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[str, ActionLedgerEntry] = {}

    def _get(self, char_id: str) -> ActionLedgerEntry:
        # 调用方持锁
        e = self._entries.get(char_id)
        if e is None:
            e = ActionLedgerEntry()
            self._entries[char_id] = e
        return e

    def mark_troops_out(self, char_id: str, now: float | None = None) -> None:
        """部队已确认出城（行军点击生效）。"""
        ts = time.time() if now is None else now
        with self._lock:
            e = self._get(char_id)
            e.troops_out = True
            e.troops_out_since = ts
            e.written = True

    def mark_troops_home(self, char_id: str, now: float | None = None) -> None:
        """部队已确认回城（派遣队列判空）。"""
        with self._lock:
            e = self._get(char_id)
            e.troops_out = False
            e.troops_out_since = 0.0
            e.written = True

    def mark_rally_launched(self, char_id: str, now: float | None = None) -> None:
        ts = time.time() if now is None else now
        with self._lock:
            e = self._get(char_id)
            e.last_rally_launched_ts = ts
            e.written = True

    def mark_fill_done(self, char_id: str, now: float | None = None) -> None:
        ts = time.time() if now is None else now
        with self._lock:
            e = self._get(char_id)
            e.last_fill_ts = ts
            e.written = True

    def has_record(self, char_id: str) -> bool:
        with self._lock:
            return self._get(char_id).written

    def troops_out(self, char_id: str) -> bool:
        with self._lock:
            return self._get(char_id).troops_out

    def troops_out_seconds(self, char_id: str, now: float | None = None) -> float:
        """部队在外已持续秒数；不在外返回 0.0。"""
        ts = time.time() if now is None else now
        with self._lock:
            e = self._get(char_id)
            if not e.troops_out:
                return 0.0
            return max(0.0, ts - e.troops_out_since)

    def snapshot(self, char_id: str) -> ActionLedgerEntry:
        """当前值的一份副本（GUI / 排查用），改它不影响内部状态。"""
        with self._lock:
            e = self._get(char_id)
            return ActionLedgerEntry(**vars(e))
