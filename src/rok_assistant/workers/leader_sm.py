from __future__ import annotations
import threading
import time
import weakref
from .state_machine import StateMachine
from ..core.recognizers.pixel_stat import slot_center
from ..core.recognizers.view_probe import View, ViewProbe
from ..infra.logger import get_logger

logger = get_logger(__name__)

_MAX_NO_RESULT = 3
_MAX_LOCKED = 5
_EMPTY_GROUND = (960, 540)   # tap empty ground to dismiss the detail popup
# 派遣队列侧栏展开态会盖掉整个底部栏（含 search_icon/map_btn，2026-09-11
# 实机验收 mumu1 卡死态）：点侧栏外空地收起侧栏与「创建部队」引导气泡。
_QUEUE_SIDEBAR_DISMISS = (1550, 320)
# 等级按钮连点太快游戏会丢点击（2026-09-11 实机验收：目标7实际4、目标8实际6；
# 0.4s 间隔实测 19 连点零丢失）。测试里置 0 免真实睡眠。
_LEVEL_CLICK_PACE = 0.35
# 搜索面板会记住上次等级：进程内按句柄缓存上次设置的等级，每轮只点差量
# （2026-09-11 验收反馈：每轮 12 降 + N 升太慢）。弱引用键随句柄回收自动
# 失效，避免 id 复用导致脏缓存；锁保护两个 worker 线程的并发读写。
# 已知限制：若玩家在 GUI 运行期间手动改过面板等级，缓存会偏一轮。
_LEVEL_CACHE: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_LEVEL_CACHE_LOCK = threading.Lock()

# 预设槽选中态确认（2026-09-27，见 _select_preset）。超时给 2.0s：高亮是本地
# 重绘（不像 queue_badge 要等服务端往返），实测 toast 与高亮同帧出现。
_PRESET_ATTEMPTS = 3
_PRESET_CONFIRM_TIMEOUT = 2.0
_PRESET_CONFIRM_INTERVAL = 0.5


class LeaderStateMachine(StateMachine):
    """集结车头。真实 UI 流程（2026-09 实测，ACCEPTANCE §1.4/§1.5）：
    归一化视图（城市视图先点 map_btn）→ 搜寨 → 设等级（minus 连点到底再
    plus 到目标，搜索面板会记住上次等级，观察值为 8）→ 搜索 → 城寨详情
    弹窗（red_rally 可见）→ 点 red_rally → 集结进攻弹窗（默认预选 5 分钟）
    → 点蓝色「集结」（blue_rally）→ 创建部队（预设槽 + 兵种）→ 行军 →
    被动等待成员填兵。

    锁定 = 点 red_rally 后 5 秒内 rally_attack_popup 未出现（§3.3）；
    无结果 = toast_no_fortress（或干脆没有任何弹窗，慢加载与之不可区分）。
    march_btn 的 00:00:XX 是行军时长估计而非倒计时，点击即发（无自动发车风险），
    但必须在发布 rally_launched 前确认点击成功——点击失败不得唤醒成员。

    v1 已知限制（接受，与 member_sm 同类）：等级设置盲进——level_minus ×12 /
    level_plus ×N 不回读结果等级，模板误点无法被检测。
    """

    def __init__(self, handle_source, recognizers: dict, target_level: int,
                 march_preset: int, march_troop_types: list, event_bus=None,
                 wait_members_seconds: float = 330.0,
                 publisher_id: str | None = None,
                 ledger=None):
        self._handle = handle_source
        self._rec = recognizers
        self._target_level = target_level
        self._march_preset = march_preset
        self._march_troop_types = march_troop_types
        self._bus = event_bus
        self._wait_members_seconds = wait_members_seconds
        # 发布 rally_launched 时带上账号标识：either_sm 的进程级集结事件
        # 登记簿靠它区分「自己/对方」的集结（跨 SM 重建存活）
        self._publisher_id = publisher_id
        self.last_rally_event = None
        # 进程级动作账本（runtime 注入）：发车确认后记「部队在外」，
        # 供集结门槛的 L0 判据用。未注入 = 不记账 = 旧行为
        self._ledger = ledger
        # 视图判定探针（2026-09-30）：只做「额外的成功信号」与「失败归因」，
        # 不取代 _normalize_view 的残留面板清理清单
        self._view_probe = ViewProbe(recognizers)
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
        self.add_transition("VERIFY_UNLOCKED", "SELECT_RALLY_TIME", self._open_troop_form,
                            guard=lambda ctx: ctx.get("not_locked"))
        # 恢复边必须先于放弃边注册（同上）
        self.add_transition("VERIFY_UNLOCKED", "NORMALIZE", self._recover_locked,
                            guard=lambda ctx: not ctx.get("not_locked")
                            and ctx.get("locked_count", 0) < _MAX_LOCKED)
        self.add_transition("VERIFY_UNLOCKED", "END", self._give_up,
                            guard=lambda ctx: not ctx.get("not_locked"))
        self.add_transition("SELECT_RALLY_TIME", "FORM_TROOP", self._form_troop)
        self.add_transition("FORM_TROOP", "LAUNCH", self._launch)
        # 集结被游戏静默拒绝的放弃边必须先于等待成员边注册：StateMachine
        # 按注册顺序取第一条匹配转移（2026-09-18 run11 run 实锤）
        self.add_transition("LAUNCH", "END", lambda ctx: None,
                            guard=lambda ctx: ctx.get("fail_reason") == "rally_rejected")
        self.add_transition("LAUNCH", "WAIT_MEMBERS", self._wait_members)
        self.add_transition("WAIT_MEMBERS", "END", lambda ctx: None,
                            guard=lambda ctx: ctx.get("departed"))

    # ---- actions ----

    def _normalize_view(self, ctx):
        # 城市视图：左下角是 map_btn，看不到搜索放大镜（§1.5.2）；地图视图下
        # map_btn 不匹配（0.528），模板不会误触发——先查 search_icon 再按需点。
        # 战争列表开着会盖住左下角按钮（成员阶段回流/上一轮残留）：
        # 点面板右上角 X（固定几何 1671,64）关掉再归一化；派遣队列侧栏
        # 展开态同样盖住底部栏，先点空地收起。
        if self._find("search_icon"):
            return
        if self._find("war_title"):
            self._handle.click(1671, 64)
            if self._wait_for("search_icon", timeout=6.0):
                return
        if self._find("queue_panel"):
            self._handle.click(*_QUEUE_SIDEBAR_DISMISS)
        if self._find("rally_attack_popup"):
            # 集结进攻弹窗残留（上轮进程被杀在选时间步，2026-09-12 实机
            # mumu1）：模态弹窗压住 HUD，点空地关闭后再继续归一化
            self._handle.click(*_EMPTY_GROUND)
        if self._find("ap_refill"):
            # 行动力不足弹窗（行军点击时行动力 < 消耗弹出，2026-09-12 实机
            # mumu0 77/140）：补体力（每日免费 500 + 初级恢复 100）而非关
            # 弹窗 —— 2026-09-18 run9 实锤加入行军同样耗行动力，140 自然
            # 上限跑不满 10 轮目标，历次「连续 3 轮失败」停机根因即此
            if not self._refill_ap():
                self._handle.click(1638, 120)
        if self._find("form_title"):
            # 创建部队表单残留（上轮进程被杀在 FORM_TROOP，2026-09-12 实机
            # mumu0）：全屏模态盖住一切，点右上角 X 关闭再归一化
            self._handle.click(1671, 64)
        if self._find("replace_popup"):
            # 部队替换确认弹窗残留（成员链路点「+」时部队已在集结中，
            # 2026-09-13 实机 mumu0）：不替换，点弹窗右上角 X 关闭
            self._handle.click(1500, 170)
        if self._find("menu_expanded"):
            # 底部快捷菜单展开态（战役/道具/联盟/统帅/邮件，2026-09-15 实机
            # mumu0 00:20 六连异常收工）：展开时联盟旗帜按钮被整体隐藏。
            # 再点一次右下角 ☰ 即收起（2026-09-16 实机验证）
            self._handle.click(1845, 1010)
        if self._find("warning_panel"):
            # 「预警」面板（增援/来攻警报触发时游戏自动弹出，2026-09-15
            # 实机 mumu1 00:09 六连异常收工）：全屏模态盖住一切，点右上角
            # X（与战争列表同位）关闭再继续归一化
            self._handle.click(1671, 64)
        if self._find("search_back"):
            # 搜索面板残留（上轮进程被杀在搜索中、或成员阶段回流遗留）：
            # 搜索模式专属底栏盖掉 map_btn，先退搜索再回地图
            self._click("search_back")
        self._click("map_btn")
        if self._wait_for("search_icon", timeout=6.0):
            return
        # 放大镜没等到：不再把失败漂到 _search_fortress（那里只能报
        # 「search_icon 不可见」，说不出到底卡在哪）
        view = self._view_probe.probe(self._handle.capture()).view
        if view is View.MAP:
            # 探针说在地图但放大镜模板失配：与 member 侧同款判据
            # （「放大镜与旗帜同为地图视图专属 UI，任一可见即成功」）
            logger.warning("[归一化] 放大镜模板失配但探针确认在地图视图，"
                           "按归一化成功处理")
            return
        raise RuntimeError(f"归一化失败：卡在[{view.value}]视图")

    def _search_fortress(self, ctx):
        if not self._click_retry("search_icon", attempts=3):
            raise RuntimeError("search_icon 点击失败（归一化已成功，放大镜应可见）")

    def _select_level(self, ctx):
        # 面板记住上次的 Tab（实测落在「野蛮人」上，2026-09-11 实机验收发现）。
        # tab_fortress 模板采的是未选中（灰色）态：匹配到 ⇔ 当前不在城寨页，
        # 点它切换；已在城寨页（棕色选中态）不匹配，_click 自动跳过。
        self._click("tab_fortress")
        # 等级差量调整：缓存缺失（GUI 启动后首轮）才连点降到底，之后每轮
        # 只点与目标的差量；等级已是目标则零点击（2026-09-11 验收反馈）。
        with _LEVEL_CACHE_LOCK:
            cached = _LEVEL_CACHE.get(self._handle)
        if cached == self._target_level:
            logger.info("[车头] 面板等级已是 %s 级，跳过调整", self._target_level)
            return
        if cached is None:
            logger.info("[车头] 面板等级未知，先降到底再升到 %s 级", self._target_level)
            for _ in range(12):
                self._click("level_minus")
                time.sleep(_LEVEL_CLICK_PACE)
            start = 1
        else:
            start = cached
        delta = self._target_level - start
        btn = "level_plus" if delta > 0 else "level_minus"
        for _ in range(abs(delta)):
            self._click(btn)
            time.sleep(_LEVEL_CLICK_PACE)
        with _LEVEL_CACHE_LOCK:
            _LEVEL_CACHE[self._handle] = self._target_level
        logger.info("[车头] 面板等级 %s → %s 级（%s 次点击）",
                    start, self._target_level, (12 if cached is None else 0) + abs(delta))

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
        # 无结果先怀疑等级缓存失步：等级设置盲进，plus 连点被游戏丢失后
        # 缓存停在目标值、面板实际低 1 级，之后每轮「跳过调整」永远搜错
        # 等级（2026-09-12 实机 mumu0：缓存 7 实际 6，连续 9 搜全空）。
        # 清缓存让重试/下一轮强制全量重同步。
        with _LEVEL_CACHE_LOCK:
            _LEVEL_CACHE.pop(self._handle, None)
        logger.warning("[车头] 搜索无结果（第 %s/%s 次，toast 可见=%s）",
                       ctx["no_result_count"], _MAX_NO_RESULT,
                       ctx["last_search_toast"])

    def _retry_search(self, ctx):
        # toast 弹出时搜索面板仍在背后——重同步等级（缓存已被
        # _check_result 清掉，_select_level 走全量降底+升级）再搜
        self._select_level(ctx)
        self._click_retry("search_btn")

    def _click_red_rally(self, ctx):
        self._click_retry("red_rally")

    def _verify_unlocked(self, ctx):
        # 锁定 = 点 red_rally 后集结攻击弹窗未出现（§3.3）。超时 5s -> 10s：
        # 2026-09-12 实机 mumu0/mumu1 同秒被判锁定（第 1、2/5 次）—— 弹窗
        # 服务器慢加载超 5s 被误判，每次误判白烧一轮全量重搜（~40s）还
        # 烧锁定计数。误判代价远高于真锁定多等 5s。
        ctx["not_locked"] = self._wait_for("rally_attack_popup", timeout=10.0)
        if not ctx["not_locked"]:
            ctx["locked_count"] = ctx.get("locked_count", 0) + 1

    def _recover_locked(self, ctx):
        # 点空地关掉详情弹窗，重新归一化视图后再搜
        logger.warning("[车头] 城寨被锁定（第 %s/%s 次），关闭详情重搜",
                       ctx.get("locked_count", 0), _MAX_LOCKED)
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
        logger.warning("[车头] 放弃本轮集结：%s（无结果 %s 次 / 锁定 %s 次），"
                       "冷却后自动重试", ctx["fail_reason"],
                       ctx.get("no_result_count", 0), ctx.get("locked_count", 0))
        self.last_rally_event = None

    def _open_troop_form(self, ctx):
        # 集结进攻弹窗（默认预选 5 分钟）→ 点蓝色「集结」按钮才出创建部队
        # 弹窗。2026-09-11 实机验收发现：旧代码此步是空操作，march_btn 永远
        # 等不到（15s 超时 RuntimeError → 错误循环）。5 分钟复选框保持默认，
        # 不点（再点一次可能取消勾选）。
        if not self._click_retry("blue_rally"):
            raise RuntimeError("blue_rally 不可见（集结进攻弹窗异常）")

    def _form_troop(self, ctx):
        if not self._wait_for("march_btn", timeout=15.0):
            view = self._view_probe.probe(self._handle.capture()).view
            raise RuntimeError(f"创建部队弹窗未出现，卡在[{view.value}]视图")
        self._select_preset()
        for t in self._march_troop_types:
            self._click(f"troop_{t}")

    def _select_preset(self):
        """点预设槽并**确认**高亮移到了槽 N（2026-09-27）。

        旧实现是盲点：`self._click(f"preset_{N}")` 的返回值直接丢掉，两种失败
        都静默——模板失配=空操作（用游戏默认兵种），模板串位=**派错兵**
        （`_click_result` 点的是匹配到的位置，而 preset_* 六个槽只差中间数字）。

        1) 先走模板（现状路径）；
        2) 失配时按**实测钉死**的槽心几何直接点——44 帧逐像素实测
           `cx=1655`、`cy=474+82*(N-1)` 零漂移（`march_btn` cy=925、
           `form_title` cy=69 逐字节不变）。模板腿失配不等于这轮必须空过。
           串位也走这条路：确认失败 → 几何点正确槽 → 确认通过；
        3) 3 轮都确认不了就**抛异常**。两个号 `march_preset` 都是 1，点错是
           **系统性**错兵，宁可 loud 失败让 runner 重试，也不发一轮兵种不可信
           的集结。

        未配置 `selected_preset_N` 识别器时退回旧的盲点行为——manifest 没写
        `pixel_stats:` 的部署、以及 test_leader_sm 的 26 击断言都靠这道守卫。
        """
        n = self._march_preset
        rec_id = f"selected_preset_{n}"
        if self._rec.get(rec_id) is None:
            self._click(f"preset_{n}")
            return
        for attempt in range(_PRESET_ATTEMPTS):
            self._click(f"preset_{n}")
            if self._wait_for(rec_id, timeout=_PRESET_CONFIRM_TIMEOUT,
                              interval=_PRESET_CONFIRM_INTERVAL):
                # 确认路径要进日志：这条改动的前提就是旧实现「两种失败都静默」，
                # 若成功也静默，实机就只能靠「没抛异常」反推——那是把静默从
                # 失败挪到了成功上。
                logger.info("[车头] 预设槽 %s 已确认（模板点击，第 %s 轮）",
                            n, attempt + 1)
                return
            logger.warning("[车头] 预设槽 %s 模板点击后未确认，按实测几何补点",
                           n)
            self._click_xy(*slot_center(n))
            if self._wait_for(rec_id, timeout=_PRESET_CONFIRM_TIMEOUT,
                              interval=_PRESET_CONFIRM_INTERVAL):
                logger.info("[车头] 预设槽 %s 已确认（几何补点，第 %s 轮）",
                            n, attempt + 1)
                return
        raise RuntimeError(f"预设槽 {n} 高亮未确认（{_PRESET_ATTEMPTS} 轮），"
                           f"拒绝派错兵，集结未发起")

    def _launch(self, ctx):
        # 必须确认 march_btn 点击成功后再发布 rally_launched——点击失败
        # 不得触发成员填兵
        if self._find("ap_refill") is not None:
            # 上次行军点击因行动力不足弹的补充弹窗残留（2026-09-18 run10
            # 实机：残留弹窗盖住 march_btn，先找行军只会一路异常，永远
            # 走不到下面的补体力分支）：补体力并关弹窗再点行军
            if not self._refill_ap():
                raise RuntimeError("行动力补充弹窗关不掉，集结未发起")
        if not self._click_retry("march_btn", attempts=3):
            raise RuntimeError("march_btn 点击失败，集结未发起")
        if self._wait_for("ap_refill", timeout=3.0):
            # 行动力不足弹窗（行动力 < 消耗，2026-09-18 实机 run9）：行军
            # 根本没发出去，补体力后必须补点行军，否则集结未发起却发布了
            # 事件，成员白等一轮
            if not self._refill_ap():
                raise RuntimeError("行动力补充弹窗关不掉，集结未发起")
            if not self._click_retry("march_btn", attempts=3):
                raise RuntimeError("行动力补充后 march_btn 点击失败，集结未发起")
        # 发射验证（2026-09-18 run11 实锤）：同联盟两号步调锁步（行军点击仅
        # 差 4s）向同一座最近城寨发起集结，后发起的被游戏**静默拒绝**——
        # 表单关闭、无 toast、无队列徽标、任何战争列表都无集结行。旧实现
        # 照旧发布 rally_launched，对方账号（车头）的成员阶段轮空 6 分钟并
        # 连续计败。行军点击后必须等派遣队列徽标出现才承认发射成功；等
        # 不到即被拒，走 LAUNCH→END 放弃边，绝不虚假唤醒成员
        if self._rec.get("queue_badge") is not None \
                and not self._wait_for("queue_badge", timeout=10.0):
            logger.warning("[车头] 行军点击后队列徽标未出现：集结被游戏静默拒绝"
                           "（同目标已有集结），本轮放弃")
            ctx["failed"] = True
            ctx["fail_reason"] = "rally_rejected"
            self.last_rally_event = None
            return
        self.last_rally_event = {
            "rally_id": f"rally_{int(time.time())}",
            "fortress_level": self._target_level,
            "march_preset": self._march_preset,
        }
        # 账本写入点：到这里才确认发车成功（上面刚验过队列徽标出现）。
        # 被静默拒绝的那条分支已提前 return，走不到这里。未配置徽标识别器
        # 时上面根本没验，「已确认」无从谈起——那种部署下不写：账本只记
        # 已确认的事实，绝不能写「大概发出去了」。
        if self._rec.get("queue_badge") is not None \
                and self._ledger is not None and self._publisher_id:
            self._ledger.mark_troops_out(self._publisher_id)
            self._ledger.mark_rally_launched(self._publisher_id)
        logger.info("[车头] 集结已发起：%s 级城寨（预设槽 %s）",
                    self._target_level, self._march_preset)
        if self._bus:
            payload = dict(self.last_rally_event)
            if self._publisher_id:
                payload["char_id"] = self._publisher_id
            self._bus.publish("rally_launched", payload)

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
