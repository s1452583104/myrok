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
