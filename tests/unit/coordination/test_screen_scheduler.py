import time
import threading
from rok_assistant.coordination.screen_scheduler import ScreenScheduler

def test_serializes_actions():
    sched = ScreenScheduler()
    order = []
    def make(i, delay):
        return lambda: (time.sleep(delay), order.append(i))
    sched.request("w1", make(1, 0.05))
    sched.request("w2", make(2, 0.05))
    sched.request("w1", make(3, 0.05))
    sched.wait_all()
    assert order == [1, 2, 3]

def test_priority_runs_first():
    sched = ScreenScheduler()
    order = []
    sched.request("w1", lambda: order.append("low"))
    sched.request("w2", lambda: order.append("high"), priority=10)
    sched.wait_all()
    # high goes first since it was enqueued with higher priority
    assert order[0] == "high"

def test_cancel_pending():
    sched = ScreenScheduler()
    called = []
    sched.request("w1", lambda: called.append("a"))
    sched.request("w1", lambda: called.append("b"))
    sched.cancel_pending("w1")
    sched.wait_all()
    # The first one may already have started; second should be cancelled
    assert "b" not in called
