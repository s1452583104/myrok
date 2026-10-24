"""场次绑定：按本地日期（星期几）决定当天是什么场次、固定多少题。

用户 2026-10-24 拍板的两条简化：

1. **场次不按 OCR 识别**——直接按时间绑定：周一至周五日常答题、
   周六初试、周日终试。画面上的「初试/终试」字样可以认错（弹窗、
   活动主页两个考试名并存），星期几不会。
2. **题量不进配置**——按场次固定：日常答题不限量（答到活动结束算
   一轮）、初试 10 题、终试 20 题。

入场时刻（初试 13:00/19:00 等）仍由游戏内倒计时门禁把关
（`screen.entry_countdown_active`），本模块不编排入场时间。
"""
from __future__ import annotations

from datetime import date, datetime

SESSION_DAILY = "daily"
SESSION_PRELIM = "prelim"
SESSION_FINAL = "final"

SESSION_LABELS = {SESSION_DAILY: "日常答题", SESSION_PRELIM: "初试",
                  SESSION_FINAL: "终试"}

#: 各场次固定题量；None = 不限量（答到活动结束为止）。
SESSION_QUESTION_LIMITS: dict[str, int | None] = {
    SESSION_DAILY: None,
    SESSION_PRELIM: 10,
    SESSION_FINAL: 20,
}

# weekday() → 场次：周六(5)=初试、周日(6)=终试，其余全是日常答题。
_WEEKDAY_SESSIONS = {5: SESSION_PRELIM, 6: SESSION_FINAL}


def session_for_date(d: date) -> str:
    """按日期返回场次类型：周一至周五 daily，周六 prelim，周日 final。"""
    return _WEEKDAY_SESSIONS.get(d.weekday(), SESSION_DAILY)


def current_session(now: datetime | None = None) -> str:
    """当前场次。`now` 可注入（测试/回放用）；默认取本机此刻。"""
    return session_for_date((now or datetime.now()).date())
