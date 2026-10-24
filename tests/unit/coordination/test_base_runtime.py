"""BaseCoordinator 的行为契约。

**这个文件在重构前后都必须绿**——它测的全是「抽基类时最容易碰坏的东西」：
stop 的 leftover 保留、stats 的键集合、snapshot 的缩略图缩放、收工上报的
并发快照。抽完基类之后这些行为一个字都不该变。
"""
from unittest.mock import MagicMock

import numpy as np

from rok_assistant.coordination.base_runtime import BaseCoordinator
from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.infra.config import RootConfig

# brief 原文这里是 `"zhaiduo": {"instances": []}`，但 `ZhaiduoConfig.instances`
# 带 `min_length=1`（config.py），空表会被 `RootConfig.model_validate` 拒——
# 8 条用例在 setup 阶段全红。`_Stub._instances()` 恒返回 []，实例内容不参与
# 这些用例的行为，所以给一个最小合法实例即可，断言一字未动。
CFG = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe", "max_rounds": 4},
    "zhaiduo": {"instances": [
        {"id": "mumu0", "mumu_index": 0,
         "characters": [{"id": "c0", "name": "车头", "role": "leader",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"]}]},
    ]},
}


class _Stub(BaseCoordinator):
    """最小子类：只实现两个必填钩子。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.spawned: list = []

    def _instances(self):
        return []

    def _sm_factory_for(self, char, handle, recognizers, profile):
        return MagicMock()


def _stub(bus=None):
    return _Stub(RootConfig.model_validate(CFG), event_bus=bus or EventBus())


def test_stop_keeps_reference_to_runners_that_will_not_die():
    """超时未停的守护线程**不能丢引用**：用户再点一次 Stop 还要有句柄可控。"""
    coord = _stub()
    alive = MagicMock()
    alive._thread.is_alive.return_value = True
    coord.runners = {"mumu0:c0": alive}
    coord.stop()
    assert coord.runners == {"mumu0:c0": alive}


def test_stop_drops_references_to_runners_that_stopped():
    coord = _stub()
    dead = MagicMock()
    dead._thread.is_alive.return_value = False
    coord.runners = {"mumu0:c0": dead}
    coord.stop()
    assert coord.runners == {}
    dead.stop.assert_called_once()


def test_stats_has_the_same_keys_the_gui_reads():
    """界面统计条按名字取值——键集合是契约，`_EMPTY_STATS` 与它一一对应。"""
    coord = _stub()
    coord.runners = {"mumu0:c0": MagicMock(rounds_ok=3, rounds_failed=1,
                                          rounds_env=2, rounds_done=6)}
    assert coord.stats() == {"ok": 3, "failed": 1, "env": 2, "rounds": 6,
                             "fills": 0, "target": 4}


def test_stats_target_is_zero_without_runners():
    """没有 runner 时该显示 0/0，不是一份假目标。"""
    coord = _stub()
    coord.runners = {}
    assert coord.stats()["target"] == 0


def test_snapshot_is_downscaled_before_encoding():
    from rok_assistant.coordination.base_runtime import _THUMB_W, _THUMB_H
    import cv2
    coord = _stub()
    runner = MagicMock(char_id="c0")
    runner.last_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    coord.runners = {"mumu0:c0": runner}
    img = cv2.imdecode(np.frombuffer(coord.snapshot("c0"), dtype=np.uint8),
                       cv2.IMREAD_COLOR)
    assert img.shape[0] <= _THUMB_H and img.shape[1] <= _THUMB_W


def test_should_finish_default_is_all_runners_reported():
    coord = _stub()
    runners = {"mumu0:c0": MagicMock(), "mumu1:c1": MagicMock()}
    coord._stopped = {"mumu0:c0": ""}
    assert coord._should_finish(runners) is False
    coord._stopped = {"mumu0:c0": "", "mumu1:c1": ""}
    assert coord._should_finish(runners) is True


def test_should_finish_is_false_for_an_empty_runner_set():
    """空集合不能算「全部收工」——那会在 start() 之前就发一次 all_workers_done。"""
    coord = _stub()
    assert coord._should_finish({}) is False


def test_worker_finished_ignores_events_for_unknown_keys():
    """上一次运行遗留的迟到事件不能凑数提前复位按钮。"""
    coord = _stub()
    coord.runners = {"mumu0:c0": MagicMock()}
    coord._stopped = {}
    coord._on_worker_finished({"instance_id": "mumu9", "char_id": "cx"})
    assert coord._stopped == {}
