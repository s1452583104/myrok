from __future__ import annotations
from .state_machine import StateMachine
from ..infra.logger import get_logger

logger = get_logger(__name__)

# 战争列表检索/加入的重试上限：列表开着原地轮询（每轮 ~3s），
# 联盟集结每 ~5 分钟开一轮，30s 内没有可加入的就放弃本轮（runner
# 冷却重建后重试），避免无限占住成员阶段。
_JOIN_POLL_TIMEOUT = 3.0
_JOIN_MAX_ATTEMPTS = 10
_PANEL_MAX_ATTEMPTS = 10


class MemberStateMachine(StateMachine):
    """成员填兵（2026-09-11 实机验证的真实链路）：

    地图右下角联盟旗帜 -> 战争列表（直接落在列表，无需再点战争页签）
    -> 点目标行的绿色「+加入」-> 即以默认部队加入并发兵。

    关键实机事实：
    - 点「+」没有部队表单、没有行军按钮：游戏直接用默认兵队出兵，
      天然满足「填兵不使用预设操作，直接使用默认的」（用户要求
      2026-09-09），因此旧链路的 FORM_TROOP/LAUNCH 全部删除。
    - 行内按钮三态：绿「+加入」=可加入；橙「替换」=已加入；
      红「X取消」=自己开的集结（不可加入自己）。
    - 战争列表排序（距离最近/最新发起）面板会记住上次选择，v1 不主动切。
    - 搜索面板开着时右下角旗帜被底部搜索栏替换（搜索模式专属底栏），
      归一化需先退搜索（search_back）。

    按名字匹配指定车头是后续里程碑（ACCEPTANCE §3.7）；当前加入列表里
    第一个可加入的集结。失败语义：重试耗尽经 _exhausted 写
    ctx['fail_reason'] 呈现终态，由 runner 冷却重建重试；环境异常
    （旗帜不可见）直接抛 RuntimeError 走 runner 错误路径（带截图）。
    """

    def __init__(self, handle_source, recognizers: dict, fill_target_leaders):
        self._handle = handle_source
        self._rec = recognizers
        self._fill_targets = fill_target_leaders
        self._pending_event = None
        self.last_event = None  # 消费后的 launch 事件留存（供调用方/测试断言）
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "WAIT_LAUNCH_EVENT", self._consume_event,
                            guard=lambda ctx: self._pending_event is not None)
        self.add_transition("WAIT_LAUNCH_EVENT", "SWITCH_TO_SELF", self._switch_to_self)
        self.add_transition("SWITCH_TO_SELF", "NORMALIZE", self._normalize_view)
        self.add_transition("NORMALIZE", "OPEN_WAR", self._open_war)
        # 耗尽出口必须注册在对应重试边之前：StateMachine.step 按注册顺序
        # 取第一个 from_state 匹配且 guard 通过的转移。
        self.add_transition("OPEN_WAR", "END", self._exhausted,
                            guard=lambda ctx: ctx.get("war_attempts", 0) > _PANEL_MAX_ATTEMPTS)
        self.add_transition("OPEN_WAR", "OPEN_WAR", self._open_war,
                            guard=lambda ctx: not ctx.get("panel_open"))
        self.add_transition("OPEN_WAR", "FIND_JOIN", lambda ctx: None,
                            guard=lambda ctx: ctx.get("panel_open"))
        self.add_transition("FIND_JOIN", "CLICK_JOIN", self._click_join,
                            guard=lambda ctx: ctx.get("join_found"))
        self.add_transition("FIND_JOIN", "END", self._exhausted,
                            guard=lambda ctx: ctx.get("join_attempts", 0) > _JOIN_MAX_ATTEMPTS)
        self.add_transition("FIND_JOIN", "FIND_JOIN", self._poll_join,
                            guard=lambda ctx: not ctx.get("join_found"))
        # guard 先于 action 求值：点击与验证在 CLICK_JOIN 的入口 action
        # 里完成，ctx['joined'] 供下面两条边的 guard 使用
        self.add_transition("CLICK_JOIN", "END", lambda ctx: None,
                            guard=lambda ctx: ctx.get("joined"))
        self.add_transition("CLICK_JOIN", "OPEN_WAR", self._join_missed,
                            guard=lambda ctx: not ctx.get("joined"))

    def on_rally_launched(self, event: dict) -> None:
        self._pending_event = event

    def _consume_event(self, ctx):
        self.last_event = self._pending_event
        self._pending_event = None

    def _switch_to_self(self, ctx):
        # v1: 每个实例单角色，无需切换（多角色切换是 v2）
        pass

    def _normalize_view(self, ctx):
        # 地图视图的标志是右下角联盟旗帜可见。搜索面板开着时底部栏变成
        # 搜索目标栏、旗帜不可见（2026-09-11 实机），先退搜索；城市视图
        # 则点 map_btn 回地图。
        if self._find("alliance_btn"):
            return
        if self._find("search_back"):
            self._click("search_back")
        elif self._find("map_btn"):
            self._click("map_btn")
        if not self._wait_for("alliance_btn", timeout=8.0):
            raise RuntimeError("联盟旗帜不可见：既不在地图视图，退搜索也没找到")

    def _open_war(self, ctx):
        ctx["war_attempts"] = ctx.get("war_attempts", 0) + 1
        # 已在战争列表（来自 VERIFY_JOINED 的重试回流）就不必再点旗帜：
        # 面板开着时旗帜被遮住/点空，反而把面板点没了
        if self._find("war_title"):
            ctx["panel_open"] = True
            return
        if not self._click_retry("alliance_btn"):
            logger.info("成员·联盟旗帜不可见，重试 (%s/%s)",
                        ctx["war_attempts"], _PANEL_MAX_ATTEMPTS)
            ctx["panel_open"] = False
            return
        ctx["panel_open"] = self._wait_for("war_title", timeout=6.0)
        if ctx["panel_open"]:
            logger.info("成员·战争列表已打开")

    def _poll_join(self, ctx):
        # 原地轮询绿「+」：联盟集结每隔几分钟才开一轮，列表可能暂时为空
        ctx["join_attempts"] = ctx.get("join_attempts", 0) + 1
        n, cap = ctx["join_attempts"], _JOIN_MAX_ATTEMPTS
        ctx["join_found"] = self._wait_for("join_btn", timeout=_JOIN_POLL_TIMEOUT)
        if ctx["join_found"]:
            return
        logger.info("成员·暂无可加入的集结，继续等 (%s/%s)", n, cap)

    def _click_join(self, ctx):
        # 点「+」即以默认部队加入并发兵（无表单，见类注释），一步完成；
        # 成功标志是目标行按钮从绿「+」变成橙「替换」
        ctx["joined"] = False
        if self._click_retry("join_btn"):
            logger.info("成员·点击加入集结")
            ctx["joined"] = self._wait_for("swap_btn", timeout=6.0)

    def _join_missed(self, ctx):
        # 点了「+」但没出现「替换」：点击未生效，重开列表再找
        logger.warning("成员·加入未生效，重开战争列表重试")

    def _exhausted(self, ctx):
        # 重试耗尽：置失败标记。fail_reason 由 WorkerRunner 在终态的
        # status_update payload 中带出；冷却重建后的 SM 自动重试新一轮。
        ctx["failed"] = True
        ctx["fail_reason"] = "no_rally_found"
        logger.warning("成员·重试耗尽，本轮放弃填兵")

    def is_terminal(self) -> bool:
        return self.current == "END"
