from __future__ import annotations
import time
from .leader_sm import LeaderStateMachine
from .member_sm import MemberStateMachine
from ..infra.logger import get_logger

logger = get_logger(__name__)

# 返城等待：轮询「派遣队列」徽标的间隔与兜底上限（2026-09-11 验收反馈：
# 开完集结+填兵后应等自己的集结部队回城再开下一轮，最大限度保持集结效率）。
_WAIT_RETURN_POLL = 30.0      # 徽标检测间隔（秒）；检测本身是纯截图，无侵入
_WAIT_RETURN_MAX = 1500.0     # 最长等待 25 分钟，超时强制进入下一轮


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
    (d) leader 阶段放弃（重试耗尽，last_rally_event 为 None）时呈现为
        终态（is_terminal() True），由 runner 冷却后整体重建、重试新一轮
        —— 与纯 leader/纯 member 的失败重试语义一致，不向调用方抛异常。
    (e) member 阶段结束后，若本轮开过集结且配置了 queue_badge 识别器
        （「派遣队列」徽标，有部队在城外时出现），进入 WAIT_RETURN 阶段：
        纯截图轮询直到部队回城（徽标消失）才呈现终态，runner 随即开启
        下一轮集结（2026-09-11 验收反馈）。未配置该识别器时行为不变
        （member END 即终态）。
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
        self._wait_deadline = 0.0
        self._next_check = 0.0

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
        elif self._phase == "wait_return":
            self._step_wait_return()
            return   # history/current 已在 _step_wait_return 维护
        else:
            self._member.step(ctx)
            self.current = f"MEMBER:{self._member.current}"
            if self._member.is_terminal():
                if self._leader.last_rally_event \
                        and "queue_badge" in self._leader._rec:
                    # 填兵结束（无论成败）：自己的集结部队还在城外，等它
                    # 回城再开下一轮。queue_badge 未配置时保持原行为
                    # （member END 立即终态）。
                    self._phase = "wait_return"
                    self.current = "WAIT_RETURN"
                    self._wait_deadline = time.time() + _WAIT_RETURN_MAX
                    self._next_check = 0.0
                    logger.info("[等待返城] 填兵结束，开始轮询派遣队列（间隔 %ss，"
                                "上限 %s 分钟）", _WAIT_RETURN_POLL,
                                _WAIT_RETURN_MAX / 60)
                else:
                    self._phase = "done"   # current 保持 MEMBER:END
        self.history.append(self.current)

    def _step_wait_return(self) -> None:
        now = time.time()
        if now >= self._wait_deadline:
            logger.warning("[等待返城] 等待超时（上限 %s 分钟），部队可能仍"
                           "在城外，强制进入下一轮", _WAIT_RETURN_MAX / 60)
            self._phase = "done"
            self.current = "MEMBER:END"
            self.history.append(self.current)
            return
        if now < self._next_check:
            return   # 未到检测间隔：本次空转（维持 WAIT_RETURN 状态）
        self._next_check = now + _WAIT_RETURN_POLL
        # 战争列表开着会盖住徽标区域（member VERIFY_JOINED 结束时重开了
        # 面板）：先关面板再读徽标 —— 2026-09-12 实机：行军后 2s 首查即
        # 误判「已回城」（面板开着徽标不可见），部队其实刚出发。刚点完
        # X 的那拍画面未及刷新，本周期不下结论，下个周期再读
        if self._leader._find("war_title"):
            self._leader._handle.click(1671, 64)
            return
        r = self._leader._find("queue_badge")
        if r is not None and r.matched:
            logger.info("[等待返城] 派遣队列非空，部队仍在城外")
            return
        logger.info("[等待返城] 派遣队列已空，集结部队已回城，本轮完成")
        self._phase = "done"
        self.current = "MEMBER:END"
        self.history.append(self.current)

    def is_terminal(self) -> bool:
        return self._failed or self._phase == "done"

    # ---- 与 StateMachine 子类对齐的读侧委托（runner / GUI 统一访问）----

    @property
    def last_image(self):
        """活动阶段子状态机的最近一帧；member 阶段尚未捕获时回退 leader
        的最后一帧（失败截图/GUI 缩略图用），尚未运行则 None。返城等待
        阶段的检测截图经 leader 的 _find 捕获，同样取 leader 帧。"""
        active = self._member if self._phase == "member" else self._leader
        if active.last_image is not None:
            return active.last_image
        return self._leader.last_image

    @property
    def fail_reason(self) -> str | None:
        # leader/member 的 give-up 出口写入共享 ctx（step 传入的同一 dict）
        return self._ctx.get("fail_reason")
