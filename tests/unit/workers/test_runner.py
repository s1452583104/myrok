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
            "map_btn", "search_icon", "alliance_btn", "war_title",
            "join_btn", "swap_btn", "fill_B")}
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
    while time.time() < deadline and not r.reached_terminal():
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


def test_runner_start_twice_keeps_single_thread():
    import threading
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(), handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=None, poll_interval=0.01, restart_cooldown=0.05,
                     error_backoff=0.05)
    before = threading.active_count()
    r.start()
    r.start()  # 第二次 start 应被忽略
    time.sleep(0.1)
    after = threading.active_count()
    r.stop()
    assert after - before == 1  # 只有一个工作线程
    r._thread.join(timeout=2.0)
    assert not r._thread.is_alive()


def test_runner_publishes_fail_reason_on_status_update():
    # FILTER 耗尽（白盒预置 war_attempts，同 test_member_sm）→ END：
    # status_update payload 必须带出 fail_reason（未失败时为 None）
    def build():
        handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
        recs = {k: _mock_rec() for k in ("map_btn", "search_icon", "alliance_btn",
                                         "war_title", "join_btn", "swap_btn",
                                         "fill_B")}
        return MemberStateMachine(handle, recs, [{"instance": "i1", "name": "B"}])

    bus = EventBus()
    statuses = []
    bus.subscribe("status_update", lambda p: statuses.append(p))
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=build, handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=bus, poll_interval=0.01, restart_cooldown=0.05)
    r.sm.on_rally_launched({"rally_id": "r1"})
    r.sm._ctx["war_attempts"] = 11
    r.start()
    deadline = time.time() + 5
    while time.time() < deadline and not r.reached_terminal():
        time.sleep(0.02)
    r.stop()
    assert any(s["state"] == "END" and s["fail_reason"] == "no_rally_found"
               for s in statuses)
    assert statuses[0]["fail_reason"] is None  # 失败前的状态发布为 None


class _FakeTime:
    """Deterministic clock（同 test_leader_sm）：替换 state_machine.time，
    leader give-up 路径的 _wait_for 超时等待瞬时推进，测试不烧真实秒数。"""

    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_runner_rebuilds_after_either_leader_give_up(monkeypatch):
    # either 角色 leader 阶段放弃 → SM 呈现为终态（不再 RuntimeError）→
    # runner 冷却后重建新 SM 重试：工厂必须被再次调用（第二个 SM 实例）
    from rok_assistant.workers.either_sm import EitherStateMachine
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    # leader 等级连点停顿置 0，免真实睡眠拖垮重建时限
    monkeypatch.setattr("rok_assistant.workers.leader_sm._LEVEL_CLICK_PACE", 0.0)

    made = []

    def factory():
        handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
        rec = _mock_rec()
        recs = {k: rec for k in ("search_icon", "map_btn", "level_plus",
                                 "search_btn", "red_rally", "rally_attack_popup",
                                 "blue_rally", "preset_1", "troop_infantry",
                                 "march_btn")}
        recs["red_rally"] = _mock_rec()  # 独立 mock，避免连带共享 rec
        sm = EitherStateMachine(handle_source=handle, recognizers=recs,
                                target_level=8, march_preset=1,
                                march_troop_types=["infantry"],
                                fill_target_leaders=[])
        sm._leader._rec["red_rally"].recognize.return_value.matched = False  # 永搜无果
        made.append(sm)
        return sm

    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=factory, handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=None, poll_interval=0.01, restart_cooldown=0.05)
    r.start()
    deadline = time.time() + 5
    while time.time() < deadline and len(made) < 2:
        time.sleep(0.02)
    r.stop()
    assert len(made) >= 2, "leader give-up 后 runner 未重建重试"
    assert made[1] is not made[0]
