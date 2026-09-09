from __future__ import annotations
from ..infra.config import CharacterConfig, RoleEnum
from .leader_sm import LeaderStateMachine
from .member_sm import MemberStateMachine
from .either_sm import EitherStateMachine


def create_state_machine(character: CharacterConfig, handle_source, recognizers: dict,
                         event_bus=None):
    """Build the state machine matching a character's configured role."""
    if character.role == RoleEnum.LEADER:
        return LeaderStateMachine(handle_source, recognizers, character.target_level,
                                  character.march_preset,
                                  character.march_troop_types, event_bus)
    if character.role == RoleEnum.MEMBER:
        return MemberStateMachine(handle_source, recognizers, character.march_preset,
                                  character.march_troop_types,
                                  character.fill_target_leaders)
    if character.role == RoleEnum.EITHER:
        return EitherStateMachine(handle_source, recognizers, character.target_level,
                                  character.march_preset, character.march_troop_types,
                                  character.fill_target_leaders, event_bus)
    raise ValueError(f"Unknown role: {character.role}")
