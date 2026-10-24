"""RuntimeCoordinator.stats()：给 GUI 统计条用的运行汇总。

汇总逻辑单独测，不走真线程 —— 起一次 RuntimeCoordinator 要 adb 预检 +
加载 ONNX，那是集成测试的事（见 tests/integration/test_runtime.py）。
"""
from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.coordination.runtime import RuntimeCoordinator
from rok_assistant.infra.config import RootConfig

CFG = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe"},
    "zhaiduo": {"instances": [
        {"id": "mumu0", "mumu_index": 0,
         "characters": [{"id": "c0", "name": "车头", "role": "leader",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"]}]},
        {"id": "mumu1", "mumu_index": 1,
         "characters": [{"id": "c1", "name": "填兵", "role": "member",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"],
                         "fill_target_leaders": [{"instance": "mumu0",
                                                  "name": "车头"}]}]},
    ]},
}


class _FakeRunner:
    """只带统计字段的占位 runner。

    刻意不用 MagicMock：它会给 `.rounds_ok` 返回一个 MagicMock，求和时
    静默变成 `MagicMock + int`，测试看着绿其实什么也没验。
    """

    def __init__(self, ok=0, failed=0, env=0):
        self.rounds_ok = ok
        self.rounds_failed = failed
        self.rounds_env = env
        self.rounds_done = ok + failed + env


def _coord(bus, runners, max_rounds=4):
    cfg = {**CFG, "app": {**CFG["app"], "max_rounds": max_rounds}}
    coord = RuntimeCoordinator(RootConfig.model_validate(cfg), event_bus=bus)
    coord.runners = runners
    return coord


def test_stats_aggregate_rounds_and_fills():
    """三个结局分项跨角色求和，填兵次数来自进程级账本。"""
    coord = _coord(EventBus(), {"mumu0:c0": _FakeRunner(3, 1, 2),
                                "mumu1:c1": _FakeRunner(2, 0, 1)})
    coord.ledger.mark_fill_done("c0")
    coord.ledger.mark_fill_done("c1")
    coord.ledger.mark_fill_done("c1")

    s = coord.stats()
    assert s["ok"] == 5
    assert s["failed"] == 1
    assert s["env"] == 3
    assert s["rounds"] == 9
    assert s["fills"] == 3


def test_stats_target_is_max_rounds_times_characters():
    """「设置个数」= max_rounds × 在跑的角色数。

    用 4 而不是默认的 10：默认值恰好等于「10 个角色各 1 轮」，写死 10 的
    实现也能蒙对，测不出乘法有没有做。
    """
    coord = _coord(EventBus(), {"mumu0:c0": _FakeRunner(),
                                "mumu1:c1": _FakeRunner()}, max_rounds=4)
    assert coord.stats()["target"] == 8


def test_stats_before_any_round_are_all_zero():
    """刚起来还没跑完一轮：全 0，但目标数已经是在跑角色数 × max_rounds。"""
    coord = _coord(EventBus(), {"mumu0:c0": _FakeRunner(),
                                "mumu1:c1": _FakeRunner()}, max_rounds=4)
    s = coord.stats()
    assert (s["ok"], s["failed"], s["env"], s["rounds"], s["fills"]) == (0, 0, 0, 0, 0)
    assert s["target"] == 8


def test_stats_without_runners_do_not_crash():
    """自然收工后 `runners` 被清空，此时读统计不能抛。

    这条路径真的会走到：`_on_worker_finished` 末尾 `self.runners.clear()`，
    而 GUI 的定时器可能正好在那一刻读统计。
    """
    coord = _coord(EventBus(), {})
    s = coord.stats()
    assert (s["ok"], s["failed"], s["env"], s["rounds"], s["fills"]) == (0, 0, 0, 0, 0)
    assert s["target"] == 0
