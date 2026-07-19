from __future__ import annotations
import heapq
import threading
import time
from typing import Callable, Any
from dataclasses import dataclass, field

@dataclass(order=True)
class _Item:
    priority: int
    seq: int
    worker_id: str = field(compare=False)
    action: Callable = field(compare=False)
    cancelled: bool = field(default=False, compare=False)

class ScreenScheduler:
    """FIFO + priority queue. Higher priority (larger int) served first."""
    def __init__(self):
        self._heap: list[_Item] = []
        self._counter = 0
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._outstanding = 0
        self._stop = False
        self._dispatcher = threading.Thread(target=self._dispatch, daemon=True)
        self._dispatcher.start()

    def request(self, worker_id: str, action: Callable, priority: int = 0) -> None:
        with self._cond:
            if self._stop:
                return
            self._counter += 1
            item = _Item(priority=-priority, seq=self._counter,
                         worker_id=worker_id, action=action)
            heapq.heappush(self._heap, item)
            self._outstanding += 1
            self._cond.notify()

    def _dispatch(self) -> None:
        while True:
            with self._cond:
                while not self._stop and not self._heap:
                    self._cond.wait()
                if self._stop and not self._heap:
                    return
                # Skip cancelled items at the top and decrement outstanding
                popped_any = False
                while self._heap and self._heap[0].cancelled:
                    heapq.heappop(self._heap)
                    self._outstanding -= 1
                    popped_any = True
                if popped_any:
                    self._cond.notify_all()
                if not self._heap:
                    continue
                item = heapq.heappop(self._heap)
            # Execute outside the lock so the action can call request/wait
            try:
                item.action()
            except Exception:
                pass
            finally:
                with self._cond:
                    self._outstanding -= 1
                    self._cond.notify_all()

    def cancel_pending(self, worker_id: str) -> None:
        with self._cond:
            for item in self._heap:
                if item.worker_id == worker_id and not item.cancelled:
                    item.cancelled = True
            self._cond.notify_all()

    def wait_all(self, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        with self._cond:
            while self._outstanding > 0:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return
                self._cond.wait(timeout=remaining)
