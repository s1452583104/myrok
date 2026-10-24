import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
import yaml
from unittest.mock import MagicMock
from rok_assistant.gui.controller import GuiController


def _allowing_guard():
    """授权放行的替身：只实现 controller.start 读的那两个成员。"""
    st = MagicMock()
    st.allows_run = True
    return st


_MIN_CFG_WITH_GEM = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe"},
    # zhaiduo 段是**陪跑**的：它必填且 instances 至少 1 条。这条用例只
    # start(GEM)，寨子那套的内容无关紧要，只要**能通过校验**。
    "zhaiduo": {"instances": [
        {"id": "mumu0", "mumu_index": 0,
         "characters": [{"id": "boss", "name": "车头", "role": "leader",
                         "target_levels": [7],
                         "march_presets": [{"preset": 1,
                                            "troops": ["cavalry"]}]}]},
    ]},
    "gem": {"instances": [
        {"id": "mumu1", "mumu_index": 1,
         "characters": [{"id": "g0", "name": "采集号"}]},
    ]},
}

_MIN_CFG_WITH_QUIZ = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe"},
    "zhaiduo": _MIN_CFG_WITH_GEM["zhaiduo"],       # 陪跑，只为过校验
    "quiz": {"instances": [
        {"id": "mumu0", "mumu_index": 0,
         "characters": [{"id": "q0", "name": "答题号"}]},
    ]},
}


class FakeCoordinator:
    # 每次新建 +1：让两轮运行的统计读数可区分，否则「新起一轮有没有归零」
    # 和「有没有沿用上一轮」两种实现在断言下长得一模一样。
    runs = 0

    def __init__(self, *a, **kw):
        FakeCoordinator.runs += 1
        self.run_no = FakeCoordinator.runs
        self.started = False
        self.stopped = False
    def start(self): self.started = True
    def stop(self): self.stopped = True
    def snapshot(self, char_id): return None
    def stats(self):
        return {"ok": self.run_no, "failed": 0, "env": 0,
                "rounds": self.run_no, "fills": 0, "target": 8}


@pytest.fixture
def controller(qapp, tmp_path):
    # runs 是类属性、跨用例累计，不归零的话每条用例看到的 run_no 都不同
    FakeCoordinator.runs = 0
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
app: {}
zhaiduo:
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

def test_stats_are_zero_before_any_run(controller):
    s = controller.stats()
    assert (s["ok"], s["failed"], s["env"], s["rounds"], s["fills"],
            s["target"]) == (0, 0, 0, 0, 0, 0)


def test_stats_read_live_coordinator(controller):
    controller.start()
    assert controller.stats()["target"] == 8


def test_stats_keep_last_reading_after_stop(controller):
    """停止后仍显示最后一次读数。

    stop() 会把 coordinator 丢掉（`_coordinator = None`），不先留存的话
    统计条在用户点停止的瞬间归零 —— 而他点停止正是为了看这一轮的战绩。
    """
    controller.start()
    controller.stop()
    assert controller.stats()["ok"] == 1


def test_stats_are_zero_while_a_new_run_is_starting(controller):
    """新起一轮时，coordinator 就位之前统计必须已归零。

    异步启动后这段窗口真实存在（界面显示着「正在启动…」），若沿用上一轮
    的读数，用户看到的是「正在启动」配着上一轮的战绩。
    """
    controller.start()
    controller.stop()
    assert controller.stats()["ok"] == 1        # 上一轮的读数还在

    seen = {}
    real_factory = controller._coordinator_factory

    def _probe_factory(*a, **kw):
        seen["stats"] = controller.stats()      # coordinator 尚未就位
        return real_factory(*a, **kw)

    controller._coordinator_factory = _probe_factory
    controller.start()
    assert seen["stats"]["ok"] == 0, "新一轮启动中仍显示上一轮读数"
    assert controller.stats()["ok"] == 2        # 就位后读新 coordinator 的


def test_card_view_defaults_to_image_before_config_loads(controller):
    """配置没加载时按默认「图文」算，不抛。"""
    assert controller.card_view() == "image"


def test_card_view_reads_the_config(controller, tmp_path):
    (tmp_path / "config.yaml").write_text("""
app:
  card_view: text
zhaiduo:
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
    controller.load_config()
    assert controller.card_view() == "text"


def test_set_card_view_writes_through_and_updates_memory(controller, tmp_path):
    """落盘 + 内存一起改。

    只写盘的话，下一次 `reload_config()`（「刷新配置」按钮）之前的读数是旧的
    —— 界面显示的和配置里写的两回事。

    配置用真实形状（`app:` 块里有键），不是夹具里的 `app: {}`：单键改写只认
    「顶层 `app:` 段 + 直接子级那一行」，行内空映射形态它拒绝改写（安全优先，
    见 set_card_view 的 docstring）。
    """
    (tmp_path / "config.yaml").write_text("""
app:
  mumu_manager_path: M.exe
  adb_path: adb.exe
zhaiduo:
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
    controller.load_config()
    assert controller.set_card_view("text") is True
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "card_view: text" in text
    assert "adb_path: adb.exe" in text          # 别的键没被动过
    assert controller.card_view() == "text"


def test_set_card_view_reports_failure_without_raising(controller, tmp_path):
    """写盘失败返回 False，不抛。

    显示模式是个纯观感开关，写不进去不该把界面搞崩；调用方据此提示
    「本次生效，未能保存」。
    """
    (tmp_path / "config.yaml").write_text("这不是 yaml: [", encoding="utf-8")
    assert controller.set_card_view("text") is False
    assert controller.card_view() == "image"   # 内存里没被改成 text


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
zhaiduo:
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


def test_characters_are_filtered_by_mode(tmp_path):
    """`characters()` 按模式取实例：宝石模式读到的是 `gem:` 段。"""
    from rok_assistant.infra.config import AppMode

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe"},
        "zhaiduo": {"instances": [
            {"id": "mumu0", "mumu_index": 0,
             "characters": [{"id": "boss", "name": "车头", "role": "leader",
                             "target_levels": [7],
                             "march_presets": [{"preset": 1,
                                                "troops": ["cavalry"]}]}]},
        ]},
        "gem": {"instances": [
            {"id": "mumu1", "mumu_index": 1,
             "characters": [{"id": "g0", "name": "采集号"}]},
        ]},
    }, allow_unicode=True), encoding="utf-8")
    c = GuiController(config_path=cfg)

    assert [x["char_id"] for x in c.characters()] == ["boss"]
    gem = c.characters(AppMode.GEM)
    assert [x["char_id"] for x in gem] == ["g0"]
    # 宝石角色没有分工，给的是展示用的 "gem" 而不是 AttributeError
    assert gem[0]["role"] == "gem"
    assert gem[0]["char_name"] == "采集号"


def test_start_uses_the_gem_coordinator_factory_for_gem_mode(tmp_path, monkeypatch):
    """`start(AppMode.GEM)` 必须造 GemCoordinator，不能造寨子的那个——
    寨子协调器会去读 `characters[0].role`，宝石角色没有这个字段。"""
    from rok_assistant.infra.config import AppMode
    from rok_assistant.infra.licensing import guard

    monkeypatch.setattr(guard, "current_guard", _allowing_guard)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(_MIN_CFG_WITH_GEM, allow_unicode=True),
                   encoding="utf-8")
    made = []

    def fake_zhaiduo(config, event_bus=None, template_dir=None):
        made.append("zhaiduo")
        raise AssertionError("宝石模式不该造寨子协调器")

    def fake_gem(config, event_bus=None, template_dir=None):
        made.append("gem")
        c = MagicMock()
        c.start.return_value = None
        return c

    c = GuiController(config_path=cfg, coordinator_factory=fake_zhaiduo,
                      gem_coordinator_factory=fake_gem)
    assert c.start(AppMode.GEM) is True
    assert made == ["gem"]


def test_start_uses_the_quiz_coordinator_factory_for_quiz_mode(tmp_path, monkeypatch):
    """`start(AppMode.QUIZ)` 必须造 QuizCoordinator——寨子协调器会去读
    `characters[0].role`，答题角色没有这个字段。"""
    from rok_assistant.infra.config import AppMode
    from rok_assistant.infra.licensing import guard

    monkeypatch.setattr(guard, "current_guard", _allowing_guard)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(_MIN_CFG_WITH_QUIZ, allow_unicode=True),
                   encoding="utf-8")

    def fake_zhaiduo(config, event_bus=None, template_dir=None):
        raise AssertionError("答题模式不该造寨子协调器")

    def fake_gem(config, event_bus=None, template_dir=None):
        raise AssertionError("答题模式不该造宝石协调器")

    made = []

    def fake_quiz(config, event_bus=None, template_dir=None):
        made.append("quiz")
        return MagicMock()

    c = GuiController(config_path=cfg, coordinator_factory=fake_zhaiduo,
                      gem_coordinator_factory=fake_gem,
                      quiz_coordinator_factory=fake_quiz)
    assert c.start(AppMode.QUIZ) is True
    assert made == ["quiz"]


def test_quiz_characters_get_the_quiz_role_label(tmp_path, monkeypatch):
    """无分工角色的回落必须**按模式**给：答题角色拿到 "quiz"。

    写死成 "gem" 的话卡片标题会是「答题号（宝石采集）」，用户会以为
    这台机器在采宝石（ROLE_LABELS["quiz"] → 「自动答题」）。
    """
    from rok_assistant.infra.config import AppMode
    from rok_assistant.infra.licensing import guard

    monkeypatch.setattr(guard, "current_guard", _allowing_guard)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(_MIN_CFG_WITH_QUIZ, allow_unicode=True),
                   encoding="utf-8")
    c = GuiController(config_path=cfg)
    quiz = c.characters(AppMode.QUIZ)
    assert [x["char_id"] for x in quiz] == ["q0"]
    assert quiz[0]["role"] == "quiz"
