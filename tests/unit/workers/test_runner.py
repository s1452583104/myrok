"""WorkerRunner 单元测试：每角色一个线程驱动状态机。"""
import time
import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.runner import WorkerRunner
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.coordination.event_bus import EventBus


def _mock_rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    return rec


def _member_factory(recognizers=None):
    def build():
        handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
        recs = {k: recognizers or _mock_rec() for k in (
            "map_btn", "search_icon", "alliance_btn", "war_btn", "sort_nearest",
            "join_btn", "march_btn")}
        return MemberStateMachine(handle, recs, [{"instance": "i1", "name": "B"}])
    return build


def test_runner_drives_member_to_end_and_publishes_status():
    bus = EventBus()
    statuses = []
    bus.subscribe("status_update", lambda p: statuses.append(p))
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="成员甲",
                     sm_factory=_member_factory(), handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=bus, poll_interval=0.01, restart_cooldown=0.05)
    r.sm.on_rally_launched({"rally_id": "r1"})
    r.start()
    deadline = time.time() + 5
    while time.time() < deadline and not r.is_terminal_once():
        time.sleep(0.02)
    r.stop()
    states = [s["state"] for s in statuses]
    assert any(s == "END" for s in states)
    assert statuses[0]["instance_id"] == "i1"
    assert statuses[0]["char_id"] == "c1"


def test_runner_pauses_when_handle_dies():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    handle.set_alive(False)
    bus = EventBus()
    statuses = []
    bus.subscribe("status_update", lambda p: statuses.append(p))
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(), handle_source=handle,
                     event_bus=bus, poll_interval=0.01, restart_cooldown=0.05)
    r.start()
    time.sleep(0.3)
    r.stop()
    assert any(s["state"] == "paused" for s in statuses)


def test_runner_survives_sm_exception_and_saves_screenshot(tmp_path):
    # 状态机 _find 的顺序是：capture → self.last_image = img → recognize。
    # 因此识别器抛异常时 last_image 已被赋值，失败截图必定保存。
    bad = _mock_rec()
    bad.recognize.side_effect = RuntimeError("boom")
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(recognizers=bad),
                     handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=None, poll_interval=0.01, restart_cooldown=0.05,
                     error_backoff=0.05, screenshot_dir=tmp_path)
    # 必须先发集结事件：SM 停在 IDLE 且无 pending event 时 step 不触发任何
    # _find，坏识别器永远不会被调用，异常路径无法覆盖。
    r.sm.on_rally_launched({"rally_id": "r1"})
    r.start()
    time.sleep(0.4)
    r.stop()
    shots = list(tmp_path.glob("failure_*.png"))
    assert shots, "异常时应保存失败截图"
    assert r.status == "error"
