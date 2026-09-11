from __future__ import annotations
import time
from .state_machine import StateMachine

_MAX_NO_RESULT = 3
_MAX_LOCKED = 5
_EMPTY_GROUND = (960, 540)   # tap empty ground to dismiss the detail popup


class LeaderStateMachine(StateMachine):
    """集结车头。真实 UI 流程（2026-09 实测，ACCEPTANCE §1.4/§1.5）：
    归一化视图（城市视图先点 map_btn）→ 搜寨 → 设等级（minus 连点到底再
    plus 到目标，搜索面板会记住上次等级，观察值为 8）→ 搜索 → 城寨详情
    弹窗（red_rally 可见）→ 点 red_rally → 集结攻击弹窗（默认预选 5 分钟）
    → 创建部队（预设槽 + 兵种）→ 行军 → 被动等待成员填兵。

    锁定 = 点 red_rally 后 5 秒内 rally_attack_popup 未出现（§3.3）；
    无结果 = toast_no_fortress（或干脆没有任何弹窗，慢加载与之不可区分）。
    march_btn 的 00:00:XX 是行军时长估计而非倒计时，点击即发（无自动发车风险），
    但必须在发布 rally_launched 前确认点击成功——点击失败不得唤醒成员。

    v1 已知限制（接受，与 member_sm 同类）：等级设置盲进——level_minus ×12 /
    level_plus ×N 不回读结果等级，模板误点无法被检测。
    """

    def __init__(self, handle_source, recognizers: dict, target_level: int,
                 march_preset: int, march_troop_types: list, event_bus=None,
                 wait_members_seconds: float = 330.0):
        self._handle = handle_source
        self._rec = recognizers
        self._target_level = target_level
        self._march_preset = march_preset
        self._march_troop_types = march_troop_types
        self._bus = event_bus
        self._wait_members_seconds = wait_members_seconds
        self.last_rally_event = None
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "NORMALIZE", self._normalize_view)
        self.add_transition("NORMALIZE", "SEARCH_FORTRESS", self._search_fortress)
        self.add_transition("SEARCH_FORTRESS", "SELECT_LEVEL", self._select_level)
        self.add_transition("SELECT_LEVEL", "CONFIRM_SEARCH", self._confirm_search)
        self.add_transition("CONFIRM_SEARCH", "CHECK_RESULT", self._check_result)
        self.add_transition("CHECK_RESULT", "CLICK_RED_RALLY", self._click_red_rally,
                            guard=lambda ctx: ctx.get("search_outcome") == "found")
        # 重试边必须先于放弃边注册：StateMachine.step 按注册顺序取第一个
        # from_state 匹配且 guard 通过的转移
        self.add_transition("CHECK_RESULT", "CONFIRM_SEARCH", self._retry_search,
                            guard=lambda ctx: ctx.get("search_outcome") == "no_result"
                            and ctx.get("no_result_count", 0) < _MAX_NO_RESULT)
        self.add_transition("CHECK_RESULT", "END", self._give_up,
                            guard=lambda ctx: ctx.get("search_outcome") == "no_result")
        self.add_transition("CLICK_RED_RALLY", "VERIFY_UNLOCKED", self._verify_unlocked)
        self.add_transition("VERIFY_UNLOCKED", "SELECT_RALLY_TIME", lambda ctx: None,
                            guard=lambda ctx: ctx.get("not_locked"))
        # 恢复边必须先于放弃边注册（同上）
        self.add_transition("VERIFY_UNLOCKED", "NORMALIZE", self._recover_locked,
                            guard=lambda ctx: not ctx.get("not_locked")
                            and ctx.get("locked_count", 0) < _MAX_LOCKED)
        self.add_transition("VERIFY_UNLOCKED", "END", self._give_up,
                            guard=lambda ctx: not ctx.get("not_locked"))
        self.add_transition("SELECT_RALLY_TIME", "FORM_TROOP", self._form_troop)
        self.add_transition("FORM_TROOP", "LAUNCH", self._launch)
        self.add_transition("LAUNCH", "WAIT_MEMBERS", self._wait_members)
        self.add_transition("WAIT_MEMBERS", "END", lambda ctx: None,
                            guard=lambda ctx: ctx.get("departed"))

    # ---- actions ----

    def _normalize_view(self, ctx):
        # 城市视图：左下角是 map_btn，看不到搜索放大镜（§1.5.2）；地图视图下
        # map_btn 不匹配（0.528），模板不会误触发——先查 search_icon 再按需点
        if self._find("search_icon"):
            return
        self._click("map_btn")
        self._wait_for("search_icon", timeout=6.0)

    def _search_fortress(self, ctx):
        if not self._click_retry("search_icon", attempts=3):
            raise RuntimeError("search_icon 不可见且 map_btn 归一化失败")

    def _select_level(self, ctx):
        # 面板记住上次的 Tab（实测落在「野蛮人」上，2026-09-11 实机验收发现）。
        # tab_fortress 模板采的是未选中（灰色）态：匹配到 ⇔ 当前不在城寨页，
        # 点它切换；已在城寨页（棕色选中态）不匹配，_click 自动跳过。
        self._click("tab_fortress")
        # 搜索面板记住上次的等级（观察到 8）：先 minus 连点 12 次压到 1 级
        # 下限，再 plus 到目标等级
        for _ in range(12):
            self._click("level_minus")
        for _ in range(max(0, self._target_level - 1)):
            self._click("level_plus")

    def _confirm_search(self, ctx):
        self._click_retry("search_btn")

    def _check_result(self, ctx):
        ctx.setdefault("no_result_count", 0)
        ctx.setdefault("locked_count", 0)
        if self._wait_for("red_rally", timeout=8.0):
            ctx["search_outcome"] = "found"
            return
        # 没有详情弹窗：toast 可见即为确证的无结果；不可见也可能是慢加载，
        # 两者行为一致（都计数），但记录实际所见供日志/调试
        ctx["last_search_toast"] = self._find("toast_no_fortress") is not None
        ctx["search_outcome"] = "no_result"
        ctx["no_result_count"] = ctx["no_result_count"] + 1

    def _retry_search(self, ctx):
        # toast 弹出时搜索面板仍在背后——直接再搜一次
        self._click_retry("search_btn")

    def _click_red_rally(self, ctx):
        self._click_retry("red_rally")

    def _verify_unlocked(self, ctx):
        # 锁定 = 点 red_rally 后 5 秒内集结攻击弹窗未出现（§3.3）；
        # ⭐ 书签与锁定无关
        ctx["not_locked"] = self._wait_for("rally_attack_popup", timeout=5.0)
        if not ctx["not_locked"]:
            ctx["locked_count"] = ctx.get("locked_count", 0) + 1

    def _recover_locked(self, ctx):
        # 点空地关掉详情弹窗，重新归一化视图后再搜
        self._handle.click(*_EMPTY_GROUND)

    def _give_up(self, ctx):
        # 重试耗尽：结束本轮，置失败标记。fail_reason 由 WorkerRunner 在
        # 终态发布的 status_update payload 中带出（供 GUI/日志观测）；
        # 冷却后 runner 重建 SM 重试新一轮。either_sm 以 last_rally_event
        # is None 判定开集结失败，呈现为终态走同一条重建重试路径。
        # fail_reason 按**真正耗尽**的那个上限归因：混有锁定的轮次仍可能是
        # 无结果耗尽（如 1 次锁定 + 3 次无结果）
        ctx["failed"] = True
        ctx["fail_reason"] = ("locked_fortress" if ctx.get("locked_count", 0) >= _MAX_LOCKED
                              else "no_fortress_found")
        self.last_rally_event = None

    def _form_troop(self, ctx):
        if not self._wait_for("march_btn", timeout=15.0):
            raise RuntimeError("创建部队弹窗未出现（march_btn 不可见）")
        self._click(f"preset_{self._march_preset}")
        for t in self._march_troop_types:
            self._click(f"troop_{t}")

    def _launch(self, ctx):
        # 必须确认 march_btn 点击成功后再发布 rally_launched——点击失败
        # 不得触发成员填兵
        if not self._click_retry("march_btn", attempts=3):
            raise RuntimeError("march_btn 点击失败，集结未发起")
        self.last_rally_event = {
            "rally_id": f"rally_{int(time.time())}",
            "fortress_level": self._target_level,
            "march_preset": self._march_preset,
        }
        if self._bus:
            self._bus.publish("rally_launched", self.last_rally_event)

    def _wait_members(self, ctx):
        # 被动等待：成员填兵或 5 分钟倒计时结束游戏自动发车（默认 330s，
        # 按 ≤10s 分片睡）。either 角色传 0.0：开完自己的集结立即转去填
        # 他人集结，不停留。
        deadline = time.time() + self._wait_members_seconds
        while time.time() < deadline:
            time.sleep(min(10.0, deadline - time.time()))
        ctx["departed"] = True

    def is_terminal(self) -> bool:
        return self.current == "END"
