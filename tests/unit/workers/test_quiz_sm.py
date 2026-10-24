"""答题状态机：一轮 = 进答题界面 → 逐题作答 → 活动结束 → 冷却。

测试用「按帧查表」的假 OCR（帧对象 → 块列表），不用真实模型：
这里要验的是转移与判据，解析本身在 tests/unit/core/test_quiz_screen.py。
"""
import json
import random

import numpy as np
import pytest

from rok_assistant.core.quiz.bank import QuizBank
from rok_assistant.core.quiz.screen import parse_question
from rok_assistant.core.quiz.solver import Solver
from rok_assistant.core.recognizer import BBox
import rok_assistant.workers.quiz_sm as quiz_sm
from rok_assistant.workers.quiz_sm import (
    ANSWER_NOT_ACCEPTED_REASON, QUIZ_ENTRY_MISSING_REASON,
    QUIZ_PARSE_FAILED_REASON, QUIZ_SCREEN_LOST_REASON, QuizStateMachine,
)
from rok_assistant.workers.runner import _ENV_FAIL_REASONS

W, H = 2664, 1200
MID = W // 2


def _blocks(*rows):
    return [(BBox(*r[:4]), r[4], r[5]) for r in rows]


# 真实帧的几何（活动页 / Q1 / Q2），只保留有判据意义的块
ACTIVITY = _blocks(
    (1160, 24, 1507, 114, "国士无双", 0.78),
    (1547, 388, 1688, 428, "习题演练", 0.73),
    (399, 431, 530, 468, "习题演练", 0.76),
    (687, 431, 817, 468, "习题演练", 0.74),
    (1585, 878, 1648, 915, "进入", 0.67),
)
Q1 = _blocks(
    (1092, 60, 1485, 116, "国士无双-复试", 0.75),
    (752, 393, 809, 436, "Q1", 0.63),
    (832, 394, 1197, 431, "统帅贝利撒留的昵称是？", 0.89),
    (823, 597, 1032, 631, "最后的罗马人", 0.81),
    (1554, 594, 1700, 634, "战火双刃", 0.79),
    (821, 756, 965, 793, "天选之豹", 0.74),
    (1557, 758, 1767, 791, "不的复兴者", 0.81),
    (1357, 916, 1608, 948, "答题剩余时间：9s", 0.82),
    (2245, 1151, 2316, 1192, "放弃", 0.67),
)
Q2 = _blocks(
    (1092, 60, 1484, 116, "国士无双-复试", 0.75),
    (749, 389, 813, 438, "Q2", 0.66),
    (834, 397, 1686, 429, "联盟领土界面中，领土资源最多能储存多长时间的产量？", 0.90),
    (818, 595, 936, 633, "24小时", 0.79),
    (1555, 595, 1672, 633, "36小时", 0.74),
    (817, 754, 937, 794, "12小时", 0.80),
    (1551, 754, 1671, 795, "18小时", 0.80),
    (1348, 914, 1616, 948, "答题剩余时间：15s", 0.86),
)
Q1_TEXT = parse_question(Q1, W).text
Q2_TEXT = parse_question(Q2, W).text

# 初试倒计时未结束的答题页（1920×1080 真实帧，2026-10-24 用户截图）：
# 「距开始还有 01:13:43」，进入按钮置灰。OPEN = 同一页去掉倒计时两块。
COUNTDOWN = _blocks(
    (806, 26, 1117, 103, "国士无双", 0.76),
    (1445, 350, 1508, 384, "初试", 0.66),
    (1411, 742, 1537, 772, "距开始还有", 0.75),
    (1420, 771, 1532, 798, "01:13:43", 0.84),
    (1443, 849, 1499, 882, "进入", 0.66),
)
OPEN = [b for b in COUNTDOWN if b[1] not in ("距开始还有", "01:13:43")]
ENTER_XY = ((1443 + 1499) // 2, (849 + 882) // 2)   # (1471, 865)

SHIPPED = [{"no": 1, "q": Q1_TEXT, "a": "最后的罗马人"}]


def _qset(n):
    """第 n 道题的块（几何照 Q1 真实帧）。

    头部沿用 Q1 fixture 的「国士无双-复试」写法——场次不再从画面文字
    识别（用户 2026-10-24 拍板：按星期几绑定），题目帧长什么样都行。
    """
    return _blocks(
        (1092, 60, 1485, 116, "国士无双-复试", 0.75),
        (752, 393, 809, 436, f"Q{n}", 0.63),
        (832, 394, 1197, 431, f"这是第{n}道测试题？", 0.89),
        (823, 597, 1032, 631, "选项甲", 0.81),
        (1554, 594, 1700, 634, "选项乙", 0.79),
        (821, 756, 965, 793, "选项丙", 0.74),
        (1557, 758, 1767, 791, "选项丁", 0.81),
        (2245, 1151, 2316, 1192, "放弃", 0.67),
    )


@pytest.fixture(autouse=True)
def _pin_daily_session(monkeypatch):
    """场次按星期几绑定（2026-10-24 用户拍板，不靠 OCR）：整套用例默认钉在
    「日常答题」，与真实星期几解耦——今天是周六，不钉的话现有用例会拿到初试的
    10 题上限和从紧补点预算而误判。考试场次的用例在内部自行覆盖。
    """
    monkeypatch.setattr(quiz_sm, "current_session", lambda: "daily")


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, dt=1.0):
        self.now += dt


class ScriptedHandle:
    """按顺序返回预置帧；用完后一直返回最后一帧。"""

    def __init__(self, frames):
        self._frames = list(frames)
        self._i = 0
        self.clicks = []

    def capture(self):
        frame = self._frames[min(self._i, len(self._frames) - 1)]
        self._i += 1
        return frame

    def click(self, x, y, anchor=None, rapid=False):
        self.clicks.append((int(x), int(y), anchor))

    def is_alive(self):
        return True


class FrameOcr:
    """帧对象 → OCR 块。同一帧永远读到同样的块（不按调用次数排队，稳）。"""

    def __init__(self, table):
        self._table = table

    def detect_text(self, frame):
        return list(self._table[id(frame)])


def _frame(blocks, green=None, w=W, h=H):
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    if green is not None:
        box = parse_question(blocks, w).options[green][1]
        frame[box.y1:box.y2, box.x1:box.x2] = (0, 200, 0)
    return frame


def _bank(tmp_path) -> QuizBank:
    shipped = tmp_path / "shipped.json"
    shipped.write_text(json.dumps(SHIPPED, ensure_ascii=False), encoding="utf-8")
    bank = QuizBank(shipped_path=shipped, learned_path=tmp_path / "learned.json")
    bank.load()
    return bank


def _make(tmp_path, script, *, bank=None, solver=None, **kw):
    """script: [(blocks, green_letter | None), ...] → (sm, handle, clock, bank)"""
    frames = [_frame(b, g) for b, g in script]
    table = {id(f): b for f, (b, _g) in zip(frames, script)}
    handle = ScriptedHandle(frames)
    clock = _Clock()
    bank = bank or _bank(tmp_path)
    solver = solver or Solver(bank, rng=random.Random(0))
    sm = QuizStateMachine(handle, FrameOcr(table), bank, solver,
                          clock=clock, sleeper=clock.advance,
                          rng=random.Random(0), **kw)
    return sm, handle, clock, bank


def _drive(sm, clock, max_steps=400, dt=1.0):
    for _ in range(max_steps):
        if sm.is_terminal():
            return
        clock.advance(dt)
        sm.step()
    raise AssertionError(f"没在 {max_steps} 步内结束（当前 {sm.current}）")


def _letter_of(blocks, click) -> str:
    """点在哪条选项上。"""
    q = parse_question(blocks, W)
    for letter, (_text, box) in q.options.items():
        if box.center() == (click[0], click[1]):
            return letter
    raise AssertionError(f"点击点 {click[:2]} 不落在任何选项上")


def test_one_round_answers_two_questions_then_ends_cleanly(tmp_path):
    script = [
        (Q1, None),        # NORMALIZE：已在答题页
        (Q1, None),        # OPEN_QUIZ：确认在答题页
        (Q1, None),        # READ：第 1 题
        (Q1, "A"),         # VERIFY：绿色 A（"最后的罗马人"）
        (Q2, None),        # ADVANCE：翻到第 2 题
        (Q2, None),        # READ：第 2 题
        (Q2, "B"),         # VERIFY：绿色 B
        (ACTIVITY, None),  # ADVANCE：读不出题 → 等 → 判本轮结束
    ]
    sm, handle, clock, bank = _make(tmp_path, script, round_cooldown_min=0.0)
    _drive(sm, clock)

    assert sm.current == "END"
    assert sm.fail_reason is None
    assert len(handle.clicks) == 2
    assert all(c[2] == "quiz_option" for c in handle.clicks)
    # 第 1 题：题库给 A（"最后的罗马人"；brief 原文误写 B）
    assert _letter_of(Q1, handle.clicks[0]) == "A"
    # 第 2 题：题库没有、LLM 关闭 → 随机（种子固定）
    expected = random.Random(0).choice(["A", "B", "C", "D"])
    assert _letter_of(Q2, handle.clicks[1]) == expected
    # 第 2 题学到的必须是绿色那项（B. 36小时）
    assert bank.lookup(Q2_TEXT).answer == "36小时"
    # 随包条目权威：第 1 题不会被学习覆盖
    assert bank.lookup(Q1_TEXT).answer == "最后的罗马人"


def test_round_ends_on_the_activity_page_without_failure(tmp_path):
    """活动结束后停在活动页（标题还是「国士无双」）：这是正常收尾，不是失败。"""
    sm, _handle, clock, _bank = _make(
        tmp_path, [(Q1, None), (Q1, None), (Q1, None), (Q1, "A"),
                   (ACTIVITY, None)], round_cooldown_min=0.0)
    _drive(sm, clock)
    assert sm.current == "END" and sm.fail_reason is None


def test_unparseable_question_before_any_answer_aborts_cleanly(tmp_path):
    sm, handle, clock, _bank = _make(
        tmp_path, [(Q1, None), (Q1, None), ([], None)], parse_retries=2)
    _drive(sm, clock)
    assert sm.current == "END"
    assert sm.fail_reason == QUIZ_PARSE_FAILED_REASON
    assert handle.clicks == []


def test_persistent_net_error_popup_aborts_cleanly_and_boundedly(tmp_path):
    """断网弹框点不掉：有限次尝试后按环境类原因收尾，绝不无限重试。

    回归点（task-7 review round 1）：READ 的断网分支原先在 `_read_waits += 1`
    之前 return，弹框一直被识别就会每秒点一次、永不写 fail_reason。
    """
    from rok_assistant.infra.anti_detection import (
        AntiDetectionConfig, HumanProfile,
    )

    class _AlwaysMatched:
        matched = True

        def __init__(self):
            self.calls = 0

        def recognize(self, frame):
            self.calls += 1
            return self

    rec = _AlwaysMatched()
    prof = HumanProfile(AntiDetectionConfig(debug_no_jitter=True))
    prof.jitter = lambda base: 0.0   # _click_net_error 内部的 1.5s 等待不真睡
    sm, handle, clock, _bank = _make(
        tmp_path, [(Q1, None), (Q1, None), ([], None)],
        recognizers={"net_error_confirm": rec}, parse_retries=2, human=prof)
    _drive(sm, clock)

    assert sm.current == "END"
    assert sm.fail_reason in (QUIZ_SCREEN_LOST_REASON, QUIZ_PARSE_FAILED_REASON)
    # 点击必须有界：每次重试最多 `_click_net_error` 内部的 3 次
    assert 0 < len(handle.clicks) <= 3
    assert all(c[2] is None for c in handle.clicks)   # 没有乱点选项
    assert rec.calls <= 4                             # 识别次数同样有界


def test_entry_missing_aborts_cleanly(tmp_path):
    """屏幕上既没有入口文字、entry_taps 又是空的：报入口缺失，绝不乱点。"""
    sm, handle, clock, _bank = _make(tmp_path, [(Q1, None), ([], None)])
    _drive(sm, clock)
    assert sm.current == "END"
    assert sm.fail_reason == QUIZ_ENTRY_MISSING_REASON
    assert handle.clicks == []


def test_entry_taps_are_used_when_no_text_entry_is_found(tmp_path):
    script = [(Q1, None), ([], None), (Q1, None)]
    sm, handle, clock, _bank = _make(tmp_path, script, entry_taps=[(100, 200)])
    for _ in range(40):
        clock.advance(1.0)
        sm.step()
    assert (100, 200, "quiz_entry_tap") in handle.clicks


# ---- VERIFY 无绿色时补点（2026-10-24 实机 0 分事故的修复） ----
#
# 实机复盘：每题只在 READ→ANSWER 点一次，且点击常发生在题目飞入动画中，
# 游戏吞掉动画期间的点击；机器人不补点，只能等倒计时归零自动结算——
# 10 题全部「未作答」，最终分数 0。修复：VERIFY 没看到绿色就原地补点
# （同一坐标，有限次数），仍不绿才按原逻辑走（不学这题、等自动翻页）。

def test_verify_without_green_retries_the_same_option(tmp_path):
    """没绿 → 回 ANSWER 再点同一个选项；补点次数有界。"""
    script = [(Q1, None)] * 40
    sm, handle, clock, _bank = _make(tmp_path, script)
    _drive(sm, clock, max_steps=400)
    option_clicks = [c for c in handle.clicks if c[2] == "quiz_option"]
    assert len(option_clicks) >= 2                     # 首点 + 至少一次补点
    assert len({(c[0], c[1]) for c in option_clicks}) == 1   # 都点在同一个选项
    assert sm.current == "END"
    assert sm.fail_reason == ANSWER_NOT_ACCEPTED_REASON   # 补点仍不翻页=真失败


def test_verify_green_does_not_retry(tmp_path):
    """看到绿色（答对/答错都会有正确项高亮）→ 不补点，直接学习。

    注意 ScriptedHandle 每次 capture 前进一帧：必须给足同一个题的帧，
    否则 VERIFY 会拿到下一题的帧（绿色涂在别的坐标上），测的就不是
    「有绿不补点」了。
    """
    script = [(Q1, "A")] * 8 + [(Q2, "A")] * 8
    sm, handle, clock, bank = _make(tmp_path, script)
    for _ in range(200):
        if sm.is_terminal():
            break
        clock.advance(1.0)
        sm.step()
    option_clicks = [c for c in handle.clicks if c[2] == "quiz_option"]
    assert len(option_clicks) == 2                     # 两题各点一次，没有补点


def test_open_quiz_waits_while_the_start_countdown_runs(tmp_path):
    """倒计时未结束：不点置灰的进入，原地轮询；时钟不推进就什么都不做。"""
    sm, handle, clock, _bank = _make(
        tmp_path, [(COUNTDOWN, None)] * 6 + [(OPEN, None), (Q1, None),
                                            (Q1, None), (Q1, "A"),
                                            (Q2, None), (Q2, None)],
        round_cooldown_min=0.0)
    for _ in range(10):
        if sm.current == "OPEN_QUIZ":
            break
        clock.advance(1.0)
        sm.step()
    assert sm.current == "OPEN_QUIZ"

    clock.advance(1.0)
    sm.step()                       # 第一次轮询：看到倒计时 → 等待
    assert handle.clicks == []      # 置灰的进入一下都没点
    assert sm.fail_reason is None   # 等待不是失败

    frozen = clock.now
    for _ in range(5):
        sm.step()                   # 时钟冻住：不重复截图、不点击
    assert clock.now == frozen and handle.clicks == []
    assert sm.current == "OPEN_QUIZ"

    clock.advance(20.0)
    sm.step()                       # 过一个轮询间隔：还在倒计时就继续等
    assert handle.clicks == []
    assert sm.current == "OPEN_QUIZ"


def test_open_quiz_clicks_enter_after_the_countdown_ends(tmp_path):
    """倒计时结束后：点进入 → 进答题页 → 开答。

    6 帧倒计时顺带证明等待**不消耗导航步数**（_NAV_MAX=4，早耗光就打不进去了）。
    """
    sm, handle, clock, _bank = _make(
        tmp_path, [(COUNTDOWN, None)] * 6 + [(OPEN, None), (Q1, None),
                                            (Q1, None), (Q1, "A"),
                                            (Q2, None), (Q2, None)],
        round_cooldown_min=0.0)
    for _ in range(300):
        if sm.current == "READ":
            break
        clock.advance(1.0)
        sm.step()
    assert sm.current == "READ"
    assert (*ENTER_XY, "quiz_entry") in handle.clicks


def test_screen_that_never_advances_is_a_real_failure(tmp_path):
    """点了选项后画面纹丝不动 → answer_not_accepted，且**计入连续失败**。"""
    sm, handle, clock, _bank = _make(
        tmp_path, [(Q1, None), (Q1, None), (Q1, None), (Q1, "A")])
    _drive(sm, clock)
    assert sm.current == "END"
    assert sm.fail_reason == ANSWER_NOT_ACCEPTED_REASON
    assert ANSWER_NOT_ACCEPTED_REASON not in _ENV_FAIL_REASONS
    assert len(handle.clicks) == 1


def test_env_reasons_are_not_counted_as_failures():
    for reason in (QUIZ_ENTRY_MISSING_REASON, QUIZ_SCREEN_LOST_REASON,
                   QUIZ_PARSE_FAILED_REASON):
        assert reason in _ENV_FAIL_REASONS


def test_cooldown_is_non_blocking_and_ends_after_the_window(tmp_path):
    """冷却窗口**不 sleep**：Stop 要能在 2s 内 join 上（与宝石 WAIT 同套路）。"""
    sm, _handle, clock, _bank = _make(
        tmp_path, [(Q1, None), (Q1, None), (Q1, None), (Q1, "A"),
                   (ACTIVITY, None)], round_cooldown_min=10.0)
    for _ in range(200):
        if sm.current == "COOLDOWN":
            break
        clock.advance(1.0)
        sm.step()
    assert sm.current == "COOLDOWN"

    frozen = clock.now
    for _ in range(5):
        sm.step()                       # 不推进时钟
    assert sm.current == "COOLDOWN"
    assert clock.now == frozen          # 没有 sleep

    clock.advance(601)
    sm.step()
    assert sm.current == "END" and sm.fail_reason is None


def test_auto_click_false_only_logs_and_ends_the_round(tmp_path):
    sm, handle, clock, bank = _make(
        tmp_path, [(Q1, None)], auto_click=False, round_cooldown_min=0.0)
    _drive(sm, clock)
    assert handle.clicks == []
    assert sm.current == "END" and sm.fail_reason is None
    assert bank.size == 1               # 没点、没验、没学


# ---- 场次绑定与题量上限（用户 2026-10-24 拍板：按星期几，不靠 OCR） ----
#
# 初试（周六）10 题、终试（周日）20 题，都是固定时间入场、单题限时；
# 周一至周五的日常答题任意时间可答、无单题时限、不限题量。
# 场次在每轮开始（_reset_nav）按当天星期几绑定，与画面文字无关。

def test_prelim_session_caps_the_round_at_ten_questions(tmp_path, monkeypatch):
    """周六（初试）→ 单轮答满 10 题收轮；不读画面上的考试名。"""
    monkeypatch.setattr(quiz_sm, "current_session", lambda: "prelim")
    qs = [_qset(n) for n in range(1, 12)]     # Q1..Q11
    script = [(qs[0], None), (qs[0], None)]   # NORMALIZE / OPEN_QUIZ
    for i in range(10):
        script += [(qs[i], None),        # READ：第 i+1 题
                   (qs[i], "A"),         # VERIFY：有绿色，不补点
                   (qs[i + 1], None)]    # ADVANCE：翻到下一题
    sm, handle, clock, _bank = _make(tmp_path, script, round_cooldown_min=0.0)
    _drive(sm, clock)

    assert sm.current == "END"
    assert sm.fail_reason is None
    assert sm._session == "prelim"
    assert sm._answered == 10              # 初试固定 10 题


def test_final_session_uses_the_twenty_question_limit(tmp_path, monkeypatch):
    """周日（终试）→ 20 题上限（不是初试的 10，也没有配置兜底）。"""
    monkeypatch.setattr(quiz_sm, "current_session", lambda: "final")
    sm, _handle, _clock, _bank = _make(tmp_path, [(Q1, None), (Q1, None)])
    sm._reset_nav({})
    assert sm._session == "final"
    assert sm._question_cap() == 20


def test_daily_session_has_no_question_cap(tmp_path, monkeypatch):
    """日常答题（周一至周五）→ 不限题量，答到活动结束算一轮。"""
    monkeypatch.setattr(quiz_sm, "current_session", lambda: "daily")
    sm, _handle, _clock, _bank = _make(tmp_path, [(Q1, None), (Q1, None)])
    sm._reset_nav({})
    assert sm._session == "daily"
    assert sm._question_cap() is None


def test_session_is_bound_at_round_start_and_rebound_between_rounds(
        tmp_path, monkeypatch):
    """场次在每轮开始（_reset_nav）绑定；新一轮重新绑，不沿用上一轮。"""
    monkeypatch.setattr(quiz_sm, "current_session", lambda: "prelim")
    sm, _handle, _clock, _bank = _make(tmp_path, [(Q1, None), (Q1, None)])
    sm._reset_nav({})
    assert sm._session == "prelim"
    monkeypatch.setattr(quiz_sm, "current_session", lambda: "daily")
    sm._reset_nav({})
    assert sm._session == "daily"


def test_retry_budget_is_tight_in_timed_exams_and_patient_in_practice(
        tmp_path, monkeypatch):
    """初试/终试有单题限时：补点 2 次；日常答题无时限：补点 4 次。"""
    monkeypatch.setattr(quiz_sm, "current_session", lambda: "prelim")
    exam_sm, exam_handle, clock, _b = _make(tmp_path, [(_qset(1), None)] * 40)
    _drive(exam_sm, clock, max_steps=400)
    exam_clicks = [c for c in exam_handle.clicks if c[2] == "quiz_option"]
    assert len(exam_clicks) == 3                    # 首点 + 2 次补点

    monkeypatch.setattr(quiz_sm, "current_session", lambda: "daily")
    practice_sm, practice_handle, clock2, _b2 = _make(tmp_path, [(Q1, None)] * 40)
    _drive(practice_sm, clock2, max_steps=400)
    practice_clicks = [c for c in practice_handle.clicks
                       if c[2] == "quiz_option"]
    assert len(practice_clicks) == 5                # 首点 + 4 次补点
