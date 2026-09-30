from __future__ import annotations
from ..infra.config import CharacterConfig, RoleEnum
from .leader_sm import LeaderStateMachine
from .member_sm import MemberStateMachine
from .either_sm import EitherStateMachine


def create_state_machine(character: CharacterConfig, handle_source, recognizers: dict,
                         event_bus=None, rally_tracker=None, ledger=None):
    """Build the state machine matching a character's configured role.

    rally_tracker：进程级集结事件登记簿（runtime 注入），either 车头
    让车/拒绝降级决策用；leader/member 角色不用。publisher_id 用
    character.id，让登记簿区分「自己/对方」的集结事件。
    ledger：进程级动作账本（runtime 注入），发车/填兵确认后写「部队
    在外」，供集结门槛的 L0 判据用；未注入 = 不记账 = 旧行为。"""
    if character.role == RoleEnum.LEADER:
        return LeaderStateMachine(handle_source, recognizers, character.target_level,
                                  character.march_preset,
                                  character.march_troop_types, event_bus,
                                  publisher_id=character.id, ledger=ledger)
    if character.role == RoleEnum.MEMBER:
        # 填兵不使用预设/兵种选择（用户要求 2026-09-09），
        # 故不传 march_preset/march_troop_types
        return MemberStateMachine(handle_source, recognizers,
                                  character.fill_target_leaders,
                                  char_id=character.id, ledger=ledger)
    if character.role == RoleEnum.EITHER:
        return EitherStateMachine(handle_source, recognizers, character.target_level,
                                  character.march_preset, character.march_troop_types,
                                  character.fill_target_leaders, event_bus,
                                  char_id=character.id, rally_tracker=rally_tracker,
                                  ledger=ledger)
    raise ValueError(f"Unknown role: {character.role}")
