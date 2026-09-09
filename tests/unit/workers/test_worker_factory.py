import numpy as np
from rok_assistant.infra.config import CharacterConfig, RoleEnum
from rok_assistant.workers.factory import create_state_machine
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.workers.either_sm import EitherStateMachine
from rok_assistant.core.handle_source import MockHandleSource


def _char(role):
    return CharacterConfig(id="c1", name="H", role=role, target_level=8,
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


def test_factory_builds_either():
    sm = create_state_machine(_char(RoleEnum.EITHER), _handle(), {})
    assert isinstance(sm, EitherStateMachine)
