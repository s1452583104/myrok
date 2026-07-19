from __future__ import annotations
from .state_machine import StateMachine

class SwitcherStateMachine(StateMachine):
    """4-step character switcher: avatar -> settings -> char_mgmt -> pick."""
    def __init__(self, handle_source, target_character: str, recognizers: dict, ocr):
        self._handle = handle_source
        self._target = target_character
        self._recognizers = recognizers
        self._ocr = ocr
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "OPEN_PROFILE", self._open_profile)
        self.add_transition("OPEN_PROFILE", "OPEN_SETTINGS", self._open_settings)
        self.add_transition("OPEN_SETTINGS", "OPEN_CHAR_MGMT", self._open_char_mgmt)
        self.add_transition("OPEN_CHAR_MGMT", "PICK_CHAR", self._pick_char)
        self.add_transition("PICK_CHAR", "VERIFY", self._verify)
        self.add_transition("VERIFY", "DONE", lambda ctx: None,
                            guard=lambda ctx: ctx.get("verified", False))
        self.add_transition("VERIFY", "PICK_CHAR", self._pick_char,
                            guard=lambda ctx: not ctx.get("verified", False) and ctx.get("retries", 0) < 2)

    def _open_profile(self, ctx):
        # Click avatar (top-left). Real coords from screen config.
        self._handle.click(50, 50)

    def _open_settings(self, ctx):
        self._handle.click(800, 600)  # 设置 button (rough)

    def _open_char_mgmt(self, ctx):
        self._handle.click(400, 400)  # 角色管理 button

    def _pick_char(self, ctx):
        # Look up target character's avatar position from ocr; for now click 250,250
        self._handle.click(250, 250)
        ctx["retries"] = ctx.get("retries", 0) + 1

    def _verify(self, ctx):
        # OCR the top-left avatar name. Mock: assume success.
        ctx["verified"] = True

    def is_done(self) -> bool:
        return self.current == "DONE"

    def run_until_done(self) -> None:
        ctx = {}
        for _ in range(20):
            self.step(ctx)
            if self.is_done():
                return
