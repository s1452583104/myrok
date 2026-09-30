from __future__ import annotations
import time
from dataclasses import dataclass
from enum import Enum

from ..coordination.action_ledger import ActionLedger

# 连续几帧同结论才采信。3 帧 = 轮询间隔 1s 下多等 2 拍，代价可忽略；
# 收益是干掉「偶发一帧噪声导致整轮判错」。
VOTE_SIZE = 3
# 账本称「部队在外」超过这个时长视为账本本身不可信（例如 WAIT_RETURN
# 那一拍没跑到、或进程被杀在行军中途），放行而不是永久卡死。
LEDGER_STALE_AFTER = 3600.0


class GateDecision(str, Enum):
    PROCEED = "proceed"   # 放行：可以开始搜索
    WAIT = "wait"         # 原地等待：本拍不搜


@dataclass(frozen=True)
class GateOutcome:
    decision: GateDecision
    reason: str           # 人类可读，直接进日志
    verdict: str | None   # 采信后的队列判读；None = 投票尚未采信
    source: str           # 判据来源：vote / ledger / grace


class QueueGate:
    """集结门槛判据（2026-09-30 重构，取代原先的单帧 + 900s 计时器）。

    两级判据，越靠前越不需要看画面：

    L1 多帧投票 —— 连续 VOTE_SIZE 帧同结论才采信，且**只延迟不翻转**。
        battle→none 的误判会开一次注定被游戏拒绝的车（日志里的
        rally_rejected），反向误判只是多等几拍。这个不对称决定了两帧
        不一致时应该「维持上次采信值」而不是「以最新帧为准」。

    L0 账本覆盖 —— 采信值是 unknown 时问 ActionLedger，而不是靠计时器
        赌判据。账本无记录时（进程刚起）退回旧的 fail-closed + 宽限，
        因为那时没有任何已知事实可用。

    `unknown_grace` 因此从「主要出口」降级为「最后兜底」，只在账本
    不可信或压根没有账本时才起作用。
    """

    def __init__(self, ledger: ActionLedger, char_id: str,
                 vote_size: int = VOTE_SIZE,
                 unknown_grace: float = 900.0,
                 ledger_stale_after: float = LEDGER_STALE_AFTER):
        self._ledger = ledger
        self._char_id = char_id
        self._vote_size = vote_size
        self._unknown_grace = unknown_grace
        self._stale_after = ledger_stale_after
        self._recent: list[str] = []
        self._settled: str | None = None
        self._unknown_since: float | None = None

    def observe(self, verdict: str, now: float | None = None) -> GateOutcome:
        """喂入一帧队列判读结论，返回本拍的门槛决策。"""
        ts = time.time() if now is None else now
        self._feed(verdict)
        settled = self._settled

        if settled is None:
            return GateOutcome(
                GateDecision.WAIT,
                f"队列判据尚未采信（投票 {len(self._recent)}/{self._vote_size} 帧）",
                None, "vote")
        if settled == "battle":
            self._unknown_since = None
            return GateOutcome(
                GateDecision.WAIT,
                "有行军/驻扎队列在城外，等待回城后再搜索", settled, "vote")
        if settled in ("none", "gather"):
            self._unknown_since = None
            return GateOutcome(GateDecision.PROCEED, "", settled, "vote")
        return self._unknown_outcome(ts)

    def _feed(self, verdict: str) -> None:
        self._recent.append(verdict)
        if len(self._recent) > self._vote_size:
            self._recent.pop(0)
        if len(self._recent) == self._vote_size and len(set(self._recent)) == 1:
            self._settled = self._recent[0]

    def _unknown_outcome(self, now: float) -> GateOutcome:
        if self._unknown_since is None:
            self._unknown_since = now
        waited = now - self._unknown_since

        if not self._ledger.has_record(self._char_id):
            # 账本里没有任何依据（进程刚起 / 换账号）：沿用旧行为
            if waited < self._unknown_grace:
                return GateOutcome(
                    GateDecision.WAIT,
                    "队列图标不可辨且账本无记录（按在外处理），暂缓搜索",
                    "unknown", "grace")
            return GateOutcome(GateDecision.PROCEED, "", "unknown", "grace")

        if not self._ledger.troops_out(self._char_id):
            return GateOutcome(
                GateDecision.PROCEED,
                "队列图标不可辨，但账本显示部队在家，放行搜索",
                "unknown", "ledger")

        out_s = self._ledger.troops_out_seconds(self._char_id, now)
        if out_s >= self._stale_after:
            return GateOutcome(
                GateDecision.PROCEED,
                f"队列图标不可辨且账本称部队在外 {out_s:.0f}s（超 "
                f"{self._stale_after:.0f}s，账本不可信），放行搜索",
                "unknown", "grace")
        if waited >= self._unknown_grace:
            return GateOutcome(GateDecision.PROCEED, "", "unknown", "grace")
        return GateOutcome(
            GateDecision.WAIT,
            f"队列图标不可辨，账本显示部队在外 {out_s:.0f}s，继续等待",
            "unknown", "ledger")
