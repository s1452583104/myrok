from __future__ import annotations
from .leader_sm import LeaderStateMachine
from .member_sm import MemberStateMachine


class EitherStateMachine:
    """车头或成员（spec 2026-09-09 §4）。

    单次上场流程：搜寨 -> 开集结 -> 不停留，立即转成员流程去填指定车头的
    集结。自己的集结由成员填，满员或倒计时结束自动发车。实现上复用
    Leader/Member 两个状态机，按阶段委托 step()：leader 到 WAIT_MEMBERS
    即置 departed 直接收尾，随后把 launch 事件交给 member 状态机。
    """

    def __init__(self, handle_source, recognizers: dict, target_level: int,
                 march_preset: int, march_troop_types: list,
                 fill_target_leaders, event_bus=None):
        self._leader = LeaderStateMachine(handle_source, recognizers, target_level,
                                          march_preset, march_troop_types, event_bus)
        self._member = MemberStateMachine(handle_source, recognizers, march_preset,
                                          march_troop_types, fill_target_leaders)
        self._phase = "leader"
        self.current = "LEADER:IDLE"
        self.history: list[str] = [self.current]
        self._ctx: dict = {}

    def step(self, context: dict | None = None) -> None:
        if context is not None:
            self._ctx = context
        ctx = self._ctx
        if self._phase == "leader":
            self._leader.step(ctx)
            if self._leader.current == "WAIT_MEMBERS":
                ctx.setdefault("departed", True)  # 不等待，即刻交棒
            self.current = f"LEADER:{self._leader.current}"
            if self._leader.is_terminal():
                self._phase = "member"
                if self._leader.last_rally_event:
                    self._member.on_rally_launched(self._leader.last_rally_event)
        else:
            self._member.step(ctx)
            self.current = f"MEMBER:{self._member.current}"
        self.history.append(self.current)

    def is_terminal(self) -> bool:
        return self._phase == "member" and self._member.is_terminal()
