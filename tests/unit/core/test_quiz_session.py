"""场次绑定：按本地日期（星期几）决定场次与固定题量。

用户 2026-10-24 拍板：场次**不按 OCR 识别**，直接按时间绑定——
周一至周五日常答题（不限题量）、周六初试（10 题）、周日终试（20 题）。
"""
from datetime import date, datetime

from rok_assistant.core.quiz.session import (
    SESSION_DAILY, SESSION_FINAL, SESSION_LABELS, SESSION_PRELIM,
    SESSION_QUESTION_LIMITS, current_session, session_for_date,
)

# 写死真实日期（2026-10-19 是周一 …… 2026-10-25 是周日）：
# 用具体日期而不是 weekday() 循环，防止「周一到周五」的映射写反。
MON = date(2026, 10, 19)
TUE = date(2026, 10, 20)
WED = date(2026, 10, 21)
THU = date(2026, 10, 22)
FRI = date(2026, 10, 23)
SAT = date(2026, 10, 24)
SUN = date(2026, 10, 25)


def test_weekday_binds_the_session():
    """周一至周五 = 日常答题，周六 = 初试，周日 = 终试。"""
    for d in (MON, TUE, WED, THU, FRI):
        assert session_for_date(d) == SESSION_DAILY
    assert session_for_date(SAT) == SESSION_PRELIM
    assert session_for_date(SUN) == SESSION_FINAL


def test_current_session_accepts_an_explicit_now():
    """给了 now 就按 now 的日期算（时刻不影响场次）。"""
    assert current_session(datetime(2026, 10, 25, 13, 0)) == SESSION_FINAL
    assert current_session(datetime(2026, 10, 24, 19, 30)) == SESSION_PRELIM
    assert current_session(datetime(2026, 10, 23, 23, 59)) == SESSION_DAILY


def test_current_session_defaults_to_today():
    """不传 now 就是今天——与 session_for_date(date.today()) 一致。"""
    assert current_session() == session_for_date(date.today())


def test_question_limits_are_fixed_per_session():
    """题量按场次固定：日常不限（None）、初试 10、终试 20。"""
    assert SESSION_QUESTION_LIMITS[SESSION_DAILY] is None
    assert SESSION_QUESTION_LIMITS[SESSION_PRELIM] == 10
    assert SESSION_QUESTION_LIMITS[SESSION_FINAL] == 20


def test_labels_cover_every_session():
    """每个场次都要有中文名（日志/GUI 要用）。"""
    assert set(SESSION_LABELS) == set(SESSION_QUESTION_LIMITS)
    assert SESSION_LABELS[SESSION_PRELIM] == "初试"
    assert SESSION_LABELS[SESSION_FINAL] == "终试"
