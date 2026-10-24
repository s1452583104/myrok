"""答题模式状态机（spec docs/superpowers/specs/2026-10-24-答题模式-design.md §6/§9）。

一轮 = 收拾画面 → 进答题活动 → 逐题「读题 → 作答 → 验绿 → 学习 → 等翻页」
→ 活动结束 → 冷却。**答到活动结束算一轮**（用户 2026-10-24 拍板）。

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
from ..core.quiz.screen import detect_quiz, find_quiz_entry, parse_question
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

_NAV_MAX = 4              # 进活动最多点几拍
_NORMALIZE_ATTEMPTS = 5
_NAV_SETTLE = 1.5         # 点完入口/落点后等动画
_PARSE_INTERVAL = 1.0     # 读不出题时的重读间隔
_ADVANCE_INTERVAL = 1.2   # 答完一题后等翻页的轮询间隔
_ADVANCE_WAIT_MAX = 4     # 同一题最多再看几眼才判「没翻页」

# 归一化时要收掉的残留面板（与 gem_sm 同一套落点，理由见那边注释）
_FORM_CLOSE_XY = (1716, 69)
_WAR_CLOSE_XY = (1671, 64)
_QUEUE_COLLAPSE_XY = (1550, 320)


class QuizStateMachine(StateMachine):
    def __init__(self, handle_source, ocr, bank: QuizBank, solver: Solver, *,
                 recognizers=None, verify_delay: float = 1.2,
                 min_green_ratio: float = 0.55,
                 max_questions_per_round: int = 30,
                 round_cooldown_min: float = 10.0,
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
        self._max_questions = int(max_questions_per_round)
        self._cooldown_min = float(round_cooldown_min)
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
        self._read_waits = 0
        self._advance_waits = 0
        self._nav_steps = 0
        super().__init__(initial="IDLE", human=human)
        self.last_image = None

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
        self.add_transition("READ", "COOLDOWN", self._enter_cooldown,
                            guard=lambda ctx: ctx.get("round_over") is True)
        self.add_transition("READ", "READ", self._read,
                            guard=lambda ctx: ctx.get("parse_verdict") == "retry")
        self.add_transition("READ", "ANSWER", self._choose)

        self.add_transition("ANSWER", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason") is not None)
        # 半自动（auto_click=false）：给完建议就收本轮，不能等一个不存在的点击
        self.add_transition("ANSWER", "COOLDOWN", self._enter_cooldown,
                            guard=lambda ctx: ctx.get("semi_auto") is True)
        self.add_transition("ANSWER", "VERIFY", self._verify)

        self.add_transition("VERIFY", "LEARN", self._learn)
        self.add_transition("LEARN", "ADVANCE", self._advance)

        # 翻页：真失败边最先，其次前进/收轮，最后是无 guard 的等待自环
        self.add_transition("ADVANCE", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            == ANSWER_NOT_ACCEPTED_REASON)
        self.add_transition("ADVANCE", "READ", self._enter_next,
                            guard=lambda ctx: ctx.get("next_question") is True)
        self.add_transition("ADVANCE", "COOLDOWN", self._enter_cooldown,
                            guard=lambda ctx: ctx.get("round_over") is True)
        self.add_transition("ADVANCE", "ADVANCE", self._advance)

        self.add_transition("COOLDOWN", "END", lambda ctx: None)

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

    def _enter_cooldown(self, ctx):
        why = ctx.get("cooldown_why")
        logger.info("[答题 %s] 本轮结束（答了 %s 题）%s", self._char_id,
                    self._answered, f"：{why}" if why else "")
        self._wait_here("COOLDOWN", self._cooldown_min * 60.0)

    # ---- IDLE → NORMALIZE ----

    def _normalize_view(self, ctx):
        """收拾到「地图视图」或「答题/活动页」。

        与宝石模式的区别：**答题页也算归一化成功**。硬把画面收成地图会把
        已经打开的答题界面点掉，等于每轮重新找入口。
        """
        for _ in range(_NORMALIZE_ATTEMPTS):
            img = self._handle.capture()
            self.last_image = img
            blocks = self._ocr.detect_text(img)
            if parse_question(blocks, img.shape[1]) is not None \
                    or detect_quiz(blocks):
                ctx.pop("fail_reason", None)
                return
            if self._matched("alliance_btn", img):
                ctx.pop("fail_reason", None)
                return
            if self._matched("net_error_confirm", img):
                self._click_net_error()
                continue
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

    def _matched(self, rec_id: str, img) -> bool:
        rec = self._rec.get(rec_id)
        return rec is not None and rec.recognize(img).matched

    # ---- NORMALIZE → OPEN_QUIZ ----

    def _reset_nav(self, ctx):
        self._nav_steps = 0
        ctx.pop("fail_reason", None)
        ctx["in_quiz"] = False

    def _open_quiz_step(self, ctx):
        """一拍导航：已经在答题界面就停；否则点入口文字，再不行点固定落点。

        `parse_question`（而不是 `detect_quiz`）才是「已进答题界面」的判据：
        活动页标题里也有「国士无双」，`detect_quiz` 在活动页就是 True。
        """
        ctx.pop("fail_reason", None)
        img = self._handle.capture()
        self.last_image = img
        blocks = self._ocr.detect_text(img)
        question = parse_question(blocks, img.shape[1])
        ctx["in_quiz"] = question is not None
        if question is not None:
            self._pending_question = question
            logger.info("[答题] 已在答题界面")
            return
        if self._nav_steps >= _NAV_MAX:
            ctx["fail_reason"] = QUIZ_ENTRY_MISSING_REASON
            logger.warning("[答题] 导航 %s 步仍未进入答题界面，本轮中止", _NAV_MAX)
            return
        entry = find_quiz_entry(blocks)
        if entry is not None:
            logger.info("[答题] 点入口 %s（第 %s 步）", entry, self._nav_steps + 1)
            self._click_xy(*entry, anchor="quiz_entry")
        elif self._nav_steps < len(self._entry_taps):
            x, y = self._entry_taps[self._nav_steps]
            logger.info("[答题] 点固定落点 (%s,%s)（第 %s 步）",
                        x, y, self._nav_steps + 1)
            self._click_xy(x, y, anchor="quiz_entry_tap")
        else:
            ctx["fail_reason"] = QUIZ_ENTRY_MISSING_REASON
            logger.warning("[答题] 屏幕上没有入口文字，也没有可用的固定落点"
                           "（config.quiz.entry_taps 为空或已用完），本轮中止")
            return
        self._nav_steps += 1
        self._wait_here("OPEN_QUIZ", _NAV_SETTLE)

    # ---- READ ----

    def _read(self, ctx):
        """读当前这一题。三种出口：作答、重读、收本轮/中止。"""
        ctx.pop("fail_reason", None)
        ctx.pop("round_over", None)
        ctx.pop("parse_verdict", None)
        ctx.pop("cooldown_why", None)
        if self._answered >= self._max_questions:
            ctx["round_over"] = True
            ctx["cooldown_why"] = f"已达单轮上限 {self._max_questions} 题"
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
            ctx["cooldown_why"] = "同一题反复出现"
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
            ctx["cooldown_why"] = ("活动页已无题" if on_quiz_screen
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
        logger.info("[答题] %s → %s. %s（来源：%s）", question.text, letter,
                    decision.text, decision.source)
        if not self._auto_click:
            ctx["semi_auto"] = True
            ctx["cooldown_why"] = "auto_click=false，只给建议"
            return
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
            logger.info("[答题] 没看到绿色高亮（结算可能还没出来），这道题不学习")
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
        ctx["cooldown_why"] = "答完后答题界面已结束"
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
