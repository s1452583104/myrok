from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.coordination.runtime import RuntimeCoordinator
from rok_assistant.infra.config import RootConfig

CFG = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe"},
    "instances": [
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
    ],
}


def _coord(bus):
    coord = RuntimeCoordinator(RootConfig.model_validate(CFG), event_bus=bus)
    # 不真启动：只放两个占位 runner，测汇总逻辑
    coord.runners = {"mumu0:c0": object(), "mumu1:c1": object()}
    return coord


def test_all_workers_done_only_after_every_runner_reports():
    bus = EventBus()
    done = []
    bus.subscribe("all_workers_done", done.append)
    _coord(bus)

    bus.publish("worker_finished", {"instance_id": "mumu0", "char_id": "c0",
                                    "stopped_reason": "已完成 10 轮，达到轮数上限"})
    assert done == []                      # 还差一台

    bus.publish("worker_finished", {"instance_id": "mumu1", "char_id": "c1",
                                    "stopped_reason": "已完成 10 轮，达到轮数上限"})
    assert len(done) == 1
    assert set(done[0]["reasons"]) == {"mumu0:c0", "mumu1:c1"}
    assert done[0]["reasons"]["mumu0:c0"] == "已完成 10 轮，达到轮数上限"


def test_all_workers_done_not_published_for_unknown_runner():
    bus = EventBus()
    done = []
    bus.subscribe("all_workers_done", done.append)
    _coord(bus)
    bus.publish("worker_finished", {"instance_id": "mumu9", "char_id": "x",
                                    "stopped_reason": "r"})
    assert done == []      # 不在 self.runners 里的事件不能凑数
