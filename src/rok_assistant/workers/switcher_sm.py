from __future__ import annotations
import time
from .state_machine import StateMachine

AVATAR_CLICK = (75, 60)   # 主界面左上角头像，位置固定（§1.5.3：左上角没有角色名）


class SwitcherStateMachine(StateMachine):
    """切角色 5 步 + 确认 + 重登（ACCEPTANCE §1.5.1 实测）：
    头像 → 设置 → 角色管理 → 点目标角色头像 → 「角色登入」确认框点「是」
    → 完整重登（点击进入游戏 → 加载约 20-25s）→ 头像校验。
    v1 每实例只跑第 1 个角色，本类暂无调用方（为 v2 多角色切换预留）。
    """

    def __init__(self, handle_source, target_character: str, recognizers: dict,
                 avatar_key: str = "", verify_key: str = "",
                 load_wait_seconds: float = 25.0):
        self._handle = handle_source
        self._target = target_character
        self._rec = recognizers   # 基类 _find/_click 系列助手读 self._rec
        self._avatar_key = avatar_key
        self._verify_key = verify_key
        self._load_wait = load_wait_seconds
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "OPEN_PROFILE", self._open_profile)
        self.add_transition("OPEN_PROFILE", "OPEN_SETTINGS", self._open_settings)
        self.add_transition("OPEN_SETTINGS", "OPEN_CHAR_MGMT", self._open_char_mgmt)
        self.add_transition("OPEN_CHAR_MGMT", "PICK_CHAR", self._pick_char)
        self.add_transition("PICK_CHAR", "CONFIRM_SWITCH", self._confirm_switch)
        self.add_transition("CONFIRM_SWITCH", "RELOGIN", self._relogin)
        self.add_transition("RELOGIN", "WAIT_LOAD", self._wait_load)
        self.add_transition("WAIT_LOAD", "VERIFY", self._verify)
        self.add_transition("VERIFY", "DONE", lambda ctx: None,
                            guard=lambda c: c.get("verified", False))
        self.add_transition("VERIFY", "OPEN_PROFILE", self._retry,
                            guard=lambda c: not c.get("verified", False)
                            and c.get("retries", 0) < 2)
        self.add_transition("VERIFY", "DONE", self._flag_failed,
                            guard=lambda c: not c.get("verified", False))

    # 基类 step() 用 self._ctx；这里以 ctx 属性暴露同一 dict，供调用方检查结果
    @property
    def ctx(self) -> dict:
        return self._ctx

    @ctx.setter
    def ctx(self, value: dict) -> None:
        pass  # 兼容可能的外部赋值；实际状态始终走基类 _ctx

    def _open_profile(self, ctx):
        self._handle.click(*AVATAR_CLICK)

    def _open_settings(self, ctx):
        if not self._click_retry("settings_btn", attempts=3):
            raise RuntimeError("settings_btn 未找到，切角色中止")

    def _open_char_mgmt(self, ctx):
        if not self._click_retry("char_mgmt_btn", attempts=3):
            raise RuntimeError("char_mgmt_btn 未找到，切角色中止")

    def _pick_char(self, ctx):
        if self._avatar_key and self._avatar_key in self._rec:
            self._click_retry(self._avatar_key, attempts=3)
        else:
            ctx["switch_failed"] = True   # 没有目标角色头像模板，无法点选

    def _confirm_switch(self, ctx):
        # 「角色登入」确认框点「是」（§1.5.1 第 5 步）
        self._wait_click("switch_confirm_yes", timeout=10.0)

    def _relogin(self, ctx):
        # 完整重登：登录页「点击进入游戏」；等待窗口要够长（游戏可能重启）
        self._wait_click("click_to_enter", timeout=60.0)

    def _wait_load(self, ctx):
        time.sleep(self._load_wait)   # 重登加载 20-25s（测试传 0）

    def _verify(self, ctx):
        ctx["retries"] = ctx.get("retries", 0) + 1
        if not self._verify_key or self._verify_key not in self._rec:
            ctx["verified"] = True
            ctx["verify_skipped"] = True   # §1.5.3：无头像模板，跳过校验
            return
        ctx["verified"] = self._find_retry(self._verify_key, attempts=3, interval=2.0) is not None

    def _retry(self, ctx):
        pass  # 回 OPEN_PROFILE 整个流程重走

    def _flag_failed(self, ctx):
        ctx["switch_failed"] = True

    def is_done(self) -> bool:
        return self.current == "DONE"

    def run_until_done(self) -> None:
        # 步数上限：模板缺失等坏路径会超时但不会死循环
        for _ in range(40):
            self.step()
            if self.is_done():
                return
