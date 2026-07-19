from __future__ import annotations
from enum import Enum
from collections import defaultdict


class RecoveryAction(str, Enum):
    RETRY = "retry"
    SKIP_STEP = "skip_step"
    SKIP_TARGET = "skip_target"
    SKIP_SESSION = "skip_session"
    PAUSE_ALL = "pause_all"


class FailureHandler:
    def __init__(self, max_retries: int = 3):
        self._max_retries = max_retries
        self._attempts: dict[tuple[str, str], int] = defaultdict(int)

    def handle(self, failure_type: str, context: dict) -> RecoveryAction:
        if failure_type == "recognition_failed":
            key = (context.get("worker_id", ""), context.get("scene", ""))
            self._attempts[key] += 1
            if self._attempts[key] < self._max_retries:
                return RecoveryAction.RETRY
            return RecoveryAction.SKIP_STEP
        if failure_type == "fortress_locked":
            return RecoveryAction.SKIP_TARGET
        if failure_type == "rally_empty_timeout":
            return RecoveryAction.SKIP_SESSION
        if failure_type == "window_disappeared":
            return RecoveryAction.PAUSE_ALL
        if failure_type == "switch_failed":
            return RecoveryAction.SKIP_SESSION
        return RecoveryAction.SKIP_SESSION

    def reset(self, worker_id: str) -> None:
        keys = [k for k in self._attempts if k[0] == worker_id]
        for k in keys:
            del self._attempts[k]
