import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from rok_assistant.gui.controller import GuiController


class FakeCoordinator:
    def __init__(self, *a, **kw):
        self.started = False
        self.stopped = False
    def start(self): self.started = True
    def stop(self): self.stopped = True
    def snapshot(self, char_id): return None


@pytest.fixture
def controller(qapp, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
app: {}
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
""", encoding="utf-8")
    c = GuiController(config_path=cfg, coordinator_factory=FakeCoordinator)
    yield c

def test_lists_characters(controller):
    chars = controller.characters()
    assert [(c["instance_id"], c["char_id"], c["role"]) for c in chars] == [
        ("inst0", "boss", "leader")]

def test_start_stop_uses_coordinator(controller):
    controller.start()
    coord = controller._coordinator
    assert coord.started
    controller.stop()
    assert coord.stopped
    assert controller._coordinator is None

def test_status_signal_from_bus(controller):
    received = []
    controller.status_changed.connect(lambda p: received.append(p))
    controller._on_bus_status({"instance_id": "inst0", "char_id": "boss",
                               "char_name": "车头", "state": "SEARCH_FORTRESS"})
    assert received and received[0]["state"] == "SEARCH_FORTRESS"

def test_load_config_error_emits_signal(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("instances: []", encoding="utf-8")   # 空实例列表，校验必失败
    c = GuiController(config_path=bad, coordinator_factory=FakeCoordinator)
    errs = []
    c.error_occurred.connect(lambda m: errs.append(m))
    assert c.load_config() is False
    assert errs

def test_reload_config_rereads_disk(controller, tmp_path):
    controller.load_config()
    # 磁盘上把角色改名后，reload 应看到新值（load_config 的内存缓存不覆盖）
    (tmp_path / "config.yaml").write_text("""
app: {}
instances:
  - id: inst0
    name: a
    adb_address: "127.0.0.1:5555"
    characters:
      - id: boss
        name: 新车头
        role: leader
        target_levels:
        - 7
        march_preset: 1
        march_troop_types: [cavalry]
""", encoding="utf-8")
    controller.reload_config()
    assert controller.characters()[0]["char_name"] == "新车头"

def test_reload_config_raises_on_invalid(controller, tmp_path):
    controller.load_config()
    (tmp_path / "config.yaml").write_text("instances: []", encoding="utf-8")
    with pytest.raises(Exception):
        controller.reload_config()
    # 失败后保留旧配置，不把内存配置清掉
    assert controller.characters()[0]["char_id"] == "boss"
