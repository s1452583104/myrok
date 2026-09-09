from __future__ import annotations
import time
from .state_machine import StateMachine

class MemberStateMachine(StateMachine):
    def __init__(self, handle_source, recognizers: dict, march_preset: int,
                 march_troop_types: list, fill_target_leaders, switcher=None):
        self._handle = handle_source
        self._rec = recognizers
        self._march_preset = march_preset
        self._march_troop_types = march_troop_types
        self._filter = fill_target_leaders
        self._switcher = switcher
        self._pending_event = None
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "WAIT_LAUNCH_EVENT",
                            lambda ctx: None,
                            guard=lambda ctx: self._pending_event is not None)
        self.add_transition("WAIT_LAUNCH_EVENT", "SWITCH_TO_SELF", self._switch_to_self)
        self.add_transition("SWITCH_TO_SELF", "OPEN_ALLIANCE", self._open_alliance)
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

    def _click(self, rec_id: str) -> bool:
        img = self._handle.capture()
        r = self._rec[rec_id].recognize(img)
        if not r.matched:
            return False
        x, y = r.bbox.center()
        self._handle.click(x, y)
        return True

    def _switch_to_self(self, ctx):
        # In single-character-worker-per-character model, already on self.
        # For multi-char per account, would call switcher.
        pass

    def _open_alliance(self, ctx):
        self._click("alliance_btn")

    def _open_war(self, ctx):
        self._click("war_btn")

    def _sort_nearest(self, ctx):
        self._click("sort_nearest")

    def _filter_rally(self, ctx):
        # fill_target_leaders 现在永远是显式列表；按名字 OCR 匹配是后续里程碑
        # （ACCEPTANCE §3.7），当前简化为加入排序后的第一个集结。
        ctx["rally_found"] = True

    def _click_join(self, ctx):
        self._click("join_btn")

    def _form_troop(self, ctx):
        self._click(f"preset_{self._march_preset}")

    def _launch(self, ctx):
        self._click("march_btn")

    def _switch_back(self, ctx):
        pass  # simplified

    def is_terminal(self) -> bool:
        return self.current == "END"
