from __future__ import annotations
from ..infra.config import CharacterConfig, RoleEnum
from .leader_sm import LeaderStateMachine
from .member_sm import MemberStateMachine
from .either_sm import EitherStateMachine
from .queue_gate import QueueGate


def create_state_machine(character: CharacterConfig, handle_source, recognizers: dict,
                         event_bus=None, rally_tracker=None, ledger=None,
                         human=None):
    """Build the state machine matching a character's configured role.

    rally_tracker：进程级集结事件登记簿（runtime 注入），either 车头
    让车/拒绝降级决策用；leader/member 角色不用。publisher_id 用
    character.id，让登记簿区分「自己/对方」的集结事件。
    ledger：进程级动作账本（runtime 注入），发车/填兵确认后写「部队
    在外」，供集结门槛的 L0 判据用；未注入 = 不记账 = 旧行为。
    human：反检测 HumanProfile（runtime 注入）；未注入时状态机用确定性
    默认 profile（debug_no_jitter），行为与改动前逐字相同。"""
    if character.role == RoleEnum.LEADER:
        # 集结前置门槛（2026-10-04 bug：纯车头不查队列，主将还在城外就
        # 开集结，「创建部队」载不出预设 → 卡在「预设槽 1 高亮未确认」）。
        # 门槛原先只接在 either 上，纯 leader 拿到的是裸状态机。账本未
        # 注入时特性关闭（与 ledger 参数的既有语义一致）。
        gate = QueueGate(ledger, character.id) if ledger is not None else None
        return LeaderStateMachine(handle_source, recognizers, character.target_levels,
                                  event_bus=event_bus,
                                  publisher_id=character.id, ledger=ledger,
                                  queue_gate=gate, human=human,
                                  march_presets=[(p.preset, list(p.troops))
                                                 for p in character.march_presets])
    if character.role == RoleEnum.MEMBER:
        # 填兵不使用预设/兵种选择（用户要求 2026-09-09），
        # 故不传 march_preset/march_troop_types
        # event_driven=True：一次信号填完所有点名车头，不记轮次（2026-10-09）
        return MemberStateMachine(handle_source, recognizers,
                                  character.fill_target_leaders,
                                  char_id=character.id, ledger=ledger,
                                  human=human, event_driven=True)
    if character.role == RoleEnum.EITHER:
        return EitherStateMachine(handle_source, recognizers, character.target_levels,
                                  character.march_preset, character.march_troop_types,
                                  character.fill_target_leaders, event_bus,
                                  char_id=character.id, rally_tracker=rally_tracker,
                                  ledger=ledger, human=human,
                                  march_presets=[(p.preset, list(p.troops))
                                                 for p in character.march_presets])
    raise ValueError(f"Unknown role: {character.role}")
