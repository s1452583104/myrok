import numpy as np
from rok_assistant.infra.config import CharacterConfig, RoleEnum
from rok_assistant.workers.factory import create_state_machine
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.workers.either_sm import EitherStateMachine
from rok_assistant.core.handle_source import MockHandleSource


def _char(role, levels=(8,)):
    return CharacterConfig(id="c1", name="H", role=role, target_levels=list(levels),
                           march_preset=1, march_troop_types=["infantry"],
                           fill_target_leaders=[{"instance": "i1", "name": "Boss"}]
                           if role != RoleEnum.LEADER else [])


def _handle():
    return MockHandleSource(screenshot=np.zeros((10, 10, 3), dtype=np.uint8))


def test_factory_builds_leader():
    sm = create_state_machine(_char(RoleEnum.LEADER), _handle(), {})
    assert isinstance(sm, LeaderStateMachine)


def test_factory_builds_member():
    sm = create_state_machine(_char(RoleEnum.MEMBER), _handle(), {})
    assert isinstance(sm, MemberStateMachine)
    # 填兵不使用预设（用户要求 2026-09-09）：member 构造不接收 march 参数
    assert not hasattr(sm, "_march_preset")
    assert not hasattr(sm, "_march_troop_types")


def test_factory_builds_either():
    sm = create_state_machine(_char(RoleEnum.EITHER), _handle(), {})
    assert isinstance(sm, EitherStateMachine)


def test_factory_passes_level_list_through_in_order():
    """多等级列表要**原样按序**传给两个开车角色（不得重排/截断）。"""
    levels = (6, 4, 5)
    lead = create_state_machine(_char(RoleEnum.LEADER, levels), _handle(), {})
    assert lead._target_levels == [6, 4, 5]
    either = create_state_machine(_char(RoleEnum.EITHER, levels), _handle(), {})
    assert either._leader._target_levels == [6, 4, 5]


def test_create_gem_state_machine_wires_config_through():
    """宝石模式没有角色分工：一个实例一个号，参数全从 GemConfig 来。

    输入**全部取非默认值**，否则「没接线」与「接上了但值正好等于默认」
    分不开。`idle_wait_*` 在配置里是**分钟**，SM 里存**秒**。
    """
    from rok_assistant.core.handle_source import MockHandleSource
    from rok_assistant.infra.config import GemCharacterConfig
    from rok_assistant.workers.factory import create_gem_state_machine
    from rok_assistant.workers.gem_sm import GemStateMachine

    handle = MockHandleSource(np.zeros((1080, 1920, 3), dtype=np.uint8))
    sm = create_gem_state_machine(
        GemCharacterConfig(id="c0", name="主号"), handle, {},
        queue_limit=7, scan_rings=4, scan_drag_px=640, scan_drag_ms=350,
        idle_wait_min=12.5, idle_wait_max=41.0)
    assert isinstance(sm, GemStateMachine)
    assert sm._queue_limit == 7
    assert sm._scan_rings == 4
    assert sm._scan_drag_px == 640
    assert sm._scan_drag_ms == 350
    assert sm._idle_wait_min == 12.5 * 60.0      # 分钟 → 秒
    assert sm._idle_wait_max == 41.0 * 60.0
    assert sm._char_id == "c0"
    assert sm.current == "IDLE"


def test_create_quiz_state_machine_forwards_the_config(monkeypatch):
    """答题工厂：配置字段必须**逐项**走到 SM 上，不能有「声明了没人读」的。

    `entry_taps` 在配置里是 list[list[int]]、SM 里是 list[tuple[int, int]]。
    """
    from unittest.mock import MagicMock

    import numpy as np

    from rok_assistant.core.handle_source import MockHandleSource
    from rok_assistant.infra.config import NoRoleCharacterConfig
    from rok_assistant.workers.factory import create_quiz_state_machine
    import rok_assistant.workers.factory as factory_mod

    captured = {}

    class _FakeSM:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setattr(factory_mod, "QuizStateMachine", _FakeSM)
    char = NoRoleCharacterConfig(id="c0", name="答题号")
    handle = MockHandleSource(np.zeros((1080, 1920, 3), dtype=np.uint8))
    ocr, bank, solver = MagicMock(), MagicMock(), MagicMock()
    create_quiz_state_machine(
        char, handle, {"t": 1}, ocr, bank, solver,
        verify_delay=2.5, min_green_ratio=0.7,
        max_questions_per_round=12, round_cooldown_min=3.0,
        parse_retries=4, entry_taps=[[10, 20]], auto_click=False)

    assert captured["args"] == (handle,)
    kwargs = captured["kwargs"]
    assert kwargs["ocr"] is ocr
    assert kwargs["bank"] is bank
    assert kwargs["solver"] is solver
    assert kwargs["recognizers"] == {"t": 1}
    assert kwargs["verify_delay"] == 2.5
    assert kwargs["min_green_ratio"] == 0.7
    assert kwargs["max_questions_per_round"] == 12
    assert kwargs["round_cooldown_min"] == 3.0
    assert kwargs["parse_retries"] == 4
    assert kwargs["entry_taps"] == [(10, 20)]      # 转成元组
    assert kwargs["auto_click"] is False
    assert kwargs["char_id"] == "c0"
