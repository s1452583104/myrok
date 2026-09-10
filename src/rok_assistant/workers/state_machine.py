from __future__ import annotations
import time
from typing import Callable, Union
from dataclasses import dataclass, field

@dataclass
class State:
    name: str

@dataclass
class Transition:
    from_state: str
    to_state: str
    action: Union[str, Callable]
    guard: Callable | None = None

class StateMachine:
    def __init__(self, initial: str):
        self._transitions: list[Transition] = []
        self.current = initial
        self.history: list[str] = [initial]
        self._ctx: dict = {}
        self.last_image = None
        self._setup()

    def _setup(self) -> None:
        raise NotImplementedError

    def add_transition(self, from_state: str, to_state: str,
                       action: Union[str, Callable], guard: Callable | None = None) -> None:
        self._transitions.append(Transition(from_state, to_state, action, guard))

    def step(self, context: dict | None = None) -> None:
        if context is None:
            context = self._ctx
        else:
            self._ctx = context
        for t in self._transitions:
            if t.from_state != self.current:
                continue
            if t.guard and not t.guard(context):
                continue
            if callable(t.action):
                t.action(context)
            # else: action is a string label, nothing to invoke
            self.current = t.to_state
            self.history.append(self.current)
            return
        # No transition matched - stay in current state

    # ---- shared recognition/click helpers (subclasses have _handle/_rec) ----
    def _find(self, rec_id: str):
        rec = self._rec.get(rec_id)
        if rec is None:
            return None
        img = self._handle.capture()
        self.last_image = img
        r = rec.recognize(img)
        return r if r.matched else None

    def _click(self, rec_id: str) -> bool:
        r = self._find(rec_id)
        if r is None:
            return False
        x, y = r.bbox.center()
        self._handle.click(x, y)
        return True

    def _find_retry(self, rec_id: str, attempts: int = 3, interval: float = 1.0):
        for i in range(attempts):
            r = self._find(rec_id)
            if r is not None:
                return r
            if i < attempts - 1 and interval > 0:
                time.sleep(interval)
        return None

    def _click_retry(self, rec_id: str, attempts: int = 3, interval: float = 1.0) -> bool:
        r = self._find_retry(rec_id, attempts=attempts, interval=interval)
        if r is None:
            return False
        x, y = r.bbox.center()
        self._handle.click(x, y)
        return True

    def _wait_for(self, rec_id: str, timeout: float = 10.0, interval: float = 1.0) -> bool:
        deadline = time.time() + timeout
        while True:
            if self._find(rec_id) is not None:
                return True
            if time.time() >= deadline:
                return False
            if interval > 0:
                time.sleep(min(interval, max(0.0, deadline - time.time())))

    def _wait_click(self, rec_id: str, timeout: float = 15.0, interval: float = 1.0) -> bool:
        if self._wait_for(rec_id, timeout=timeout, interval=interval):
            return self._click(rec_id)
        return False
