"""QuizCoordinator：只验「它把答题模式的配置接对了」。"""
from unittest.mock import MagicMock

import numpy as np

from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.coordination.quiz_runtime import QuizCoordinator
from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.core.quiz.llm import LLMClient
from rok_assistant.infra.config import AppMode, RootConfig
from rok_assistant.workers.quiz_sm import QuizStateMachine

CFG = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe",
            "max_rounds": 99},
    "zhaiduo": {"instances": [
        {"id": "z0", "mumu_index": 0,
         "characters": [{"id": "z0c0", "name": "寨子号", "role": "leader",
                         "target_levels": [5],
                         "march_presets": [{"preset": 1,
                                            "troops": ["infantry"]}]}]},
    ]},
    "quiz": {
        "max_rounds": 4,
        "fuzzy_threshold": 0.8,
        "verify_delay": 2.5,
        "min_green_ratio": 0.7,
        "max_questions_per_round": 12,
        "round_cooldown_min": 3.0,
        "parse_retries": 4,
        "auto_click": False,
        "entry_taps": [[10, 20]],
        "instances": [
            {"id": "mumu0", "mumu_index": 0,
             "characters": [{"id": "q0", "name": "答题号"}]},
        ],
    },
}


class _FakeBank:
    def __init__(self):
        self.loads = 0
        self.size = 1076

    def load(self):
        self.loads += 1


def _coord(**kw):
    return QuizCoordinator(RootConfig.model_validate(CFG),
                           event_bus=EventBus(), **kw)


def test_instances_come_from_the_quiz_section():
    assert [i.id for i in _coord()._instances()] == ["mumu0"]


def test_max_rounds_is_the_quiz_section_not_the_app_section():
    assert _coord()._max_rounds() == 4


def test_stats_target_uses_quiz_max_rounds():
    coord = _coord()
    coord.runners = {"mumu0:q0": MagicMock(rounds_ok=0, rounds_failed=0,
                                           rounds_env=0, rounds_done=0)}
    assert coord.stats()["target"] == 4
    assert coord.stats()["fills"] == 0


def test_quiz_has_no_cross_instance_routes():
    assert _coord()._route_for("mumu0:q0", MagicMock()) is None


def test_bank_is_loaded_once_and_shared_with_the_solver():
    """题库跨轮复用：每轮重建一次 SM，但 `load()` 只跑一次（读 1076 条 + 模糊表）。"""
    bank = _FakeBank()
    coord = _coord(ocr=MagicMock(), bank_factory=lambda: bank)
    coord._pre_start(coord._instances())
    coord._pre_start(coord._instances())
    assert bank.loads == 1
    assert coord._solver._bank is bank


def test_llm_is_none_when_disabled():
    coord = _coord(ocr=MagicMock(), bank_factory=_FakeBank)
    coord._pre_start(coord._instances())
    assert coord._solver._llm is None


def test_llm_is_built_when_enabled_with_a_key():
    import copy
    raw = copy.deepcopy(CFG)
    raw["quiz"]["llm"] = {"enabled": True, "api_key": "sk-1"}
    coord = QuizCoordinator(RootConfig.model_validate(raw),
                            event_bus=EventBus(),
                            ocr=MagicMock(), bank_factory=_FakeBank)
    coord._pre_start(coord._instances())
    assert isinstance(coord._solver._llm, LLMClient)


def test_sm_factory_receives_the_quiz_config():
    coord = _coord(ocr=MagicMock(), bank_factory=_FakeBank)
    coord._pre_start(coord._instances())
    handle = MockHandleSource(np.zeros((1080, 1920, 3), dtype=np.uint8))
    sm = coord._sm_factory_for(coord._instances()[0].characters[0], handle,
                               {}, None)
    assert isinstance(sm, QuizStateMachine)
    assert sm._ocr is coord._ocr
    assert sm._bank is coord._bank
    assert sm._solver is coord._solver
    assert sm._verify_delay == 2.5
    assert sm._min_green_ratio == 0.7
    assert sm._max_questions == 12
    assert sm._cooldown_min == 3.0
    assert sm._parse_retries == 4
    assert sm._entry_taps == [(10, 20)]
    assert sm._auto_click is False
    assert sm._char_id == "q0"
    assert coord._solver._fuzzy_threshold == 0.8


def test_config_reads_only_the_quiz_section():
    coord = _coord()
    assert [i.id for i in coord._config.instances_for(AppMode.ZHAIDUO)] == ["z0"]
    assert [i.id for i in coord._instances()] == ["mumu0"]
    assert coord._max_rounds() == 4          # 不是 app.max_rounds=99
