"""答题模式状态机（spec docs/superpowers/specs/2026-10-24-答题模式-design.md §6/§9）。

一轮 = 收拾画面 → 进答题活动 → 逐题「读题 → 作答 → 验绿 → 学习 → 等翻页」
→ 活动结束即收工。**一天一轮**（用户 2026-10-25 拍板：答到活动结束算
一轮，无法重复答）——没有轮次/冷却配置，round_over 边直通 END。

入口带「距开始还有」倒计时时（进入按钮置灰）：原地轮询等开始，不点置灰
按钮、不消耗导航步数（用户 2026-10-24 拍板：无限等待到开始）。

三种场次（用户 2026-10-24 拍板：**按星期几绑定，不靠 OCR 识别**）：
初试（周六）固定 10 题、终试（周日）固定 20 题，都是固定时间入场、
单题限时；周一至周五的日常答题任意时间可答、无单题时限、不限题量
（答到活动结束算一轮）。补点预算按场次分配：考试从紧，日常从宽。

**本模块绝不抛异常**：所有失败都写成 `ctx["fail_reason"] = <常量>` + END 边。
抛异常会让 WorkerRunner 在同一状态退避重放，攒满 6 次直接停机——一次
「这题读不出来」不该升级成停机。

**等待一律不 sleep**：用 `_not_before[状态]` + `step()` 提前返回（与
gem_sm 的 WAIT、either_sm 的 WAIT_RETURN 同一套路），否则用户点 Stop
要等完整段冷却才 join 得上。
"""
from __future__ import annotations

import time

from ..core.quiz.bank import QuizBank, normalize
from ..core.quiz.models import ScreenQuestion
from ..core.quiz.screen import (
    detect_quiz, entry_countdown_active, find_quiz_entry, parse_question,
)
from ..core.quiz.session import (
    SESSION_DAILY, SESSION_LABELS, SESSION_QUESTION_LIMITS, current_session,
)
from ..core.quiz.solver import Solver
from ..core.quiz.verify import pick_correct_option
from ..infra.logger import get_logger
from .state_machine import NORMALIZE_STUCK_REASON, StateMachine

logger = get_logger(__name__)

# ---- 失败原因常量（runner._ENV_FAIL_REASONS 按值对齐，见哨兵用例）----

# 环境类：不计入连续失败
QUIZ_ENTRY_MISSING_REASON = "quiz_entry_missing"   # 找不到答题入口 / 活动没开
QUIZ_SCREEN_LOST_REASON = "quiz_screen_lost"       # 画面被弹窗/断线盖住
QUIZ_PARSE_FAILED_REASON = "quiz_parse_failed"     # 一题都没答就连续读不出
# 真失败：计入连续失败。点了选项、画面却停在原题——这不是环境问题，
# 是「这票没被受理」（spec §6 的反例）。
ANSWER_NOT_ACCEPTED_REASON = "answer_not_accepted"

# 进活动最多点几拍。实机路径（2026-10-25 探针）是
# 地图→活动图标→左栏翻找「国士无双」→前往→进入，共 6 拍；
# 留余量给「翻找多一次」的情况。
_NAV_MAX = 10
_NORMALIZE_ATTEMPTS = 5
_NAV_SETTLE = 1.5         # 点完入口/落点后等动画
_ACTIVITY_SETTLE = 2.0    # 点活动图标后等面板打开（比普通按钮慢）
_COUNTDOWN_POLL = 20.0    # 入口「距开始还有」倒计时期间的轮询间隔（秒）
_PARSE_INTERVAL = 1.0     # 读不出题时的重读间隔
_ADVANCE_INTERVAL = 1.2   # 答完一题后等翻页的轮询间隔
_ADVANCE_WAIT_MAX = 4     # 同一题最多再看几眼才判「没翻页」
# 选项点击补点（2026-10-24 实机 0 分事故）：每题点击常发生在题目飞入
# 动画中，游戏吞掉动画期间的点击；VERIFY 没绿色就原地再点同一个选项。
# 初试/终试有单题限时（实机约 20s）：补点必须快而少；日常答题没有时限
# （用户 2026-10-24 补充），可以多点几次、多等一会。
EXAM_CLICK_RETRIES = 2        # 考试（初试/终试）的补点次数
EXAM_RETRY_DELAY = 0.8        # 考试补点前让画面稳一稳（秒）
PRACTICE_CLICK_RETRIES = 4    # 日常答题的补点次数
PRACTICE_RETRY_DELAY = 1.0    # 日常答题补点前的稳定间隔（秒）

# 归一化时要收掉的残留面板（与 gem_sm 同一套落点，理由见那边注释）
_FORM_CLOSE_XY = (1716, 69)
_WAR_CLOSE_XY = (1671, 64)
_QUEUE_COLLAPSE_XY = (1550, 320)
# 底部快捷菜单展开态：再点右下角 ☰ 收起（与 member_sm 同一落点，2026-09-16
# 实机验证）。展开时整排「战役/道具/联盟/统帅/邮件」盖住左下/右下的地图按钮，
# 联盟旗帜（alliance_btn）会整个消失。
_MENU_COLLAPSE_XY = (1845, 1010)
# 点 ☰ 之后必须**等菜单真的消失**再回主循环。收起有动画：立刻再抓的那一帧
# 仍然判「展开」→ 又点一次 ☰ → 把刚收起的菜单点开（实机 2026-10-25 探针：
# 归一化前后两帧完全一致，menu_expanded 0.995 不动，就是点了偶数次）。
_MENU_SETTLE = 0.6        # 每拍等动画的间隔（秒）
_MENU_SETTLE_MAX = 3      # 最多等几拍就放弃（放弃后主循环再判，不无限等）

# ---- 地图 → 活动中心 → 国士无双（2026-10-25 实机探测出的唯一路径）----
# 地图右侧「活动」卷轴图标：没有任何文字，OCR 找不到，靠模板 `activity_icon`
# 在右上角 HUD 里定位（manifest 里有 ROI/阈值/实测分）。
# `_ACTIVITY_ICON_XY` 只是**模板没命中时的退路**：1920×1080 实测 (1682,127)
# 能打开活动中心（旁边是火把=征服赛季、奖杯=另开面板）。
_ACTIVITY_ICON_XY = (1682, 127)
# 活动面板左上角返回箭头（地图/活动中心/活动页同一位置）。BACK 键在 MuMu 上
# 禁用（2026-09-16 记录），只能点这个。
_ACTIVITY_BACK_XY = (44, 58)
# 活动中心左栏是活动列表，默认停在「热门活动」顶部，「国士无双」常在折叠线
# 以下——实机要往下滚 3 次才出现。返回键在这台模拟器上禁用（2026-09-16 记录），
# 所以只滚不再开面板。
_LEFT_LIST_SCROLL = (380, 900, 380, 380)
_LEFT_LIST_SCROLL_MS = 600
_LEFT_LIST_SCROLL_MAX = 4
# 活动中心面板的自有文案，用来区分「面板开着」和「在地图上」。
_ACTIVITY_CENTER_WORDS = ("活动负载", "热门活动", "活动日历", "活动中心")
# 左栏列表占页面左侧的比例：详情页标题也常写「国士无双」，靠横向位置区分。
_LIST_X_RATIO = 0.30
# 国士无双标题的 OCR 变体（与 screen.py 的 TITLE_KEYWORDS 对齐）
_QUIZ_TITLES = ("国士无双", "国王无双")


def _label_center(blocks, label: str) -> tuple[int, int] | None:
    """文本**恰好等于** label 的块的中心点。

    导航按钮只认精确文本：`前往` 若按包含匹配会命中「前往其他活动」这类
    说明文字，`进入` 会命中「进入条件」，点到就是别处。
    """
    for box, text, _conf in blocks:
        if text.strip() == label:
            return box.center()
    return None


def _is_quiz_title(text: str) -> bool:
    return any(title in text for title in _QUIZ_TITLES)


def _quiz_detail_visible(blocks, width: int) -> bool:
    """是不是「国士无双」详情页：标题在页面中部（不在左侧列表栏）。

    活动中心左栏也有同名条目，两者只靠横向位置区分（实机 1920 宽：左栏
    x≈372，详情标题 x≈694；2664 宽时分别 ≈500 / ≈1092）。
    """
    return any(_is_quiz_title(text.strip()) and box.x1 > width * _LIST_X_RATIO
               for box, text, _conf in blocks)


def _quiz_list_row(blocks, width: int) -> tuple[int, int] | None:
    """活动中心左栏的「国士无双」条目中心；不在左栏就是 None。"""
    for box, text, _conf in blocks:
        if text.strip() in _QUIZ_TITLES and box.x2 <= width * _LIST_X_RATIO:
            return box.center()
    return None


def _activity_center_open(blocks) -> bool:
    """画面是不是活动中心面板（地图 HUD 被面板盖住时用它判）。"""
    return any(word in text for _box, text, _conf in blocks
               for word in _ACTIVITY_CENTER_WORDS)


def _activity_screen_open(blocks) -> bool:
    """画面是不是活动中心或国士无双活动页（含时间轴）。

    归一化用：这两种画面都是**上一轮的残留**，既没有地图 HUD 也不是答题
    界面——不收掉就是 normalize_stuck（2026-10-25 实机：入口导航中止后
    停在活动页，下一轮重建 SM 就卡在这）。
    """
    if _activity_center_open(blocks):
        return True
    return any(text.strip() in ("习题演练", "初试", "终试")
               for _box, text, _conf in blocks)


class QuizStateMachine(StateMachine):
    def __init__(self, handle_source, ocr, bank: QuizBank, solver: Solver, *,
                 recognizers=None, verify_delay: float = 1.2,
                 min_green_ratio: float = 0.55,
                 parse_retries: int = 2, entry_taps=None,
                 auto_click: bool = True, char_id: str = "?",
                 human=None, clock=time.time, sleeper=time.sleep, rng=None):
        self._handle = handle_source
        self._ocr = ocr
        self._rec = recognizers or {}
        self._bank = bank
        self._solver = solver
        self._verify_delay = float(verify_delay)
        self._min_green_ratio = float(min_green_ratio)
        self._parse_retries = max(1, int(parse_retries))
        self._entry_taps = [tuple(int(v) for v in tap)
                            for tap in (entry_taps or [])]
        self._auto_click = bool(auto_click)
        self._char_id = char_id
        self._clock = clock
        self._sleep = sleeper
        # 各状态的「最早可再跑」时刻：等待靠它实现，**不阻塞线程**
        self._not_before: dict[str, float] = {}
        self._pending_question: ScreenQuestion | None = None
        self._answered_key = ""       # 上一题的归一化题干（判「有没有翻页」）
        self._answered = 0
        self._q_clicks = 0            # 本题已点了几次选项（补点计数）
        self._read_waits = 0
        self._advance_waits = 0
        self._nav_steps = 0
        self._list_scrolls = 0        # 活动中心左栏已翻了几次（找国士无双）
        self._countdown_logged = False   # 倒计时等待已记过日志（避免每 20s 一条）
        self._session: str = SESSION_DAILY   # 本场轮次的场次（_reset_nav 按星期几绑定）
        super().__init__(initial="IDLE", human=human)
        self.last_image = None

    # ---- 场次与题量上限（用户 2026-10-24 拍板：按星期几绑定，题量固定） ----

    def _question_cap(self) -> int | None:
        """单轮题数上限：初试 10 / 终试 20（固定）；日常答题 None = 不限量，
        答到活动结束算一轮。"""
        return SESSION_QUESTION_LIMITS[self._session]

    def _click_retry_budget(self) -> tuple[int, float]:
        """补点预算（次数, 间隔秒）：考试限时从紧，日常答题从宽。"""
        if self._session == SESSION_DAILY:
            return PRACTICE_CLICK_RETRIES, PRACTICE_RETRY_DELAY
        return EXAM_CLICK_RETRIES, EXAM_RETRY_DELAY

    # ---- 转移表 ----

    def _setup(self):
        self.add_transition("IDLE", "NORMALIZE", self._normalize_view)
        self.add_transition("NORMALIZE", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            == NORMALIZE_STUCK_REASON)
        self.add_transition("NORMALIZE", "OPEN_QUIZ", self._reset_nav)

        # 入口导航：END（找不到入口）→ 自环（继续点）→ READ（进得去）
        self.add_transition("OPEN_QUIZ", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            == QUIZ_ENTRY_MISSING_REASON)
        self.add_transition("OPEN_QUIZ", "OPEN_QUIZ", self._open_quiz_step,
                            guard=lambda ctx: ctx.get("in_quiz") is False)
        self.add_transition("OPEN_QUIZ", "READ", self._read)

        # 读题：中止边必须最先注册
        self.add_transition("READ", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            in (QUIZ_SCREEN_LOST_REASON, QUIZ_PARSE_FAILED_REASON))
        self.add_transition("READ", "END", self._end_round,
                            guard=lambda ctx: ctx.get("round_over") is True)
        self.add_transition("READ", "READ", self._read,
                            guard=lambda ctx: ctx.get("parse_verdict") == "retry")
        self.add_transition("READ", "ANSWER", self._choose)

        self.add_transition("ANSWER", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason") is not None)
        # 半自动（auto_click=false）：给完建议就收本轮，不能等一个不存在的点击
        self.add_transition("ANSWER", "END", self._end_round,
                            guard=lambda ctx: ctx.get("semi_auto") is True)
        self.add_transition("ANSWER", "VERIFY", self._verify)

        self.add_transition("VERIFY", "ANSWER", self._choose,
                            guard=lambda ctx: ctx.get("retry_click") is True)
        self.add_transition("VERIFY", "LEARN", self._learn)
        self.add_transition("LEARN", "ADVANCE", self._advance)

        # 翻页：真失败边最先，其次前进/收轮，最后是无 guard 的等待自环
        self.add_transition("ADVANCE", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            == ANSWER_NOT_ACCEPTED_REASON)
        self.add_transition("ADVANCE", "READ", self._enter_next,
                            guard=lambda ctx: ctx.get("next_question") is True)
        self.add_transition("ADVANCE", "END", self._end_round,
                            guard=lambda ctx: ctx.get("round_over") is True)
        self.add_transition("ADVANCE", "ADVANCE", self._advance)

    # ---- step 覆写：所有等待都是「看时钟」，不是 sleep ----

    def step(self, context: dict | None = None) -> None:
        if self._clock() < self._not_before.get(self.current, 0.0):
            return
        super().step(context)

    def is_terminal(self) -> bool:
        return self.current == "END"

    def _wait_here(self, state: str, delay: float) -> None:
        self._not_before[state] = self._clock() + max(0.0, delay)

    # ---- 收尾出口 ----

    def _abort_round(self, ctx):
        logger.warning("[答题 %s] 本轮中止：%s", self._char_id,
                       ctx.get("fail_reason"))

    def _end_round(self, ctx):
        """一轮收工：只留痕，不等待。

        答题一天只能答一次（用户 2026-10-25 拍板）：没有轮间冷却，
        round_over 边直通 END，答满就走。
        """
        why = ctx.get("round_end_why")
        logger.info("[答题 %s] 本轮结束（答了 %s 题）%s", self._char_id,
                    self._answered, f"：{why}" if why else "")

    # ---- IDLE → NORMALIZE ----

    def _normalize_view(self, ctx):
        """收拾到「地图视图」或「答题/活动页」。

        与宝石模式的区别：**答题页也算归一化成功**。硬把画面收成地图会把
        已经打开的答题界面点掉，等于每轮重新找入口。

        地图视图有两个判据，**任一可见即成功**：联盟旗帜 `alliance_btn`，
        或左下角放大镜 `search_icon`（同为地图视图专属 HUD）。放大镜判的是
        「地图 HUD 可用、能点右侧活动图标」，不是镜头位置——镜头停在自己城市
        时它也常驻（2026-09-22 记录），这里正需要这个语义。只认旗帜会在
        两种常见画面上误判：底部快捷菜单展开时整排按钮盖住旗帜（2026-10-25
        实机：旗帜 0.212、放大镜 0.901、菜单 0.995），以及简化模式下联盟
        快捷键根本不显示（member_sm 2026-09-18 实机）。菜单展开态先收起再判，
        否则入口/地图按钮仍被它压着。
        """
        for _ in range(_NORMALIZE_ATTEMPTS):
            img = self._handle.capture()
            self.last_image = img
            blocks = self._ocr.detect_text(img)
            if parse_question(blocks, img.shape[1]) is not None \
                    or detect_quiz(blocks):
                ctx.pop("fail_reason", None)
                return
            if self._matched("net_error_confirm", img):
                self._click_net_error()
                continue
            if self._matched("menu_expanded", img):
                self._collapse_menu()
                continue
            if _activity_screen_open(blocks):
                # 上一轮停在活动中心/活动页（入口找不到就中止了）：点返回退回
                # 地图。不处理的话这里既没有地图 HUD 也没有题目，5 拍后误判
                # normalize_stuck。
                self._close_activity()
                continue
            if self._matched("alliance_btn", img) \
                    or self._matched("search_icon", img):
                ctx.pop("fail_reason", None)
                return
            if self._matched("form_title", img):
                self._handle.click(*_FORM_CLOSE_XY)
                continue
            if self._matched("war_title", img):
                self._handle.click(*_WAR_CLOSE_XY)
                continue
            if self._matched("queue_panel", img):
                self._handle.click(*_QUEUE_COLLAPSE_XY)
                continue
            if self._matched("map_btn", img):
                self._click("map_btn")
                continue
            self._sleep(self._pause(None))
        ctx["fail_reason"] = NORMALIZE_STUCK_REASON
        logger.warning("[答题] 归一化收拾不出地图或答题界面，本轮中止")

    def _collapse_menu(self) -> None:
        """点 ☰ 收起底部快捷菜单，并等到它**真的从画面消失**再返回。

        只点不等会让主循环在动画帧上再点一次（见 `_MENU_SETTLE` 注释）。
        等满 `_MENU_SETTLE_MAX` 拍还没收起就交回主循环重新判定——最多再点
        一次，不会变成无休止连点。
        """
        self._handle.click(*_MENU_COLLAPSE_XY)
        for _ in range(_MENU_SETTLE_MAX):
            self._sleep(_MENU_SETTLE)
            img = self._handle.capture()
            self.last_image = img
            if not self._matched("menu_expanded", img):
                return

    def _close_activity(self) -> None:
        """点返回箭头退出活动面板，并等到面板真的消失再返回。

        与 `_collapse_menu` 同一个坑：点完立刻抓的那帧还在退场动画里，
        主循环再点一次返回——而那时人已经在地图上，(44,58) 落到左上角
        玩家面板上（实机 2026-10-25：连点两次后 search_icon 掉到 0.38）。
        """
        self._handle.click(*_ACTIVITY_BACK_XY)
        for _ in range(_MENU_SETTLE_MAX):
            self._sleep(_MENU_SETTLE)
            img = self._handle.capture()
            self.last_image = img
            if not _activity_screen_open(self._ocr.detect_text(img)):
                return

    def _matched(self, rec_id: str, img) -> bool:
        rec = self._rec.get(rec_id)
        return rec is not None and rec.recognize(img).matched

    def _activity_icon_point(self, img) -> tuple[int, int]:
        """地图右侧「活动」卷轴图标的点击点。

        优先用模板 `activity_icon` 的命中框中心——卷轴位置会随顶栏图标增减
        横移（用户 2026-10-25 指出的风险），写死像素一旦挤偏就点空。模板没
        命中（没装这个模板 / 主题改动太大）才退回 `_ACTIVITY_ICON_XY`，
        并留一条日志说明用的是退路，免得以后误以为是模板在生效。
        """
        rec = self._rec.get("activity_icon")
        if rec is not None:
            res = rec.recognize(img)
            if res.matched and res.bbox is not None:
                return res.bbox.center()
            logger.info("[答题] 活动图标模板未命中（%.3f），改用固定落点 %s",
                        res.confidence, _ACTIVITY_ICON_XY)
        return _ACTIVITY_ICON_XY

    # ---- NORMALIZE → OPEN_QUIZ ----

    def _reset_nav(self, ctx):
        self._nav_steps = 0
        self._list_scrolls = 0
        self._countdown_logged = False
        # 场次按当天星期几绑定（用户 2026-10-24 拍板，不靠 OCR 识别）：
        # 周六=初试、周日=终试、周一至周五=日常答题。新一轮重新绑。
        self._session = current_session()
        cap = self._question_cap()
        cap_text = f"固定 {cap} 题" if cap is not None else "不限题量"
        logger.info("[答题 %s] 今日场次：%s（%s）", self._char_id,
                    SESSION_LABELS[self._session], cap_text)
        ctx.pop("fail_reason", None)
        ctx["in_quiz"] = False

    def _open_quiz_step(self, ctx):
        """一拍导航：按实机唯一路径把画面推进到答题界面。

        实机路径（2026-10-25 探针逐屏验证，1920×1080）：
        地图 →〔右侧「活动」卷轴图标，模板 activity_icon 定位〕→ 活动中心
             →〔左栏列表翻到「国士无双」点它〕→ 活动详情（右侧摘要）
             →〔「前往」〕→ 活动全页（7 天时间轴）
             →〔「进入」〕→ 答题界面。
        「进入」只在活动开着的当天、且有资格时出现；没出现就是环境原因
        （活动没开 / 初试没过拿不到终试资格），干净中止，别乱点。

        `parse_question`（而不是 `detect_quiz`）才是「已进答题界面」的判据：
        活动页标题里也有「国士无双」，`detect_quiz` 在活动页就是 True。

        倒计时门禁（2026-10-24 用户截图 + 录屏）：初试/终试没到开始时间时，
        页面上是「距开始还有 hh:mm:ss」、进入按钮置灰——点了不生效。这时
        **不点、不耗导航步数**，按 `_COUNTDOWN_POLL` 原地轮询等它开始
        （倒计时可能以小时计，耗光导航步数就打不进去了）；时钟不推进就
        什么都不做，Stop 随时响应。
        """
        ctx.pop("fail_reason", None)
        img = self._handle.capture()
        self.last_image = img
        blocks = self._ocr.detect_text(img)
        width = img.shape[1]
        question = parse_question(blocks, width)
        ctx["in_quiz"] = question is not None
        if question is not None:
            self._pending_question = question
            logger.info("[答题] 已在答题界面")
            return
        if entry_countdown_active(blocks):
            if not self._countdown_logged:
                logger.info("[答题] 入口倒计时未结束（距开始还有），等待开始…")
                self._countdown_logged = True
            self._wait_here("OPEN_QUIZ", _COUNTDOWN_POLL)
            return
        if self._countdown_logged:
            logger.info("[答题] 倒计时已结束，继续入口导航")
            self._countdown_logged = False
        if self._nav_steps >= _NAV_MAX:
            ctx["fail_reason"] = QUIZ_ENTRY_MISSING_REASON
            logger.warning("[答题] 导航 %s 步仍未进入答题界面，本轮中止", _NAV_MAX)
            return

        # ① 国士无双详情页（标题在页面中部，不是左栏）：先「前往」进活动全页，
        #    全页上才有「进入」。这一步走错会点到别的活动，所以只认国士无双。
        if _quiz_detail_visible(blocks, width):
            go = _label_center(blocks, "前往")
            if go is not None:
                self._nav_click(*go, what="前往")
                return
            enter = _label_center(blocks, "进入")
            if enter is not None:
                self._nav_click(*enter, what="进入")
                return
            ctx["fail_reason"] = QUIZ_ENTRY_MISSING_REASON
            logger.warning("[答题] 国士无双活动页上没有「进入」——活动今天没开，"
                           "或本号没有资格（初试未通过拿不到终试资格）。本轮中止")
            return

        # ② 活动中心左栏的「国士无双」行：点它把右侧详情切过去。
        row = _quiz_list_row(blocks, width)
        if row is not None:
            self._nav_click(*row, what="国士无双")
            return

        # ③ 活动中心开着但左栏没找到：往下翻（默认停在热门活动顶部）。
        if _activity_center_open(blocks):
            if self._list_scrolls >= _LEFT_LIST_SCROLL_MAX:
                ctx["fail_reason"] = QUIZ_ENTRY_MISSING_REASON
                logger.warning("[答题] 活动中心左栏翻了 %s 次也没找到国士无双"
                               "（活动可能不在本周期），本轮中止",
                               self._list_scrolls)
                return
            logger.info("[答题] 活动中心左栏翻找国士无双（第 %s 次）",
                        self._list_scrolls + 1)
            self._handle.swipe(*_LEFT_LIST_SCROLL, _LEFT_LIST_SCROLL_MS)
            self._list_scrolls += 1
            self._nav_steps += 1
            self._wait_here("OPEN_QUIZ", _NAV_SETTLE)
            return

        # ④ 屏幕上直接有入口文字（答题页的习题演练、活动页的进入等）。
        entry = find_quiz_entry(blocks)
        if entry is not None:
            self._nav_click(*entry, what="入口文字")
            return

        # ⑤ config 里的固定落点：用户手工指定的路径优先于内置地图落点。
        if self._nav_steps < len(self._entry_taps):
            x, y = self._entry_taps[self._nav_steps]
            logger.info("[答题] 点固定落点 (%s,%s)（第 %s 步）",
                        x, y, self._nav_steps + 1)
            self._click_xy(x, y, anchor="quiz_entry_tap")
            self._nav_steps += 1
            self._wait_here("OPEN_QUIZ", _NAV_SETTLE)
            return

        # ⑥ 地图：点右侧「活动」图标打开活动中心（位置由模板给，见
        #    `_activity_icon_point`）。
        if self._matched("search_icon", img) or self._matched("alliance_btn", img):
            self._nav_click(*self._activity_icon_point(img), what="活动图标",
                            settle=_ACTIVITY_SETTLE)
            return

        ctx["fail_reason"] = QUIZ_ENTRY_MISSING_REASON
        logger.warning("[答题] 屏幕上既没有入口文字、也不像地图或活动中心，"
                       "也没有可用的固定落点（config.quiz.entry_taps 为空或已用完），"
                       "本轮中止")
        return

    def _nav_click(self, x: int, y: int, *, what: str,
                   settle: float = _NAV_SETTLE) -> None:
        """入口导航的一次点击：记日志、点、计步、等动画。"""
        logger.info("[答题] 点%s (%s,%s)（第 %s 步）", what, x, y,
                    self._nav_steps + 1)
        self._click_xy(x, y, anchor="quiz_entry")
        self._nav_steps += 1
        self._wait_here("OPEN_QUIZ", settle)

    # ---- READ ----

    def _read(self, ctx):
        """读当前这一题。三种出口：作答、重读、收本轮/中止。"""
        ctx.pop("fail_reason", None)
        ctx.pop("round_over", None)
        ctx.pop("parse_verdict", None)
        ctx.pop("round_end_why", None)
        cap = self._question_cap()
        if cap is not None and self._answered >= cap:
            ctx["round_over"] = True
            ctx["round_end_why"] = (f"已达{SESSION_LABELS[self._session]}"
                                   f"单轮上限 {cap} 题")
            return
        img = self._handle.capture()
        self.last_image = img
        blocks = self._ocr.detect_text(img)
        question = parse_question(blocks, img.shape[1])
        if question is not None:
            if normalize(question.text) != self._answered_key:
                self._read_waits = 0
                self._pending_question = question
                logger.info("[答题] 第 %s 题：%s", self._answered + 1, question.text)
                return
            # 刚答过的那题还在屏幕上：等它翻页（有界）
            self._read_waits += 1
            if self._read_waits <= _ADVANCE_WAIT_MAX:
                ctx["parse_verdict"] = "retry"
                self._wait_here("READ", _ADVANCE_INTERVAL)
                return
            ctx["round_over"] = True
            ctx["round_end_why"] = "同一题反复出现"
            return
        # 读不出题：先处理断网弹框，再重读；耗尽后区分「结束」与「异常」。
        # 断网重试**也必须计入同一个有界计数**：断网期间弹框会在每次
        # 「确定」后又弹回来，若不计数，这里会每 1s 点一次、永不写
        # fail_reason（与 `_normalize_view` 的 `_NORMALIZE_ATTEMPTS` 同理，
        # 卡住必须是干净中止）。弹框点不掉时走下面的 classify：同样是
        # 环境类原因（`quiz_parse_failed` / `quiz_screen_lost`），不计失败。
        self._read_waits += 1
        if self._read_waits < self._parse_retries:
            if self._matched("net_error_confirm", img):
                self._click_net_error()
            ctx["parse_verdict"] = "retry"
            self._wait_here("READ", _PARSE_INTERVAL)
            return
        on_quiz_screen = detect_quiz(blocks)
        at_map = self._matched("alliance_btn", img)
        if self._answered > 0 and (on_quiz_screen or at_map):
            ctx["round_over"] = True
            ctx["round_end_why"] = ("活动页已无题" if on_quiz_screen
                                   else "已被送回地图")
            logger.info("[答题] 连续 %s 次读不出题目（%s），判本轮结束",
                        self._read_waits,
                        "仍在活动页" if on_quiz_screen else "已回到地图")
            return
        if self._answered > 0:
            ctx["fail_reason"] = QUIZ_SCREEN_LOST_REASON
            logger.warning("[答题] 连续 %s 次读不出题目，画面既不是答题页也不是"
                           "地图（弹窗/断线盖住了），本轮中止", self._read_waits)
            return
        ctx["fail_reason"] = QUIZ_PARSE_FAILED_REASON
        logger.warning("[答题] 连续 %s 次读不出题目，且本轮一题都没答过"
                       "（识别/分辨率/界面改版），本轮中止", self._read_waits)

    # ---- READ → ANSWER ----

    def _choose(self, ctx):
        ctx.pop("fail_reason", None)
        ctx.pop("semi_auto", None)
        ctx.pop("retry_click", None)
        question = self._pending_question
        if question is None:
            ctx["fail_reason"] = QUIZ_PARSE_FAILED_REASON
            logger.warning("[答题] 进入作答时没有待答题目（内部状态丢失），本轮中止")
            return
        decision = self._solver.answer(question)
        if decision is None:
            ctx["fail_reason"] = QUIZ_PARSE_FAILED_REASON
            logger.warning("[答题] 这道题没有可点的选项，本轮中止")
            return
        letter = decision.letter
        ctx["clicked_letter"] = letter
        ctx["answer_source"] = decision.source
        logger.info("[答题] %s → %s. %s（来源：%s，第 %d 次点击）",
                    question.text, letter, decision.text, decision.source,
                    self._q_clicks + 1)
        if not self._auto_click:
            ctx["semi_auto"] = True
            ctx["round_end_why"] = "auto_click=false，只给建议"
            return
        self._q_clicks += 1
        box = question.options[letter][1]
        self._click_xy(*box.center(), anchor="quiz_option")

    # ---- ANSWER → VERIFY ----

    def _verify(self, ctx):
        """答完等一会儿再截图：绿色高亮 = 正确答案。

        答错时所选项变红、正确项仍是绿，所以**答对答错都能学到答案**。
        没看到绿色只说明结算还没出来（或这题不会高亮），不算失败——
        「有没有翻页」由 ADVANCE 裁决。
        """
        ctx.pop("correct_letter", None)
        self._sleep(self._verify_delay)
        img = self._handle.capture()
        self.last_image = img
        question = self._pending_question
        if question is None:
            return
        boxes = {letter: box for letter, (_t, box) in question.options.items()}
        correct = pick_correct_option(img, boxes, min_ratio=self._min_green_ratio)
        if correct is None:
            # 没绿：结算没出来，或**这一票被游戏吞了**（实机 0 分事故：
            # 点击发生在题目飞入动画中，游戏不响应）。补点计数还有额度
            # 就回 ANSWER 再点一次同一个选项；额度用完才按「不学习」
            # 放行（ADVANCE 会等翻页，始终不翻再判真失败）。
            # 额度按场类型分配：初试/终试单题限时从紧，日常答题无时限从宽。
            retries, delay = self._click_retry_budget()
            if self._q_clicks <= retries:
                ctx["retry_click"] = True
                self._wait_here("VERIFY", delay)
                logger.info("[答题] 没看到绿色高亮，%s 秒后补点（第 %d/%d 次）",
                            delay, self._q_clicks + 1, retries + 1)
            else:
                logger.info("[答题] 没看到绿色高亮（补点 %d 次仍无结算），"
                            "这道题不学习", retries)
            return
        ctx["correct_letter"] = correct
        text = question.options[correct][0]
        if correct == ctx.get("clicked_letter"):
            logger.info("[答题] ✅ 答对（%s. %s）", correct, text)
        else:
            logger.info("[答题] ❌ 点的是 %s，绿色是 %s. %s",
                        ctx.get("clicked_letter"), correct, text)

    # ---- VERIFY → LEARN ----

    def _learn(self, ctx):
        question = self._pending_question
        if question is None:
            return
        self._q_clicks = 0                # 一题学完，补点计数归零
        correct = ctx.get("correct_letter")
        if correct is not None:
            answer = question.options[correct][0]
            if self._bank.learn(question.text, answer):
                logger.info("[答题] 已写入学习题库：%s → %s", question.text, answer)
        self._answered_key = normalize(question.text)
        self._answered += 1

    # ---- LEARN → ADVANCE ----

    def _advance(self, ctx):
        """等屏幕翻到下一题；始终不翻就判 `answer_not_accepted`（真失败）。"""
        ctx.pop("fail_reason", None)
        ctx.pop("next_question", None)
        ctx.pop("round_over", None)
        img = self._handle.capture()
        self.last_image = img
        blocks = self._ocr.detect_text(img)
        question = parse_question(blocks, img.shape[1])
        if question is not None and normalize(question.text) != self._answered_key:
            ctx["next_question"] = True
            self._pending_question = question
            return
        self._advance_waits += 1
        if self._advance_waits <= _ADVANCE_WAIT_MAX:
            self._wait_here("ADVANCE", _ADVANCE_INTERVAL)
            return
        if question is not None:
            ctx["fail_reason"] = ANSWER_NOT_ACCEPTED_REASON
            logger.warning("[答题] 点了选项 %s 后画面停在原题（%s 次），"
                           "这一票没被受理，本轮中止",
                           ctx.get("clicked_letter"), self._advance_waits)
            return
        ctx["round_over"] = True
        ctx["round_end_why"] = "答完后答题界面已结束"
        logger.info("[答题] 答完后读不出下一题（%s 次），判本轮结束",
                    self._advance_waits)

    def _enter_next(self, ctx):
        self._read_waits = 0
        self._advance_waits = 0
        # READ 的读题动作挂在「进入 READ」的边上（本状态机一个 step 只走
        # 一条边，guard 在 action 之前求值）。从 ADVANCE 回到 READ 也是
        # 一次进入，必须先读这一屏，否则下一拍会直接拿上一题的
        # `_pending_question` 去作答。
        self._read(ctx)
