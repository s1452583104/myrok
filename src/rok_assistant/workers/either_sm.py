from __future__ import annotations
import random
import time
from .leader_sm import LeaderStateMachine
from .member_sm import MemberStateMachine
from .queue_gate import GateDecision, QueueGate
from ..coordination.action_ledger import ActionLedger
from ..infra.anti_detection import AntiDetectionConfig, HumanProfile
from ..infra.logger import get_logger

logger = get_logger(__name__)

# 返城等待：轮询「派遣队列」徽标的间隔与兜底上限（2026-09-11 验收反馈：
# 开完集结+填兵后应等自己的集结部队回城再开下一轮，最大限度保持集结效率）。
_WAIT_RETURN_POLL = 30.0      # 徽标检测间隔（秒）；检测本身是纯截图，无侵入
_WAIT_RETURN_MAX = 1500.0     # 最长等待 25 分钟，超时强制进入下一轮
# 对方集结事件的有效窗：集结准备窗 5 分钟 + 行军/战斗余量。窗内不开自己的
# 集结（同一城寨同时只能一个联盟集结，后发者被游戏静默拒绝 —— 2026-09-18
# run11 实锤：两号行军点击仅差 4s，后发的表单关闭、无 toast、无队列），
# 直接转填对方的集结
_FOREIGN_RALLY_WINDOW = 480.0
# 车头错峰抖动上限：两号步调锁步是静默拒绝的根因，开搜前随机等待让
# 「谁先发起」逐轮轮换，两个号都能练到车头与填兵
_LEAD_JITTER_MAX = 45.0


class _NullTracker:
    """未注入集结事件登记簿时的空实现：让车/跳过特性整体关闭，行为与
    旧版一致（单账号运行、纯 leader/member 角色均不受影响）。"""

    def last_foreign_launch(self, char_id: str, max_age: float):
        return None

    def last_foreign_skip(self, char_id: str, max_age: float):
        return None
# 门槛「未知队列图标」宽限期：徽标在但已知图标都不可辨时 fail-closed 拦截
# 搜索；若该状态持续超过宽限期（疑似未知良性队列），放行并告警
# —— 2026-09-14 实机：旧模板背景像素敏感（正样本掉到 0.72/0.88）导致
# 误判「仅采集/已回城」提前开下一轮集结，改为未知不轻易放行。
# 2026-09-16：5 分钟宽限曾把「主将未回城」误放行 → 默认武将代开车打不过
# 寨子，放宽到 15 分钟（一个行军+战斗+返程周期通常 ≤12 分钟）
_QUEUE_UNKNOWN_GRACE = 900.0


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

    def __init__(self, handle_source, recognizers: dict, target_levels: list[int],
                 march_preset: int, march_troop_types: list,
                 fill_target_leaders, event_bus=None, char_id: str = "?",
                 rally_tracker=None, ledger=None, human=None,
                 march_presets=None):
        self._bus = event_bus
        self._char_id = char_id
        # 本类无基类：human 不会被 super().__init__ 落到 self._human，须自行
        # 存储（返城检测间隔经它抖动）。未注入时确定性 profile，行为同旧版。
        self._human = human if human is not None else HumanProfile(
            AntiDetectionConfig(debug_no_jitter=True))
        # 进程级动作账本（runtime 注入）：转交两个子状态机，发车/填兵确认
        # 后由它们写「部队在外」。门槛判据读它（见下）。未注入时自建一本
        # （单账号/测试场景），保证判据逻辑一致
        self._ledger = ledger if ledger is not None else ActionLedger()
        # 门槛判据（2026-09-30）：多帧投票 + 账本覆盖 unknown。
        self._gate = QueueGate(self._ledger, self._char_id,
                               unknown_grace=_QUEUE_UNKNOWN_GRACE)
        # 进程级集结事件登记簿（runtime 注入，跨 SM 重建存活）：查「对方
        # 的集结/让车事件」决定本轮开不开集结；未注入时空实现=特性关闭
        self._tracker = rally_tracker if rally_tracker is not None else _NullTracker()
        self._jitter_done = False
        # either 角色不等自己的集结（用户要求）：开完立即转成员流程填
        # 他人集结，故 wait_members_seconds=0.0（默认 330s 留给纯车头）。
        # queue_gate 刻意不传：either 自己那面门（self._gate）已经在
        # step() 里观测同一份判读，再给子车头一面会让 QueueGate 的内部
        # 投票/计时器被喂两遍，采信节奏翻倍
        self._leader = LeaderStateMachine(handle_source, recognizers, target_levels,
                                          march_preset, march_troop_types, event_bus,
                                          wait_members_seconds=0.0,
                                          publisher_id=self._char_id,
                                          ledger=self._ledger, human=human,
                                          march_presets=march_presets)
        # 填兵不使用预设（用户要求 2026-09-09）：成员构造不再传 march 参数。
        # char_id 必须传：成员填兵确认后要按本账号 id 写账本，缺省 "?" 会把
        # 事实记到错误（共享）名下
        self._member = MemberStateMachine(handle_source, recognizers,
                                          fill_target_leaders,
                                          char_id=self._char_id,
                                          ledger=self._ledger, human=human)
        self._phase = "leader"
        self.current = "LEADER:IDLE"
        self.history: list[str] = [self.current]
        self._ctx: dict = {}
        self._failed = False
        self._wait_deadline = 0.0
        self._next_check = 0.0
        self._gate_next_log = 0.0
        self._gate_last_msg = ""

    def step(self, context: dict | None = None) -> None:
        if context is not None:
            self._ctx = context
        ctx = self._ctx
        if self._phase == "leader":
            # 搜索-集结前置门槛（2026-09-13 用户要求）：上一轮集结部队
            # 未回城就搜下一轮，会搜到上轮已锁定的城寨、且车头回不了城。
            # 判据自 2026-09-30 起交给 QueueGate：多帧投票（L1）滤掉单帧
            # 噪声，unknown 时改问进程级动作账本（L0）而不是干等计时器，
            # 账本无记录（进程刚起/换账号）才退回旧的 fail-closed + 宽限。
            # 只在轮次入口（IDLE/NORMALIZE）拦截，日志 30s 节流
            if self._leader.current in ("IDLE", "NORMALIZE"):
                outcome = self._gate.observe(self._queue_verdict())
                if outcome.decision is GateDecision.WAIT:
                    self._gate_log(outcome.reason)
                    return
                if outcome.source != "vote":
                    # 判据来源不是投票 = 是账本/兜底放行的，必须留痕：
                    # 「为什么这轮放行了」在实机上是最难查的一类问题
                    logger.warning("[集结门槛] 放行（判据来源 %s）：%s",
                                   outcome.source, outcome.reason)
                # 让车门槛（2026-09-18 run11 实锤）：窗内对方已发起集结时，
                # 同一城寨再开集结会被游戏静默拒绝（表单关闭、无 toast、无
                # 队列徽标）。窗内不开自己的集结，直接转成员流程填对方的。
                # 必须先于错峰抖动判定：skip 要立刻生效，不能先睡 45s
                foreign = self._tracker.last_foreign_launch(
                    self._char_id, _FOREIGN_RALLY_WINDOW)
                if foreign is not None:
                    logger.info("[集结门槛] 对方(%s)的集结已在准备窗内，本轮"
                                "跳过开集结，直接转填兵",
                                foreign.get("char_id", "?"))
                    if self._bus is not None:
                        self._bus.publish("rally_skipped",
                                          {"char_id": self._char_id})
                    self._phase = "member"
                    self._member.on_rally_launched(foreign)
                    self.current = f"MEMBER:{self._member.current}"
                    self.history.append(self.current)
                    return
                # 车头错峰抖动（一次性）：两号步调锁步是静默拒绝的根因，
                # 开搜前随机等待让「谁先发起」逐轮轮换，两个号都能练到
                # 车头与填兵
                if not self._jitter_done:
                    self._jitter_done = True
                    delay = random.uniform(0.0, _LEAD_JITTER_MAX)
                    if delay >= 1.0:
                        logger.info("[车头] 错峰等待 %.0fs 后开始搜索", delay)
                        time.sleep(delay)
            self._leader.step(ctx)
            self.current = f"LEADER:{self._leader.current}"
            if self._leader.is_terminal():
                if self._leader.last_rally_event:
                    self._phase = "member"
                    self._member.on_rally_launched(self._leader.last_rally_event)
                elif ctx.get("fail_reason") == "rally_rejected" \
                        and self._tracker.last_foreign_launch(
                            self._char_id, _FOREIGN_RALLY_WINDOW) is not None:
                    # 自己被静默拒绝且窗内对方确有集结：竞态输家经历，
                    # 不计失败（fail_streak 会误触连续失败停机），冷却
                    # 重建后由让车门槛直接转填兵
                    logger.info("[车头] 集结被拒（对方已先在该城寨发起），"
                                "本轮按轮空完成处理")
                    ctx.pop("failed", None)
                    ctx.pop("fail_reason", None)
                    self._phase = "done"
                    self.current = "LEADER:END"
                else:
                    # leader 放弃（no_fortress_found / locked_fortress）：
                    # 呈现为终态，交由 runner 冷却重建重试
                    self._failed = True
        elif self._phase == "wait_return":
            self._step_wait_return()
            return   # history/current 已在 _step_wait_return 维护
        else:
            # 提前收尾（2026-09-18 run11 实锤）：自己跳过了开集结（填对方
            # 的），对方也发不出可填的集结（rally_skipped=它转填了我方的）
            # 或其集结被静默拒绝时，成员流程找不到集结只会白烧 6 分钟轮询。
            # 对方有跳过记录且成员尚未走到终态 → 立即转入返城等待
            if not self._member.is_terminal() \
                    and self._tracker.last_foreign_skip(
                        self._char_id, _FOREIGN_RALLY_WINDOW) is not None:
                logger.info("[成员] 对方已转填我方集结（无集结可填），成员"
                            "阶段提前收尾")
                ctx.pop("failed", None)
                ctx.pop("fail_reason", None)
                self._enter_wait_return()
                self.history.append(self.current)
                return
            self._member.step(ctx)
            self.current = f"MEMBER:{self._member.current}"
            if self._member.is_terminal():
                if ctx.get("fail_reason") == "no_rally_found" \
                        and self._leader.last_rally_event is not None:
                    # 自己的集结已发起且部队在途，对方无集结可填（对方转填
                    # 我方集结 / 对方开集结被拒）：轮空不计失败（fail_streak
                    # 会误触连续失败停机），等自己的部队回城即可
                    logger.info("[成员] 指定车头无集结可填，但自己的集结已在"
                                "途：按轮空完成处理")
                    ctx.pop("failed", None)
                    ctx.pop("fail_reason", None)
                self._enter_wait_return()
        self.history.append(self.current)

    def _enter_wait_return(self) -> None:
        """填兵阶段收口：本轮开过集结且配置了徽标识别器时进入返城等待
        （纯截图轮询），否则保持旧行为（member END 即终态）。"""
        if self._leader.last_rally_event and "queue_badge" in self._leader._rec:
            self._phase = "wait_return"
            self.current = "WAIT_RETURN"
            self._wait_deadline = time.time() + _WAIT_RETURN_MAX
            self._next_check = 0.0
            logger.info("[等待返城] 填兵结束，开始轮询派遣队列（间隔 %ss，"
                        "上限 %s 分钟）", _WAIT_RETURN_POLL,
                        _WAIT_RETURN_MAX / 60)
        else:
            self._phase = "done"   # current 保持 MEMBER:END

    def _queue_verdict(self) -> str:
        """右侧 */5 派遣队列判读 —— 实现在 LeaderStateMachine.queue_verdict。

        2026-10-04 搬家：整段只用 leader 的 _rec/_find/_handle，而纯 leader
        角色也需要它（集结前置门槛）。留这层薄壳是为了两点：either 自己的
        门槛调用点不变，以及既有测试对 either 实例打 monkeypatch
        （test_either_sm_gate 的 setattr(sm, "_queue_verdict", ...)）继续有效。
        """
        return self._leader.queue_verdict()

    def _gate_log(self, message: str) -> None:
        # 30s 节流，但换了理由立刻打（与 leader_sm._gate_log 同一口径）：
        # 每轮第一拍固定是「投票 1/3 帧」，它若吃掉节流窗口，随后真正采信
        # 的那条理由就被压掉，日志会读成「门槛放行了」
        now = time.time()
        if message != self._gate_last_msg or now >= self._gate_next_log:
            self._gate_last_msg = message
            self._gate_next_log = now + 30.0
            logger.info("[集结门槛] %s", message)

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
        self._next_check = now + self._human.jitter(_WAIT_RETURN_POLL)
        # 战争列表开着会盖住徽标区域（member VERIFY_JOINED 结束时重开了
        # 面板）：先关面板再读徽标 —— 2026-09-12 实机：行军后 2s 首查即
        # 误判「已回城」（面板开着徽标不可见），部队其实刚出发。刚点完
        # X 的那拍画面未及刷新，本周期不下结论，下个周期再读
        if self._leader._find("war_title"):
            self._leader._handle.click(1671, 64)
            return
        verdict = self._queue_verdict()
        if verdict == "battle":
            logger.info("[等待返城] 行军/驻扎队列仍在城外")
            return
        if verdict == "returning":
            # 返程中：部队确实还在城外，但按 2026-10-09 的「返回中放行」
            # 决策收轮（与门槛同一口径）。**不写 mark_troops_home** ——
            # 账本只记已确认的事实，部队确实还没回城。
            logger.info("[等待返城] 队列返程中，按「返回中放行」收轮")
            self._phase = "done"
            self.current = "MEMBER:END"
            self.history.append(self.current)
            return
        if verdict == "gather":
            logger.info("[等待返城] 城外仅采集队列，不影响开集结，本轮完成")
            self._phase = "done"
            self.current = "MEMBER:END"
            self.history.append(self.current)
            return
        if verdict == "unknown":
            # 徽标在但图标不可辨：继续等（有 25 分钟上限兜底），不轻易
            # 判「已回城」—— 2026-09-14 实机两次误判均源于此路径放行
            logger.info("[等待返城] 队列徽标在但图标不可辨，谨慎起见继续"
                        "等待")
            return
        logger.info("[等待返城] 派遣队列已空，集结部队已回城，本轮完成")
        # 账本写入点：队列判空 = 部队确实回城（唯一确认口径，非「停止轮询」）。
        # 清 troops_out 让下一轮门槛的 L0 判据不再误以为部队仍在外
        self._ledger.mark_troops_home(self._char_id)
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
