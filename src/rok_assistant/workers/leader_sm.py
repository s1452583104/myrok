from __future__ import annotations
import time
from .state_machine import StateMachine
from ..core.recognizer import BBox

class LeaderStateMachine(StateMachine):
    def __init__(self, handle_source, recognizers: dict, target_level: int,
                 march_preset: int, march_troop_types: list, event_bus=None):
        self._handle = handle_source
        self._rec = recognizers
        self._target_level = target_level
        self._march_preset = march_preset
        self._march_troop_types = march_troop_types
        self._bus = event_bus
        self.last_rally_event = None
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "SEARCH_FORTRESS", self._search_fortress)
        self.add_transition("SEARCH_FORTRESS", "SELECT_LEVEL", self._select_level)
        self.add_transition("SELECT_LEVEL", "CONFIRM_SEARCH", self._confirm_search)
        self.add_transition("CONFIRM_SEARCH", "CHECK_RESULT", self._check_result)
        self.add_transition("CHECK_RESULT", "SELECT_RALLY_TIME", self._select_rally_time,
                            guard=lambda ctx: ctx.get("not_locked"))
        self.add_transition("CHECK_RESULT", "CONFIRM_SEARCH", self._next_fortress,
                            guard=lambda ctx: not ctx.get("not_locked"))
        self.add_transition("SELECT_RALLY_TIME", "FORM_TROOP", self._form_troop)
        self.add_transition("FORM_TROOP", "LAUNCH", self._launch)
        self.add_transition("LAUNCH", "WAIT_MEMBERS", self._wait_members)
        self.add_transition("WAIT_MEMBERS", "END", lambda ctx: None,
                            guard=lambda ctx: ctx.get("departed"))

    def _find(self, rec_id: str):
        img = self._handle.capture()
        r = self._rec[rec_id].recognize(img)
        return r if r.matched else None

    def _click(self, rec_id: str):
        r = self._find(rec_id)
        if r is None:
            return False
        x, y = r.bbox.center()
        self._handle.click(x, y)
        return True

    def _search_fortress(self, ctx):
        self._click("search_icon")

    def _select_level(self, ctx):
        # Click on level tab "野蛮人城寨"
        # Then click +/- to reach target_level
        for _ in range(self._target_level - 1):
            self._click("level_plus")

    def _confirm_search(self, ctx):
        self._click("search_btn")

    def _check_result(self, ctx):
        # Wait for rally_attack_popup
        r = self._find("rally_attack_popup")
        ctx["not_locked"] = r is not None

    def _next_fortress(self, ctx):
        # Click "next fortress" arrow
        self._click("next_fortress_arrow")

    def _select_rally_time(self, ctx):
        # Default 5 minutes - already selected; just confirm
        pass

    def _form_troop(self, ctx):
        # Click preset slot matching march_preset
        self._click(f"preset_{self._march_preset}")
        # Set troop types
        for t in self._march_troop_types:
            self._click(f"troop_{t}")

    def _launch(self, ctx):
        self._click("march_btn")
        # Fire event
        self.last_rally_event = {
            "rally_id": f"rally_{int(time.time())}",
            "fortress_level": self._target_level,
            "march_preset": self._march_preset,
        }
        if self._bus:
            self._bus.publish("rally_launched", self.last_rally_event)

    def _wait_members(self, ctx):
        # Passive wait. Game auto-departs after timer.
        ctx["departed"] = True  # simplified; real impl subscribes to game state

    def is_terminal(self) -> bool:
        return self.current == "END"
