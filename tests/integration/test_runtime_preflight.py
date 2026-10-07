import pytest

from rok_assistant.coordination import runtime as RT
from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.infra.config import RootConfig

# 就地写一份最小配置，**不要**从 test_preflight 里 import——本仓库还没有
# 跨测试模块 import 的先例，而那会让 pytest 把同一个模块收两遍。
CFG = {
    "instances": [
        {"id": "mumu0", "name": "如愿", "mumu_index": 0,
         "characters": [{"id": "c0", "name": "车头", "role": "leader",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"]}]},
    ],
}


def test_start_runs_preflight_before_building_recognizers(monkeypatch):
    order = []

    def _fake_preflight(instances, app_config):
        order.append("preflight")
        raise RuntimeError("模拟器「如愿」（mumu0，MuMu 编号 0）连不上：boom")

    def _fake_load(*_a, **_kw):
        order.append("recognizers")
        raise AssertionError("预检失败时不该装配识别器")

    monkeypatch.setattr(RT, "preflight", _fake_preflight)
    monkeypatch.setattr(RT.TemplateRegistry, "load", _fake_load)
    coord = RT.RuntimeCoordinator(RootConfig.model_validate(CFG),
                                  event_bus=EventBus())
    with pytest.raises(RuntimeError, match="连不上"):
        coord.start()
    assert order == ["preflight"]
    assert coord.runners == {}          # 没有任何 worker 被拉起
    assert coord._running is False      # 回滚干净，可再次 start
