"""GemCoordinator：只验「它把宝石模式的配置接对了」，不验基类行为
（那在 test_base_runtime.py 里）。"""
from unittest.mock import MagicMock

from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.coordination.gem_runtime import GemCoordinator
from rok_assistant.infra.config import AppMode, RootConfig

CFG = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe",
            "max_rounds": 99},
    # zhaiduo 段是**陪跑**的：RootConfig.zhaiduo 必填且 instances 至少 1 条
    # （infra/config.py:292/400）。放一套与宝石完全不相干的实例，
    # 用来证明宝石协调器**只读 gem 段**（见下面那条用例）。
    "zhaiduo": {"instances": [
        {"id": "z0", "mumu_index": 0,
         "characters": [{"id": "z0c0", "name": "寨子号", "role": "leader",
                         "target_levels": [5],
                         "march_presets": [{"preset": 1,
                                            "troops": ["infantry"]}]}]},
    ]},
    "gem": {"queue_limit": 6, "max_rounds": 7, "scan_rings": 2,
            "scan_drag_px": 700, "scan_drag_ms": 400,
            "idle_wait_min": 11.0, "idle_wait_max": 45.0,
            "instances": [
                {"id": "mumu0", "mumu_index": 0,
                 "characters": [{"id": "c0", "name": "主号"}]},
            ]},
}


def _coord():
    return GemCoordinator(RootConfig.model_validate(CFG), event_bus=EventBus())


def test_instances_come_from_the_gem_section():
    assert [i.id for i in _coord()._instances()] == ["mumu0"]


def test_max_rounds_is_the_gem_section_not_the_app_section():
    """`gem.max_rounds` 与 `app.max_rounds` 是两个独立的旋钮。"""
    assert _coord()._max_rounds() == 7


def test_stats_target_uses_gem_max_rounds():
    coord = _coord()
    coord.runners = {"mumu0:c0": MagicMock(rounds_ok=0, rounds_failed=0,
                                           rounds_env=0, rounds_done=0)}
    assert coord.stats()["target"] == 7
    assert coord.stats()["fills"] == 0


def test_gem_has_no_cross_instance_routes():
    """宝石模式不订阅 rally_launched：一台机器一个号，没有跨实例链路。"""
    coord = _coord()
    assert coord._route_for("mumu0:c0", MagicMock()) is None
    assert coord._routes == {}


def test_should_finish_is_all_runners_reported():
    """宝石模式没有「车头/成员」之分，收工判据就是基类默认那条。"""
    coord = _coord()
    runners = {"mumu0:c0": MagicMock(), "mumu1:c1": MagicMock()}
    coord._stopped = {"mumu0:c0": ""}
    assert coord._should_finish(runners) is False
    coord._stopped = {"mumu0:c0": "", "mumu1:c1": ""}
    assert coord._should_finish(runners) is True


def test_sm_factory_receives_the_gem_config():
    """`GemConfig` 的每个字段都要真的走到 SM 上，不能有「声明了没人读」的。

    `idle_wait_*` 在配置里是**分钟**，SM 里存**秒**（`gem_sm.py:120-121`）。
    """
    coord = _coord()
    from rok_assistant.workers.gem_sm import GemStateMachine
    import numpy as np
    from rok_assistant.core.handle_source import MockHandleSource
    handle = MockHandleSource(np.zeros((1080, 1920, 3), dtype=np.uint8))
    sm = coord._sm_factory_for(coord._instances()[0].characters[0], handle, {},
                               None)
    assert isinstance(sm, GemStateMachine)
    assert sm._queue_limit == 6
    assert sm._scan_rings == 2
    assert sm._scan_drag_px == 700
    assert sm._scan_drag_ms == 400
    assert sm._idle_wait_min == 11.0 * 60.0
    assert sm._idle_wait_max == 45.0 * 60.0
    assert sm._char_id == "c0"


def test_config_reads_only_the_gem_section():
    """宝石模式**只**读 `gem:` 段：`zhaiduo:` 段里放一套完全不相干的实例，
    宝石协调器取到的实例仍然只来自 gem 段，`_max_rounds()` 也只认 gem 的值。"""
    coord = _coord()
    # 两个段各有一套实例，互不干扰
    assert [i.id for i in coord._config.instances_for(AppMode.ZHAIDUO)] == ["z0"]
    assert [i.id for i in coord._instances()] == ["mumu0"]
    # app.max_rounds 是 99、gem.max_rounds 是 7 —— 取的是 7，不是 99
    assert coord._max_rounds() == 7
