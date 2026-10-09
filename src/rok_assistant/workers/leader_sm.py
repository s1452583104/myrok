from __future__ import annotations
import threading
import time
import weakref
from .state_machine import StateMachine
from .queue_gate import GateDecision
from ..core.recognizers.pixel_stat import (
    PRESET_COL_HALF_X, PRESET_CX, PRESET_PITCH, PRESET_TOP, slot_center)
from ..core.recognizers.view_probe import View, ViewProbe
from ..infra.logger import get_logger

logger = get_logger(__name__)

# 每个等级允许的连续无结果次数（2026-10-04 用户要求：3 → 5）。满额后
# 换 target_levels 里的下一个等级重搜，而不是直接放弃本轮。
_MAX_NO_RESULT = 5
_MAX_LOCKED = 5
_EMPTY_GROUND = (960, 540)   # tap empty ground to dismiss the detail popup
# 派遣队列侧栏展开态会盖掉整个底部栏（含 search_icon/map_btn，2026-09-11
# 实机验收 mumu1 卡死态）：点侧栏外空地收起侧栏与「创建部队」引导气泡。
_QUEUE_SIDEBAR_DISMISS = (1550, 320)
# 等级按钮连点太快游戏会丢点击（2026-09-11 实机验收：目标7实际4、目标8实际6；
# 实测 **0.4s** 间隔连点 19 次零丢失）。原 _LEVEL_CLICK_PACE 取 0.35s，是**低于
# 实测安全值**的取值——正因如此真机必须确认不丢点击。节奏值现由
# anti_detection.rapid_click_min 持有（spec §5），这里不再有第二处硬编码 sleep。
_LEVEL_BLIND_RESET = 12          # 读不出等级时的降底点击数（原 12 次 minus）
_LEVEL_READ_ATTEMPTS = 3         # 读等级的重读次数
_LEVEL_VERIFY_ROUNDS = 2         # 回读校验 + 修正的轮数上限
# 搜索面板会记住上次等级。**2026-10-07 起本缓存只服务盲降回退路径**
# （_blind_set_level）——主路径改为回读面板实际等级，不再需要它。
# 保留而不是删除的原因：盲降就是改动前的代码，缓存命中时它只点差量；
# 删掉会让「OCR 读不出」的每一轮都退回 12 连点降底，那是回归（spec §4.4）。
# 弱引用键随句柄回收自动失效；锁保护两个 worker 线程的并发读写。
# 已知限制：若玩家在 GUI 运行期间手动改过面板等级，缓存会偏一轮。
_LEVEL_CACHE: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_LEVEL_CACHE_LOCK = threading.Lock()

# 预设槽选中态确认（2026-09-27，见 _select_preset）。超时给 2.0s：高亮是本地
# 重绘（不像 queue_badge 要等服务端往返），实测 toast 与高亮同帧出现。
_PRESET_ATTEMPTS = 3
_PRESET_CONFIRM_TIMEOUT = 2.0
_PRESET_CONFIRM_INTERVAL = 0.5

# 集结前置门槛的等待日志节流（秒）。门槛 WAIT 是常态（等部队回城，可能
# 好几分钟），每拍一条会把日志刷满。
_GATE_LOG_INTERVAL = 30.0

# 「补体力 → 点行军」的有界重试上限（2026-10-04 实机，2026-10-09 上调）。
# 补完一次体力后点行军仍可能再弹「行动力不足」（AP 仍不够：体力临界、
# 每日/道具额度已领过），此时必须再补再点，而不是直接抛错——实机 3 次
# `行动力补充后 march_btn 点击失败` 就是原实现补一次就放弃，全靠 runner
# 退避重试才恢复。真耗尽（补不动）时按此上限放弃本轮，交给 runner 的
# 连续失败计数停机。
# 2026-10-09 从 3 上调到 8：用户要求「没有体力就补充体力，吃到没道具为止」。
# 单次 _refill_ap 现在会多吃几口（state_machine._AP_EAT_MAX），外循环也要
# 给够次数，否则道具还没吃完就先放弃了。
_AP_REFILL_MAX = 8


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

    等级设置（2026-10-07 改）：优先**回读**面板上的「等级：N」文本
    （manifest 的 text_fields.fortress_level），据此点差量并回读校验，
    点击次数随当前等级自然变化。读不出时退回盲降（12 次 level_minus 降底
    再升，见 _blind_set_level），此时仍是改动前的盲进行为。
    已知限制：读出的等级可能来自非城寨页（面板会记住上次 Tab，而野蛮人页
    也有等级）——同一 ROI 上若两页都能读出合法数字，回读自洽、不会被自纠
    机制发现。待实机确认（spec §9）。
    """

    def __init__(self, handle_source, recognizers: dict, target_levels: list[int],
                 march_preset: int | None = None,
                 march_troop_types: list | None = None, event_bus=None,
                 wait_members_seconds: float = 330.0,
                 publisher_id: str | None = None,
                 ledger=None, queue_gate=None, human=None,
                 march_presets: list | None = None):
        self._handle = handle_source
        self._rec = recognizers
        # 有序搜索列表（2026-10-04）：本轮从第 0 个开始，每级连搜
        # _MAX_NO_RESULT 次无结果就换下一个，绕完一圈放弃。顺序完全按
        # 配置，不做降序假设（用户明确要求 6→4→5 这类顺序合法）
        self._target_levels = list(target_levels)
        # 有序预设列表（2026-10-09）：每项 (预设号, 兵种列表)。第一个确认
        # 不了高亮就换下一个（返程中的主将载不出预设，见 _select_preset）。
        # 新参数是**关键字**且在末尾：既有的 18 处位置参数调用（测试 +
        # either_sm）一字不改；只给旧的两个字段时退化成单元素列表，
        # 行为与改动前逐字相同。
        if march_presets:
            self._march_presets = [(int(p), list(t)) for p, t in march_presets]
        else:
            self._march_presets = [
                (int(1 if march_preset is None else march_preset),
                 list(march_troop_types or []))]
        # 兼容读侧：老代码/老测试读 _march_preset / _march_troop_types 时
        # 拿到首选那一项
        self._march_preset = self._march_presets[0][0]
        self._march_troop_types = list(self._march_presets[0][1])
        self._bus = event_bus
        self._wait_members_seconds = wait_members_seconds
        # 发布 rally_launched 时带上账号标识：either_sm 的进程级集结事件
        # 登记簿靠它区分「自己/对方」的集结（跨 SM 重建存活）
        self._publisher_id = publisher_id
        self.last_rally_event = None
        # 进程级动作账本（runtime 注入）：发车确认后记「部队在外」，
        # 供集结门槛的 L0 判据用。未注入 = 不记账 = 旧行为
        self._ledger = ledger
        # 预设列基准（槽 1 中心，2026-10-03）：默认取实测钉死值，首次模板
        # 命中后用命中位置校准（见 _select_preset / _calibrate_preset_column）
        self._preset_base = PRESET_TOP
        # 视图判定探针（2026-09-30）：只做「额外的成功信号」与「失败归因」，
        # 不取代 _normalize_view 的残留面板清理清单
        self._view_probe = ViewProbe(recognizers)
        # 集结前置门槛（2026-10-04 用户报 bug）：上一轮部队还在城外
        # （行军/返程/集结中）就开下一轮，「创建部队」表单载不出预设
        # （武将在外）→ 卡在「预设槽 N 高亮未确认」。门槛判据与 either
        # 共用同一份 QueueGate/queue_verdict。None = 不挂门 = 旧行为
        # （未注入 ledger 的部署、单测默认）。either 自己那份门照旧，
        # 故它传 None 以免重复观测同一批帧
        self._queue_gate = queue_gate
        self._gate_next_log = 0.0
        self._gate_last_msg = ""
        super().__init__(initial="IDLE", human=human)

    def step(self, context: dict | None = None) -> None:
        """集结前置门槛（见 __init__ 的 _queue_gate）。

        只在轮次入口（IDLE/NORMALIZE）拦截：队列没清空就原地等，一拍都
        不推进。放在 step 而不是转移表里，是因为「等待」不是一条边——
        它要停在原状态反复观测，而转移表只能前进。

        放行时补写账本回城：纯 leader 原本只有 mark_troops_out（_launch
        确认队列徽标后写），没有对应的回城写入，账本会永远停在「在外」。
        而门槛的 unknown 分支正是读账本的——不补这一笔，图标一旦不可辨
        就会 fail-closed 干等 unknown_grace（900s），把「开错车」换成
        「卡 15 分钟」。

        只在 verdict == "none"（队列真的判空）时写：账本 mark_troops_home
        的口径就是「派遣队列判空」，而 "gather" 是队列非空（只是不阻塞）。
        这与 either 的 WAIT_RETURN 同一口径（见 test_either_sm_gate 的
        test_wait_return_gather_does_not_mark_home）——同一面旗帜、同一个
        问题，两处不该给出不同答案。代价是采集队列在外的轮次账本仍停在
        「在外」，后续遇 unknown 会多等一段；方向安全（只会多等，不会误放）。
        """
        if self._queue_gate is not None and self.current in ("IDLE", "NORMALIZE"):
            outcome = self._queue_gate.observe(self.queue_verdict())
            if outcome.decision is GateDecision.WAIT:
                self._gate_log(outcome.reason)
                return
            if outcome.verdict == "none" and self._publisher_id:
                self._ledger.mark_troops_home(self._publisher_id)
            if outcome.source != "vote":
                # 判据来源不是投票 = 账本/兜底放行的，必须留痕：
                # 「为什么这轮放行了」在实机上是最难查的一类问题
                logger.warning("[集结门槛] 放行（判据来源 %s）：%s",
                               outcome.source, outcome.reason)
        super().step(context)

    def _gate_log(self, message: str) -> None:
        """门槛等待日志：30s 节流，但**换了理由立刻打**。

        2026-10-04 实机验证时被这条节流误导过：每轮第一拍总是「投票 1/3
        帧」，它把 30s 窗口吃掉，紧接着真正采信成 battle 的那条「有行军/
        驻扎队列在城外」被压掉——日志读起来像「门槛放行了」，其实是被拦
        住了（实机 14:03:03 首拍、14:03:36 才打出真因）。理由变了说明判据
        状态变了，正是最该看见的一刻，不能省。
        """
        now = time.time()
        if message != self._gate_last_msg or now >= self._gate_next_log:
            self._gate_last_msg = message
            self._gate_next_log = now + _GATE_LOG_INTERVAL
            logger.info("[集结门槛] %s", message)

    def queue_verdict(self) -> str:
        """右侧 */5 派遣队列判读（2026-09-16 实机重校准）：

        - 'none'      地图视图上徽标不可见=无队列在外
        - 'battle'    绿色脚印=行军中 / 蓝色旗帜=驻扎·集结等待 /
                      红色刀剑=战斗中（动态多形态动画：交叉 X=queue_battle_icon、
                      平行双剑=queue_fight_icon、白色「上箭头」挥舞帧=
                      queue_recall_icon —— 2026-09-17 实机确认无独立召回态，
                      取消集结直接解散无图标、撤回显示绿脚印普通行军；该模板
                      匹配的就是战斗动画帧）—— 阻塞，无宽限。
                      2026-09-16 用户报告：预设主将未回城（返程/战斗态）时
                      开集结，游戏让默认武将代开车打不过寨子。同日第二次
                      事故：返程/战斗图标无模板，采集锄头匹配把混合队列
                      误判成「仅采集」放行 —— 五态+战斗动画各形态
                      全部补齐模板
        - 'returning' 黄色返回箭头=返程中 —— **放行**（2026-10-09 用户拍板，
                      推翻 2026-09-16 的阻塞结论）。安全阀在车头侧：
                      _select_preset 对载不出预设的槽回退到下一个，全失败
                      则抛异常（2026-09-16 那次事故的成因正是「点了预设但没
                      确认、游戏用默认武将代开车」）
        - 'gather'    仅绿色锄头=采集在外（放行，2026-09-13 用户确认）
        - 'unknown'   徽标在但已知图标都不可辨，或不在地图视图无法判读
                      —— fail-closed 按在外处理，持续超宽限期才放行告警。
                      2026-09-14 实机教训：模板裁剪含背景像素换场景掉分，误判
                      「仅采集/已回城」提前开集结。2026-09-16：战争列表面板开着时
                      队列栏整体隐藏，「徽标不可见」被误读成「无队列」放行搜索。
                      未知宁可等。注：_find 不匹配与未配置都返回 None，须用
                      _rec.get 区分（未配置=门槛不生效，保持旧行为）

        2026-10-04 从 either_sm 搬到这里：整段只用 self._rec/_find/_handle，
        本来就是车头的事；纯 leader 也要用它（见 __init__ 的 _queue_gate）。
        """
        if self._rec.get("queue_badge") is None:
            return "none"   # 未配置徽标识别器：门槛不生效（与旧版一致）
        if self._find("queue_badge") is None:
            # 徽标不可见 ≠ 一定无队列在外：战争列表等面板开着时右侧队列栏
            # 整体隐藏（2026-09-16 实机：重启后战争面板残留，mumu0/mumu1
            # 双双被误判「无队列」放行搜索，而填兵部队还在他人集结里）。
            # 判据用「联盟旗帜可见=在地图视图」：地图上徽标才可信。
            # 不在地图视图时先关已知残留面板（与 normalize 同位）、点
            # map_btn 回地图，本拍按 unknown fail-closed 拦截，下一拍在
            # 地图视图上重新判读
            # 地图视图判据：alliance_btn（联盟旗帜）或 search_icon（左下
            # 放大镜）任一可见即可 —— 2026-09-18 实机：简化模式下联盟快捷
            # 键整体不显示（alliance_btn 模板在干净地图上仅 0.248），但
            # search_icon 只在地图视图出现，且战争列表/预警等全屏面板打开
            # 时同样被盖住（normalize 需先关面板才见 search_icon），不会
            # 重演 2026-09-16 面板残留误判「无队列」
            for proof in ("alliance_btn", "search_icon"):
                if self._rec.get(proof) is not None \
                        and self._find(proof) is not None:
                    return "none"   # 地图视图且无徽标：队列确实为空
            closed = False
            # 已知残留面板 → 关闭动作（与 leader normalize 同位坐标）：
            # 全屏模态（创建部队 form_title 2026-09-18 实机 run4 残留挡
            # 门槛）盖住一切时，normalize 根本没机会跑，门槛必须自己关
            for panel, action in (
                    ("war_title", ("click", 1671, 64)),
                    ("warning_panel", ("click", 1671, 64)),
                    ("form_title", ("click", 1671, 64)),
                    ("replace_popup", ("click", 1500, 170)),
                    ("rally_attack_popup", ("click", 960, 540)),
                    ("menu_expanded", ("click", 1845, 1010))):
                if self._find(panel) is not None:
                    self._handle.click(action[1], action[2])
                    closed = True
                    break
            if not closed and self._find("ap_refill") is not None:
                # 行动力不足弹窗：补体力（每日免费 500 + 初级恢复 100）而非
                # 关弹窗 —— 关掉下次行军还是弹，白烧轮次（2026-09-18 run9）
                closed = self._refill_ap()
                if not closed:
                    self._handle.click(1638, 120)
            if not closed and self._find("search_back") is not None:
                # 搜索面板开着（残留/恢复回流）：队列栏被搜索模式底栏整体
                # 隐藏（2026-09-16 实机 21:08 mumu1），退出搜索再判读
                self._click("search_back")
                closed = True
            if not closed:
                # 城市视图：左下角地图图标出城按钮（实机 (72,1034)，2026-09-16
                # 两号齐卡城市视图实锤）直接点击出城回地图。注意 map_btn
                # 模板是地图视图的「进入城市」城堡按钮 (92,985)，在
                # 城市视图不匹配、且语义相反，不能用它出城
                self._handle.click(72, 1034)
            return "unknown"
        # 阻塞集合（2026-10-09 起不含 queue_return_icon）：行军/驻扎/战斗中
        for icon in ("queue_march_icon", "queue_flag_icon",
                     "queue_battle_icon", "queue_fight_icon", "queue_recall_icon"):
            if self._find(icon) is not None:
                return "battle"
        # 返程中：放行（用户 2026-10-09 拍板）。返程的主将载不出预设，由
        # _select_preset 的回退兜住——不靠阻塞整轮，靠「载不出来就换一个」。
        if self._find("queue_return_icon") is not None:
            return "returning"
        if self._find("queue_gather_icon") is not None:
            return "gather"
        return "unknown"

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
        # 降级边必须先于放弃边注册（同上）。「还有下一个等级」= 下标未越界：
        # 到这就说明列表已绕完一圈（每级都搜满了额度），放弃本轮
        self.add_transition("CHECK_RESULT", "CONFIRM_SEARCH", self._switch_level,
                            guard=lambda ctx: ctx.get("search_outcome") == "no_result"
                            and ctx.get("no_result_count", 0) >= _MAX_NO_RESULT
                            and ctx.get("level_index", 0) + 1
                            < len(self._target_levels))
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

    def _current_level(self, ctx) -> int:
        """本轮当前在搜的等级 = target_levels[ctx["level_index"]]。

        下标缺失即第 0 个（列表首个 = 本轮起始等级）。越界由转移 guard
        挡在 _switch_level 之前，这里不做钳制——静默钳制会把「下标算错」
        伪装成「一直在搜最后一级」，正是最难查的那类问题。
        """
        return self._target_levels[ctx.get("level_index", 0)]

    def _read_level(self) -> int | None:
        """读搜索面板上的当前城寨等级；读不出返回 None。

        manifest 没配 `fortress_level`（旧配置 / 未更新模板）时直接返回
        None，调用方退回盲降——与改动前逐字相同的行为。
        """
        rec = self._rec.get("fortress_level")
        if rec is None:
            return None
        for attempt in range(_LEVEL_READ_ATTEMPTS):
            img = self._handle.capture()
            self.last_image = img          # 失败截图要能看到当时读到的是什么
            r = rec.recognize(img)
            if r.matched:
                raw = (r.data or {}).get("value", "")
                try:
                    lv = int(raw)
                except (TypeError, ValueError):
                    lv = None
                if lv is not None and 1 <= lv <= 10:
                    return lv
                # 读出个不在 1..10 的东西：面板多半不在城寨页（tab 切换失败）。
                # 不猜也不钳制——静默钳制会把「读错对象」伪装成「等级就是 10」，
                # 正是最难查的那类问题。
                logger.warning("[车头] 等级文本读出 %r（不在 1..10），视为读失败",
                               raw)
            if attempt < _LEVEL_READ_ATTEMPTS - 1:
                time.sleep(self._pause(None))
        return None

    def _set_level(self, target: int, current: int) -> int:
        """从 current 点差量到 target，返回实际点击次数（不写日志）。

        不加次数上限：两个端点都落在 1..10（`_read_level` 校验读值，
        `_current_level` 来自配置），差量天然有界。多一个上限只会让盲降
        路径不再与改动前等价，而「最坏情况与现状相同」是本次设计的前提。
        """
        delta = target - current
        btn = "level_plus" if delta > 0 else "level_minus"
        for _ in range(abs(delta)):
            self._click(btn, rapid=True)
        return abs(delta)

    def _cache_level(self, level: int) -> None:
        with _LEVEL_CACHE_LOCK:
            _LEVEL_CACHE[self._handle] = level

    def _blind_set_level(self, target: int) -> None:
        """等级读不出时的降级路径 = 改动前 _select_level 的主体，逐字保留。

        spec §4.4：**不删缓存**。缓存命中就只点差量，否则 12 连点降底再升。
        这条路径只在 OCR 失败时走到，保留缓存才能兑现「最坏情况与改动前相同」。
        与原实现的唯一差别是：每点一下的停顿不再由这里 sleep，改由
        JitteringHandleSource 按 `rapid=True` 用 rapid_click_min/max 承担
        （spec §5.2）——点击次数与顺序逐字未变。
        """
        with _LEVEL_CACHE_LOCK:
            cached = _LEVEL_CACHE.get(self._handle)
        if cached == target:
            logger.info("[车头] 面板等级已是 %s 级，跳过调整", target)
            return
        if cached is None:
            logger.info("[车头] 面板等级未知，先降到底再升到 %s 级", target)
            for _ in range(_LEVEL_BLIND_RESET):
                self._click("level_minus", rapid=True)
            start = 1
        else:
            start = cached
        self._set_level(target, start)
        self._cache_level(target)
        logger.info("[车头] 面板等级 %s → %s 级（%s 次点击）", start, target,
                    (_LEVEL_BLIND_RESET if cached is None else 0)
                    + abs(target - start))

    def _verify_level(self, target: int) -> bool:
        """回读校验 + 补点。返回 True = 已确认面板在 target。

        最后只 warning 不抛错：等级偏差会被后续 no_result 计数自然兜住
        （_check_result 的既有机制），不该为此直接烧掉一轮。
        """
        for _ in range(_LEVEL_VERIFY_ROUNDS):
            read = self._read_level()
            if read is None:
                return False
            if read == target:
                logger.info("[车头] 等级回读确认 %s 级", target)
                return True
            logger.warning("[车头] 等级回读 %s 级 ≠ 目标 %s 级，补点 %s 次",
                           read, target, abs(target - read))
            self._set_level(target, read)
        logger.warning("[车头] 等级回读仍未确认（目标 %s 级），继续本轮", target)
        return False

    def _select_level(self, ctx):
        # 面板记住上次的 Tab（实测落在「野蛮人」上，2026-09-11 实机验收发现）。
        # tab_fortress 模板采的是未选中（灰色）态：匹配到 ⇔ 当前不在城寨页，
        # 点它切换；已在城寨页（棕色选中态）不匹配，_click 自动跳过。
        self._click("tab_fortress")
        target = self._current_level(ctx)

        current = self._read_level()
        if current is None:
            logger.warning("[车头] 等级文本读不出（面板可能不在城寨页），退回盲降")
            self._blind_set_level(target)
            return
        if current == target:
            logger.info("[车头] 面板等级已是 %s 级，跳过调整", target)
            self._cache_level(target)
            return
        n = self._set_level(target, current)
        logger.info("[车头] 面板等级 %s → %s 级（%s 次点击）", current, target, n)
        if self._verify_level(target):
            self._cache_level(target)

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

    def _switch_level(self, ctx):
        """本等级搜满 _MAX_NO_RESULT 次仍无结果 → 换列表里的下一个等级。

        2026-10-04 用户要求：某个等级的城寨在附近被清光时，死磕同一级
        只会白烧轮次。计数**清零**——「5 次」是每级的额度，不是整轮额度
        （三级 = 最多 15 次搜索）；绕完一圈由转移 guard 拦下走 _give_up。
        """
        prev = self._current_level(ctx)
        ctx["level_index"] = ctx.get("level_index", 0) + 1
        ctx["no_result_count"] = 0
        logger.warning("[车头] %s 级连续 %s 次搜不到，改搜 %s 级"
                       "（列表第 %s/%s 个）", prev, _MAX_NO_RESULT,
                       self._current_level(ctx), ctx["level_index"] + 1,
                       len(self._target_levels))
        self._retry_search(ctx)

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
        # no_result_count 是**每级**额度、降级时清零，所以这里报「已试等级」
        # 而不是累计次数——不然日志会读成「只搜了 5 次就放弃」
        tried = self._target_levels[:ctx.get("level_index", 0) + 1]
        logger.warning("[车头] 放弃本轮集结：%s（已试等级 %s，末级无结果 %s 次 / "
                       "锁定 %s 次），冷却后自动重试", ctx["fail_reason"], tried,
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
        preset, troops = self._select_preset()
        ctx["used_preset"] = preset
        # 点胜出预设**自己的**兵种，不是全局兵种（多预设下每个槽可以配不同兵）
        for t in troops:
            self._click(f"troop_{t}")

    def _select_preset(self) -> tuple[int, list[str]]:
        """按配置顺序挑一个能确认高亮的预设槽，返回 (预设号, 兵种列表)。

        逐个预设跑 `_select_one_preset`（原实现，逐字复用：模板点击 + 列
        基准自校准 + 确认 `selected_preset_N` 高亮）；**第一个确认成功的
        胜出**。全部确认不了仍抛异常（保持 loud 失败）。

        为什么需要回退（2026-10-09 用户要求）：队列门槛已放行「返程中」
        （见 queue_verdict 的 "returning"），而返程中的主将载不出预设 ——
        回退就是这次放行的安全阀：载不出来就换下一个槽，而不是用默认武将
        代开车（2026-09-16 那次事故）。全都载不出来说明确实没兵可派，
        抛异常交给 runner 重试。

        未配置 `selected_preset_N` 识别器时（manifest 没写 pixel_stats 的
        部署）`_select_one_preset` 走盲点分支、必然「成功」，因此**不会**
        回退——这是刻意的：没有判据就没有回退依据，宁可保持旧行为。
        """
        first = self._march_presets[0][0]
        last_exc = None
        for idx, (n, troops) in enumerate(self._march_presets):
            try:
                self._select_one_preset(n)
            except RuntimeError as exc:
                last_exc = exc
                if idx + 1 < len(self._march_presets):
                    logger.warning("[车头] 预设槽 %s 高亮确认不了，改用下一个"
                                   "预设槽 %s", n, self._march_presets[idx + 1][0])
                continue
            if idx:
                logger.info("[车头] 预设槽 %s 不可用，本轮改用预设槽 %s",
                            first, n)
            return n, list(troops)
        # 单预设：逐字保留 _select_one_preset 的原异常（spec §6「单元素时行为
        # 与旧版逐字相同」——旧消息里带具体槽号与轮数，是既有测试与运维日志
        # 都依赖的口径）。多预设才用下面的聚合消息，好把「全都不可用」讲清。
        if len(self._march_presets) == 1:
            raise last_exc
        raise RuntimeError(
            f"预设槽 {[n for n, _ in self._march_presets]} 全部高亮未确认，"
            "拒绝派错兵，集结未发起")

    def _select_one_preset(self, n: int) -> None:
        """点预设槽并**确认**高亮移到了槽 N（2026-09-27）。

        旧实现是盲点：`self._click(f"preset_{N}")` 的返回值直接丢掉，两种失败
        都静默——模板失配=空操作（用游戏默认兵种），模板串位=**派错兵**
        （`_click_result` 点的是匹配到的位置，而 preset_* 六个槽只差中间数字）。

        1) 先走模板（现状路径）；命中时顺带用命中位置校准整列基准
           （`_calibrate_preset_column`，2026-10-03）；
        2) 失配时按槽心几何直接点——`cx=1655`、`cy=基准+82*(N-1)`，基准默认
           是 44 帧实测的 474（`march_btn` cy=925、`form_title` cy=69 逐字节
           不变），被校准过就用校准值。模板腿失配不等于这轮必须空过。
           串位也走这条路：确认失败 → 几何点正确槽 → 确认通过；
        3) 3 轮都确认不了就**抛异常**。两个号 `march_preset` 都是 1，点错是
           **系统性**错兵，宁可 loud 失败让 runner 重试，也不发一轮兵种不可信
           的集结。

        **2026-10-03 实机教训**：基准写死会过期。实机帧量到槽心是
        `432+82*(N-1)`——面板整体上移 42px，而 `march_btn`/`form_title` 分毫
        未动，所以「拿面板框当锚点」也救不了。后果是 `selected_preset_1`
        永远不 matched：每轮 3 次确认全失败 → 抛异常 → runner 连错 6 次 →
        worker 收工（现象：卡在创建部队面板不动）。现在基准从模板命中位置
        现算，见 `_calibrate_preset_column` 的取舍说明。

        未配置 `selected_preset_N` 识别器时退回旧的盲点行为——manifest 没写
        `pixel_stats:` 的部署、以及 test_leader_sm 的 26 击断言都靠这道守卫。
        """
        rec_id = f"selected_preset_{n}"
        if self._rec.get(rec_id) is None:
            self._click(f"preset_{n}")
            return
        for attempt in range(_PRESET_ATTEMPTS):
            hit = self._find(f"preset_{n}")
            if hit is not None:
                self._calibrate_preset_column(hit, n)
                self._click_result(hit)
                if self._wait_for(rec_id, timeout=_PRESET_CONFIRM_TIMEOUT,
                                  interval=_PRESET_CONFIRM_INTERVAL):
                    # 确认路径要进日志：这条改动的前提就是旧实现「两种失败都
                    # 静默」，若成功也静默，实机就只能靠「没抛异常」反推——
                    # 那是把静默从失败挪到了成功上。
                    logger.info("[车头] 预设槽 %s 已确认（模板点击，第 %s 轮）",
                                n, attempt + 1)
                    return
            # 模板失配（点击是空操作）或点完没确认（点偏/被挡）→ 按槽心几何
            # 补点一次。串位也走这条路：确认失败 → 几何点正确槽 → 确认通过
            self._click_xy(*slot_center(n, self._preset_base), anchor="preset_slot")
            if self._wait_for(rec_id, timeout=_PRESET_CONFIRM_TIMEOUT,
                              interval=_PRESET_CONFIRM_INTERVAL):
                logger.info("[车头] 预设槽 %s 已确认（几何补点，第 %s 轮）",
                            n, attempt + 1)
                return
            logger.warning("[车头] 预设槽 %s 未确认（基准 cy=%.0f，%s），重试",
                           n, self._preset_base,
                           "模板命中" if hit is not None else "模板失配")
        raise RuntimeError(f"预设槽 {n} 高亮未确认（{_PRESET_ATTEMPTS} 轮），"
                           f"拒绝派错兵，集结未发起")

    def _calibrate_preset_column(self, hit, n: int) -> None:
        """用 `preset_N` 模板命中的位置反推整列基准（2026-10-03 实机）。

        命中的就是槽 N 的图标，所以槽 1 中心 `top = y_hit - 82*(N-1)`。这条
        信号是已经验证过的（阈值 0.97，780 帧零串位），比写死的 474 更能跟
        上游戏改版：实机面板整体上移 42px 那次，就是它把基准从 474 拉到 432。

        **只认落在预设列 ROI 内的命中**（manifest 里 preset_* 的 roi 是
        x 1600..1712）：列外的命中不是预设图标，拿它定基准只会把列搬错地方。

        取舍：模板若真串到邻槽，基准会跟着串，确认就成了自证。这条由 0.97
        阈值挡住（正确槽最低 0.9935 / 串邻槽最高 0.9616）。实机真正会遇到的
        「点空操作」「点偏到邻槽」仍然拦得住——高亮位置是独立测出来的。
        """
        cx, cy = hit.bbox.center()
        if abs(cx - PRESET_CX) > PRESET_COL_HALF_X:
            return   # 不在预设列里，不是槽心，别拿它定基准
        top = cy - (n - 1) * PRESET_PITCH
        if abs(top - self._preset_base) < 1.0:
            return
        self._preset_base = top
        logger.info("[车头] 预设列基准自校准 -> 槽 1 cy=%.0f（槽 %s 模板命中 "
                    "y=%.0f）", top, n, cy)
        # 判据的取样基准也挪过去：六个槽共用一份 judge，调一个即可
        for slot in range(1, 7):
            rec = self._rec.get(f"selected_preset_{slot}")
            calibrate = getattr(rec, "calibrate", None)
            if calibrate is not None:
                calibrate(top)
                break

    def _launch(self, ctx):
        # 必须确认 march_btn 点击成功后再发布 rally_launched——点击失败
        # 不得触发成员填兵。
        #
        # 「补体力 → 点行军」做成有界循环（2026-10-04 实机 3 次
        # `行动力补充后 march_btn 点击失败` 的修法）：原实现只在行军点击
        # **首次**弹窗时补一次体力，补完再点若又弹（AP 仍不够），直接抛错，
        # 全靠 runner 退避重试才恢复。这里补到行军点得出去、或补满
        # _AP_REFILL_MAX 次为止；真耗尽时按上限放弃本轮，走 runner 的
        # 连续失败计数停机，不再靠异常兜。
        for attempt in range(1, _AP_REFILL_MAX + 1):
            if self._find("ap_refill") is not None:
                # 入口残留（2026-09-18 run10 实机：残留弹窗盖住 march_btn，
                # 先找行军只会一路异常，永远走不到补体力分支）或上一轮补完
                # 仍不够：补体力并关弹窗再点行军
                if not self._refill_ap():
                    raise RuntimeError("行动力补充弹窗关不掉，集结未发起")
            if not self._click_retry("march_btn", attempts=3):
                raise RuntimeError("march_btn 点击失败，集结未发起")
            # 行动力不足弹窗（行动力 < 消耗，2026-09-18 实机 run9）：行军
            # 根本没发出去，必须补体力后补点行军，否则集结未发起却发布了
            # 事件，成员白等一轮。弹窗没复现 = 这次真发出去了
            if not self._wait_for("ap_refill", timeout=3.0):
                break
            logger.warning("[车头] 行军点击后仍弹行动力不足（第 %s/%s 次），"
                           "补体力再试", attempt, _AP_REFILL_MAX)
        else:
            raise RuntimeError(
                f"行动力补充 {_AP_REFILL_MAX} 次后 march_btn 仍点不出去"
                "（疑似体力耗尽/道具用尽），集结未发起")
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
        used = ctx.get("used_preset", self._march_presets[0][0])
        self.last_rally_event = {
            "rally_id": f"rally_{int(time.time())}",
            # 实际搜到的那一级（多选列表里可能已降过级），不是列表首个
            "fortress_level": self._current_level(ctx),
            # 实际用上的预设号（可能是回退后的第二个），供日志/账本核对
            "march_preset": used,
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
                    self._current_level(ctx), used)
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
