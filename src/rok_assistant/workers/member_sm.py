from __future__ import annotations
from .state_machine import StateMachine

class MemberStateMachine(StateMachine):
    """成员填兵。用户要求（2026-09-09）：填兵不使用预设操作，直接使用默认的即可 —
    打开创建部队弹窗后直接点行军，使用游戏默认兵队。march_preset/march_troop_types
    只在该角色担任集结车头时才有意义（见 LeaderStateMachine）。
    """

    def __init__(self, handle_source, recognizers: dict, fill_target_leaders,
                 switcher=None):
        self._handle = handle_source
        self._rec = recognizers
        self._filter = fill_target_leaders  # 按 OCR 名字匹配车头是后续里程碑（ACCEPTANCE §3.7）；当前排序后加入第一个集结
        self._switcher = switcher
        self._pending_event = None
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "WAIT_LAUNCH_EVENT",
                            lambda ctx: None,
                            guard=lambda ctx: self._pending_event is not None)
        self.add_transition("WAIT_LAUNCH_EVENT", "SWITCH_TO_SELF", self._switch_to_self)
        self.add_transition("SWITCH_TO_SELF", "NORMALIZE", self._normalize_view)
        self.add_transition("NORMALIZE", "OPEN_ALLIANCE", self._open_alliance)
        self.add_transition("OPEN_ALLIANCE", "OPEN_WAR", self._open_war)
        self.add_transition("OPEN_WAR", "SORT_BY_NEAREST", self._sort_nearest)
        self.add_transition("SORT_BY_NEAREST", "FILTER", self._filter_rally)
        self.add_transition("FILTER", "CLICK_JOIN", self._click_join,
                            guard=lambda ctx: ctx.get("rally_found"))
        self.add_transition("FILTER", "OPEN_WAR", self._open_war,
                            guard=lambda ctx: not ctx.get("rally_found"))
        self.add_transition("CLICK_JOIN", "FORM_TROOP", self._form_troop)
        self.add_transition("FORM_TROOP", "LAUNCH", self._launch)
        self.add_transition("LAUNCH", "SWITCH_BACK", self._switch_back)
        self.add_transition("SWITCH_BACK", "END", lambda ctx: None)

    def on_rally_launched(self, event: dict) -> None:
        self._pending_event = event

    def _switch_to_self(self, ctx):
        # v1: 每个实例单角色，无需切换（多角色切换是 v2）
        pass

    def _normalize_view(self, ctx):
        # alliance_btn 在地图视图底部栏；城市视图下底部左侧是 map_btn
        # （ACCEPTANCE §1.5.2）。search_icon 可见即已在地图视图。
        if self._find("search_icon"):
            return
        self._click("map_btn")
        self._wait_for("search_icon", timeout=6.0)

    def _open_alliance(self, ctx):
        self._click_retry("alliance_btn")

    def _open_war(self, ctx):
        ctx["war_attempts"] = ctx.get("war_attempts", 0) + 1
        self._click_retry("war_btn")

    def _sort_nearest(self, ctx):
        self._click_retry("sort_nearest")

    def _filter_rally(self, ctx):
        # fill_target_leaders 按 OCR 名字匹配车头是后续里程碑（ACCEPTANCE §3.7）；
        # 当前排序后加入第一个集结。
        ctx["rally_found"] = ctx.get("war_attempts", 1) <= 10

    def _click_join(self, ctx):
        self._click_retry("join_btn")

    def _form_troop(self, ctx):
        # 只等待创建部队弹窗（march_btn 可见）；不点预设槽位、不点兵种图标 —
        # 使用游戏默认兵队（用户要求 2026-09-09）。
        self._wait_for("march_btn", timeout=15.0)

    def _launch(self, ctx):
        self._click_retry("march_btn", attempts=3)

    def _switch_back(self, ctx):
        pass  # v1: 无需切换回去

    def is_terminal(self) -> bool:
        return self.current == "END"
