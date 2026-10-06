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
            "join_btn", "swap_btn", "march_btn", "fill_B")}
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
                     error_backoff=0.05, screenshot_dir=tmp_path,
                     max_consecutive_failures=100)  # 本测试只看异常恢复，不触发熔断
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
                                         "march_btn", "fill_B")}
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
    # 车头错峰抖动置 0：不烧真实睡眠（上限 45s 会吃掉 5s 重建时限）
    monkeypatch.setattr("rok_assistant.workers.either_sm.random.uniform",
                        lambda a, b: 0.0)

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
                                target_levels=[8], march_preset=1,
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


def test_runner_stops_after_max_rounds():
    # 验收目标（2026-09-11）：跑满 N 轮自动收工 —— 全绿 mock 每轮成功，
    # max_rounds=2 时主循环退出、不再重建
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(), handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=None, poll_interval=0.01, restart_cooldown=0.05,
                     max_rounds=2)
    r.sm.on_rally_launched({"rally_id": "r1"})
    r.start()
    seen = set()
    deadline = time.time() + 5
    while time.time() < deadline and r.stopped_reason is None:
        # 冷却重建后的新 SM 需要重新喂 launch 事件（复刻协调器路由）
        if id(r.sm) not in seen:
            seen.add(id(r.sm))
            r.sm.on_rally_launched({"rally_id": f"r{len(seen)}"})
        time.sleep(0.02)
    r.stop()
    assert r.rounds_done == 2
    assert r.stopped_reason is not None and "轮数上限" in r.stopped_reason
    assert r.status == "done"
    assert not r._thread.is_alive()


def test_runner_stops_after_consecutive_failures(monkeypatch):
    # 白盒预置 war_attempts（同 fail_reason 测试）：每轮 no_rally_found，
    # max_consecutive_failures=2 时第 2 轮失败后停止，不再重建
    def build():
        handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
        recs = {k: _mock_rec() for k in ("map_btn", "search_icon", "alliance_btn",
                                         "war_title", "join_btn", "swap_btn",
                                         "march_btn", "fill_B")}
        sm = MemberStateMachine(handle, recs, [{"instance": "i1", "name": "B"}])
        sm._ctx["war_attempts"] = 11
        return sm

    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=build, handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=None, poll_interval=0.01, restart_cooldown=0.05,
                     max_consecutive_failures=2)
    r.sm.on_rally_launched({"rally_id": "r1"})
    r.start()
    seen = set()
    deadline = time.time() + 5
    while time.time() < deadline and r.stopped_reason is None:
        if id(r.sm) not in seen:
            seen.add(id(r.sm))
            r.sm.on_rally_launched({"rally_id": f"r{len(seen)}"})
        time.sleep(0.02)
    r.stop()
    assert r.rounds_done == 2
    assert r._fail_streak == 2
    assert r.stopped_reason is not None and "连续" in r.stopped_reason
    assert r.status == "done"


def _recording_profile(seen):
    """确定性 HumanProfile，其 jitter 换成记录器：把入参追加进 seen 并返回
    0.0（等待立即返回，测试不烧真实秒数，也不断言精确时长）。"""
    from rok_assistant.infra.anti_detection import AntiDetectionConfig, HumanProfile
    prof = HumanProfile(AntiDetectionConfig(debug_no_jitter=True))
    prof.jitter = MagicMock(
        side_effect=lambda base: (seen.append(base), 0.0)[1])
    return prof


def test_runner_cooldown_wait_goes_through_jitter():
    # 冷却等待必须经注入 profile 的 jitter(30.0)（默认 restart_cooldown），
    # 而不是把 30.0 常量直接交给 wait() —— 后者没有任何断言能察觉，
    # 「去规律化」也就落空。记录器让 wait 瞬时返回，只验证调用值。
    seen = []
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(), handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=None, poll_interval=0.01,
                     human=_recording_profile(seen))
    r.sm.on_rally_launched({"rally_id": "r1"})   # 一轮走完 → 进冷却分支
    r.start()
    deadline = time.time() + 5
    while time.time() < deadline and 30.0 not in seen:
        time.sleep(0.01)
    r.stop()
    assert 30.0 in seen, f"冷却等待未经 jitter(30.0)，记录={seen[:8]}"


def test_runner_poll_wait_goes_through_jitter():
    # SM 停在 IDLE（不喂 launch）时主循环每拍走 poll 等待分支：该等待同样
    # 必须经 jitter(2.0)（默认 poll_interval），不能是硬编码常量。
    seen = []
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(), handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=None, human=_recording_profile(seen))
    r.start()
    deadline = time.time() + 5
    while time.time() < deadline and 2.0 not in seen:
        time.sleep(0.01)
    r.stop()
    assert 2.0 in seen, f"轮询等待未经 jitter(2.0)，记录={seen[:8]}"


def test_runner_default_profile_keeps_deterministic_waits():
    # 不注入 profile 的调用方（既有测试/库用法）必须保持改动前的确定性：
    # 默认 profile 的 jitter 恒等返回 base —— 这是整条分支的兼容前提。
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(), handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=None, poll_interval=0.01, restart_cooldown=0.05)
    assert r._human.jitter(30.0) == 30.0
    assert r._human.jitter(2.0) == 2.0


def test_runner_stops_after_consecutive_step_errors():
    # 体力耗尽的表现是 step 持续异常（blue_rally 点不动 RuntimeError），
    # 不走终态 —— 连续异常计数达上限同样要收工，不能无限截图循环
    class _BoomSM:
        current = "LEADER:SELECT_RALLY_TIME"
        last_image = None
        fail_reason = None

        def is_terminal(self):
            return False

        def step(self):
            raise RuntimeError("blue_rally 不可见（模拟体力耗尽）")

    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_BoomSM, handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=None, poll_interval=0.01, restart_cooldown=0.05,
                     error_backoff=0.01, max_consecutive_failures=2)
    r.start()
    deadline = time.time() + 5
    while time.time() < deadline and r.stopped_reason is None:
        time.sleep(0.02)
    r.stop()
    assert r.rounds_done == 0   # 异常不算轮次
    assert r._error_streak == 4  # max_consecutive_failures * 2
    assert r.stopped_reason is not None and "step 异常" in r.stopped_reason
    assert r.status == "done"
