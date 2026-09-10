from __future__ import annotations
from .leader_sm import LeaderStateMachine
from .member_sm import MemberStateMachine


class EitherStateMachine:
    """车头或成员（spec 2026-09-09 §4）。

    单次上场流程：搜寨 -> 开集结 -> 不停留，立即转成员流程去填指定车头的
    集结。自己的集结由成员填，满员或倒计时结束自动发车。实现上复用
    Leader/Member 两个状态机，按阶段委托 step()。

    调度器循环契约（WorkerRunner 主循环，与 StateMachine 子类一致）：
    (a) step(context=None) 在 context 为 None 时复用上次存储的 context，
        语义与 StateMachine.step 一致；
    (b) is_terminal() 在 member 阶段到达 END 之前一直为 False，
        调度器需持续调用 step()；
    (c) departed 标志由 LeaderStateMachine 拥有（_wait_members 置位、
        WAIT_MEMBERS -> END 的 guard 消费），调用方不得预置该键；
    (d) leader 阶段放弃（重试耗尽，last_rally_event 为 None）或 member
        阶段 FILTER 耗尽时呈现为终态（is_terminal() True），由 runner
        冷却后整体重建、重试新一轮 —— 与纯 leader/纯 member 的失败
        重试语义一致，不向调用方抛异常。
    """

    def __init__(self, handle_source, recognizers: dict, target_level: int,
                 march_preset: int, march_troop_types: list,
                 fill_target_leaders, event_bus=None):
        # either 角色不等自己的集结（用户要求）：开完立即转成员流程填
        # 他人集结，故 wait_members_seconds=0.0（默认 330s 留给纯车头）
        self._leader = LeaderStateMachine(handle_source, recognizers, target_level,
                                          march_preset, march_troop_types, event_bus,
                                          wait_members_seconds=0.0)
        # 填兵不使用预设（用户要求 2026-09-09）：成员构造不再传 march 参数
        self._member = MemberStateMachine(handle_source, recognizers,
                                          fill_target_leaders)
        self._phase = "leader"
        self.current = "LEADER:IDLE"
        self.history: list[str] = [self.current]
        self._ctx: dict = {}
        self._failed = False

    def step(self, context: dict | None = None) -> None:
        if context is not None:
            self._ctx = context
        ctx = self._ctx
        if self._phase == "leader":
            self._leader.step(ctx)
            self.current = f"LEADER:{self._leader.current}"
            if self._leader.is_terminal():
                if self._leader.last_rally_event:
                    self._phase = "member"
                    self._member.on_rally_launched(self._leader.last_rally_event)
                else:
                    # leader 放弃（no_fortress_found / locked_fortress）：
                    # 呈现为终态，交由 runner 冷却重建重试
                    self._failed = True
        else:
            self._member.step(ctx)
            self.current = f"MEMBER:{self._member.current}"
        self.history.append(self.current)

    def is_terminal(self) -> bool:
        return self._failed or (self._phase == "member" and self._member.is_terminal())

    # ---- 与 StateMachine 子类对齐的读侧委托（runner / GUI 统一访问）----

    @property
    def last_image(self):
        """活动阶段子状态机的最近一帧；member 阶段尚未捕获时回退 leader
        的最后一帧（失败截图/GUI 缩略图用），尚未运行则 None。"""
        active = self._leader if self._phase == "leader" else self._member
        if active.last_image is not None:
            return active.last_image
        return self._leader.last_image

    @property
    def fail_reason(self) -> str | None:
        # leader/member 的 give-up 出口写入共享 ctx（step 传入的同一 dict）
        return self._ctx.get("fail_reason")
