import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import logging
import threading
import time
from contextlib import contextmanager

import numpy as np
import pytest
from unittest.mock import patch

from rok_assistant.coordination.runtime import RuntimeCoordinator
from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.infra.config import load_config


VALID = """
app:
  mumu_manager_path: ""
  adb_path: "adb"
instances:
  - id: inst0
    name: a
    adb_address: "127.0.0.1:5555"
    characters:
      - id: boss
        name: 车头
        role: leader
        target_levels:
        - 7
        march_preset: 1
        march_troop_types: [cavalry]
  - id: inst1
    name: b
    adb_address: "127.0.0.1:5556"
    characters:
      - id: worker
        name: 成员
        role: member
        target_levels:
        - 7
        march_preset: 1
        march_troop_types: [cavalry]
        fill_target_leaders:
          - { instance: inst0, name: 车头 }
"""

# 空模板清单：Registry 加载成功但 recognizers 为空，避免依赖真实 templates/
EMPTY_MANIFEST = "templates: []\n"

# either 角色配置：验证 _spawn 把进程级账本下发给 EitherStateMachine
# （either 必须配一个指向 leader 的 fill_target，见 config 校验）
EITHER = """
app:
  mumu_manager_path: ""
  adb_path: "adb"
instances:
  - id: inst0
    name: a
    adb_address: "127.0.0.1:5555"
    characters:
      - id: boss
        name: 车头
        role: leader
        target_levels:
        - 7
        march_preset: 1
        march_troop_types: [cavalry]
  - id: inst1
    name: b
    adb_address: "127.0.0.1:5556"
    characters:
      - id: solo
        name: 独狼
        role: either
        target_levels:
        - 7
        march_preset: 1
        march_troop_types: [cavalry]
        fill_target_leaders:
          - { instance: inst0, name: 车头 }
"""


def _write_config(tmp_path, text=VALID):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return load_config(p)


@contextmanager
def _running_coordinator(tmp_path, config_text=VALID):
    """启动一个用 MockHandleSource + 空模板清单的 coordinator，结束即停。"""
    cfg = _write_config(tmp_path, config_text)
    (tmp_path / "manifest.yaml").write_text(EMPTY_MANIFEST, encoding="utf-8")
    bus = EventBus()
    fake_handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    with patch("rok_assistant.coordination.runtime.create_handle_source",
               return_value=fake_handle):
        coord = RuntimeCoordinator(cfg, event_bus=bus, template_dir=tmp_path)
        coord.start()
        try:
            yield coord
        finally:
            coord.stop()


def test_coordinator_builds_one_runner_per_first_character(tmp_path):
    with _running_coordinator(tmp_path) as coord:
        assert set(coord.runners) == {"inst0:boss", "inst1:worker"}


def test_coordinator_routes_rally_to_member_runner(tmp_path):
    with _running_coordinator(tmp_path) as coord:
        member_sm = coord.runners["inst1:worker"].sm
        coord._bus.publish("rally_launched", {"rally_id": "r9"})
        # 线程在跑，消费时机不定：轮询等待成员 SM 留存的事件（last_event
        # 在 _consume_event 后持久保留，_pending_event 则被清空）
        deadline = time.time() + 5.0
        while member_sm.last_event is None and time.time() < deadline:
            time.sleep(0.05)
        assert member_sm.last_event == {"rally_id": "r9"}


def test_coordinator_snapshot_returns_jpeg_bytes(tmp_path):
    with _running_coordinator(tmp_path) as coord:
        # 无帧时返回 None
        assert coord.snapshot("unknown") is None
        # 注入一帧后返回以 JPEG magic 开头的非空 bytes
        coord.runners["inst0:boss"].sm.last_image = np.zeros((4, 4, 3), np.uint8)
        data = coord.snapshot("boss")
        assert data is not None
        assert data[:2] == b"\xff\xd8"


def test_start_warns_on_level_collision_but_still_runs(tmp_path, caplog):
    """EITHER 配置里两号同为 7 级且 either 填 leader → 撞车。
    start() 必须真的记录告警（纯函数测试钉不住「发射」这一步），
    且告警只是提醒，不得中断启动 —— runner 仍照常建好、coordinator 在运行。"""
    with caplog.at_level(logging.WARNING,
                         logger="rok_assistant.coordination.runtime"):
        with _running_coordinator(tmp_path, EITHER) as coord:
            assert coord._running is True                      # 未被告警阻断
            assert set(coord.runners) == {"inst0:boss", "inst1:solo"}
    warnings = [r.getMessage() for r in caplog.records
                if r.name == "rok_assistant.coordination.runtime"]
    assert any("都含 7 级" in m and "填对方" in m for m in warnings)


def test_spawn_threads_shared_ledger_by_identity(tmp_path):
    """_spawn 必须把**进程级账本的同一实例**下发给每个状态机（identity，
    不是相等）。漏传 ledger 时 EitherStateMachine 会自建一本（either_sm.py），
    而 runner 每轮终态后重建 SM —— 账本随之每轮清空，集结门槛的 L0 判据永久
    退化成「无记录 + 宽限兜底」，且不会有任何测试失败。自建对象与共享对象
    「值相等但身份不同」，故必须用 is 断言才能钉住。"""
    with _running_coordinator(tmp_path, EITHER) as coord:
        sm = coord.runners["inst1:solo"].sm
        assert sm._ledger is coord.ledger
        # 门槛与两个子状态机读的必须是同一本，不是各自副本
        assert sm._gate._ledger is coord.ledger
        assert sm._leader._ledger is coord.ledger
        assert sm._member._ledger is coord.ledger


# ---------------- 用不跑线程的 FakeRunner 精确测路由/生命周期 ----------------

class FakeSM:
    def __init__(self):
        self.current = "IDLE"
        self.events: list[dict] = []

    def on_rally_launched(self, event: dict) -> None:
        self.events.append(event)


class FakeRunner:
    """不启动线程的 WorkerRunner 替身；类级列表记录创建顺序。"""
    instances: list["FakeRunner"] = []

    def __init__(self, **kw):
        self.kw = kw
        self.sm = FakeSM()
        self.started = False
        self.stopped = False
        # 已结束的线程：is_alive() 为 False，stop() 视为正常终止
        self._thread = threading.Thread(target=lambda: None, daemon=True)
        self._thread.start()
        FakeRunner.instances.append(self)

    @property
    def char_id(self) -> str:
        return self.kw["char_id"]

    def start(self) -> None:
        self.started = True

    def stop(self, timeout: float = 10.0) -> None:
        self.stopped = True


class StuckRunner(FakeRunner):
    """stop() 拦不下来的 worker：线程一直活着，用于验证 stop 不丢引用。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._thread = threading.Thread(target=lambda: time.sleep(30), daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self.stopped = True   # 线程假装没听见


@contextmanager
def _fake_runner_coordinator(tmp_path, runner_cls=FakeRunner):
    cfg = _write_config(tmp_path)
    (tmp_path / "manifest.yaml").write_text(EMPTY_MANIFEST, encoding="utf-8")
    bus = EventBus()
    fake_handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    FakeRunner.instances = []
    with patch("rok_assistant.coordination.runtime.create_handle_source",
               return_value=fake_handle), \
         patch("rok_assistant.coordination.runtime.WorkerRunner", runner_cls):
        coord = RuntimeCoordinator(cfg, event_bus=bus, template_dir=tmp_path)
        coord.start()
        yield coord


def test_router_gate_ignores_event_when_not_waiting(tmp_path):
    with _fake_runner_coordinator(tmp_path) as coord:
        member = coord.runners["inst1:worker"]
        member.sm.current = "FILTER"   # 已在跑的非等待态
        coord._bus.publish("rally_launched", {"rally_id": "r1"})
        assert member.sm.events == []
        member.sm.current = "WAIT_LAUNCH_EVENT"
        coord._bus.publish("rally_launched", {"rally_id": "r2"})
        assert member.sm.events == [{"rally_id": "r2"}]


def test_stop_unsubscribes_routes_and_restart_resubscribes_once(tmp_path):
    with _fake_runner_coordinator(tmp_path) as coord:
        bus = coord._bus
        coord.stop()
        bus.publish("rally_launched", {"rally_id": "r1"})
        for runner in FakeRunner.instances:
            assert runner.sm.events == []   # 退订后事件不再送达任何 SM
        # 重新 start 恰好重订阅一次（漏退订会多出路由处理器）；
        # RallyEventTracker 在 __init__ 只订阅一次，重启不重复
        coord.start()
        routes = [h for h in bus._handlers["rally_launched"]
                  if getattr(h, "__name__", "") == "route"]
        assert len(routes) == 1
        assert len(bus._handlers["rally_launched"]) == 2   # 路由 + 登记簿
        coord.stop()


def test_partial_start_failure_rolls_back(tmp_path):
    cfg = _write_config(tmp_path)
    (tmp_path / "manifest.yaml").write_text(EMPTY_MANIFEST, encoding="utf-8")
    fake_handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    FakeRunner.instances = []
    with patch("rok_assistant.coordination.runtime.create_handle_source",
               side_effect=[fake_handle, RuntimeError("inst1 连不上")]), \
         patch("rok_assistant.coordination.runtime.WorkerRunner", FakeRunner):
        coord = RuntimeCoordinator(cfg, event_bus=EventBus(), template_dir=tmp_path)
        with pytest.raises(RuntimeError):
            coord.start()
        assert coord._running is False
        assert coord.runners == {} and coord._routes == {}
        # 第 1 个实例的 runner 已被回滚停掉，不会成为孤儿
        assert len(FakeRunner.instances) == 1
        assert FakeRunner.instances[0].started
        assert FakeRunner.instances[0].stopped


def test_start_error_names_the_emulator_that_failed(tmp_path):
    """报错必须点名是哪一台，且保留原始原因。

    2026-10-05 用户报「点 Start 后只连上一个，另一个成员实例报错」，但运行日志
    里两个 worker 都正常——失败落在 `create_handle_source` 阶段，worker 还没起来，
    **日志里一个字都没有**。配了两台时，裸异常里只有「模拟器 1 可能没有启动」
    这种编号，界面上再包一层泛泛的「启动失败」，用户根本不知道说的是哪台。
    """
    cfg = _write_config(tmp_path)
    (tmp_path / "manifest.yaml").write_text(EMPTY_MANIFEST, encoding="utf-8")
    fake_handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    FakeRunner.instances = []
    with patch("rok_assistant.coordination.runtime.create_handle_source",
               side_effect=[fake_handle, RuntimeError("模拟器 1 可能没有启动")]), \
         patch("rok_assistant.coordination.runtime.WorkerRunner", FakeRunner):
        coord = RuntimeCoordinator(cfg, event_bus=EventBus(), template_dir=tmp_path)
        with pytest.raises(RuntimeError) as ei:
            coord.start()
    msg = str(ei.value)
    assert "b" in msg, f"没点名是哪台模拟器：{msg}"          # 第 2 个实例的 name
    assert "inst1" in msg, f"没带上实例 id：{msg}"
    assert "模拟器 1 可能没有启动" in msg, f"把原始原因吞了：{msg}"


def test_stop_keeps_reference_to_stuck_runner(tmp_path):
    with _fake_runner_coordinator(tmp_path, runner_cls=StuckRunner) as coord:
        coord.stop()
        # 超时未停的 runner 必须保留引用，不能被 clear 静默丢弃
        assert set(coord.runners) == {"inst0:boss", "inst1:worker"}
        assert coord._running is False

