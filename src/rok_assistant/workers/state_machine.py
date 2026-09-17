from __future__ import annotations
import time
from typing import Callable, Union
from ..core.recognizer import RecognizeResult
from dataclasses import dataclass, field

@dataclass
class State:
    name: str

@dataclass
class Transition:
    from_state: str
    to_state: str
    action: Union[str, Callable]
    guard: Callable | None = None

class StateMachine:
    def __init__(self, initial: str):
        self._transitions: list[Transition] = []
        self.current = initial
        self.history: list[str] = [initial]
        self._ctx: dict = {}
        self.last_image = None  # last captured frame; kept for failure screenshots
        self._setup()

    def _setup(self) -> None:
        raise NotImplementedError

    @property
    def fail_reason(self) -> str | None:
        """本轮失败原因（give-up/exhausted 出口写入 ctx['fail_reason']）；
        未失败为 None。WorkerRunner 在 status_update payload 中带出。"""
        return self._ctx.get("fail_reason")

    def add_transition(self, from_state: str, to_state: str,
                       action: Union[str, Callable], guard: Callable | None = None) -> None:
        self._transitions.append(Transition(from_state, to_state, action, guard))

    def step(self, context: dict | None = None) -> None:
        if context is None:
            context = self._ctx
        else:
            self._ctx = context
        for t in self._transitions:
            if t.from_state != self.current:
                continue
            if t.guard and not t.guard(context):
                continue
            if callable(t.action):
                t.action(context)
            # else: action is a string label, nothing to invoke
            self.current = t.to_state
            self.history.append(self.current)
            return
        # No transition matched - stay in current state

    # ---- shared recognition/click helpers (subclasses have _handle/_rec) ----
    def _find(self, rec_id: str) -> RecognizeResult | None:
        rec = self._rec.get(rec_id)
        if rec is None:
            return None
        img = self._handle.capture()
        self.last_image = img
        r = rec.recognize(img)
        return r if r.matched else None

    def _click_result(self, r: RecognizeResult) -> bool:
        x, y = r.bbox.center()
        self._handle.click(x, y)
        return True

    def _click(self, rec_id: str) -> bool:
        r = self._find(rec_id)
        if r is None:
            return False
        return self._click_result(r)

    def _find_retry(self, rec_id: str, attempts: int = 3,
                    interval: float = 1.0) -> RecognizeResult | None:
        for i in range(attempts):
            r = self._find(rec_id)
            if r is not None:
                return r
            if i < attempts - 1 and interval > 0:
                time.sleep(interval)
        return None

    def _click_retry(self, rec_id: str, attempts: int = 3, interval: float = 1.0) -> bool:
        r = self._find_retry(rec_id, attempts=attempts, interval=interval)
        if r is None:
            return False
        return self._click_result(r)

    def _wait_for_result(self, rec_id: str, timeout: float = 10.0,
                         interval: float = 1.0) -> RecognizeResult | None:
        deadline = time.time() + timeout
        while True:
            r = self._find(rec_id)
            if r is not None:
                return r
            if time.time() >= deadline:
                return None
            if interval > 0:
                time.sleep(min(interval, max(0.0, deadline - time.time())))

    def _wait_for(self, rec_id: str, timeout: float = 10.0, interval: float = 1.0) -> bool:
        return self._wait_for_result(rec_id, timeout=timeout, interval=interval) is not None

    def _wait_click(self, rec_id: str, timeout: float = 15.0, interval: float = 1.0) -> bool:
        r = self._wait_for_result(rec_id, timeout=timeout, interval=interval)
        if r is None:
            return False
        return self._click_result(r)

    # 行动力补充弹窗按钮（1920x1080 实机测量，2026-09-18 run9/run10 截图）：
    _AP_CLAIM_DAILY = (1448, 379)   # 每日免费 500「领取」（每日 1 次，有则白拿）
    _AP_USE_ROW2 = (1447, 570)      # 第二行「使用」：未领每日时=紧急50、
    #                                  领过后（该行上移）=初级100，都便宜够用
    _AP_DIALOG_X = (1638, 120)      # 弹窗右上角 X

    def _refill_ap(self) -> bool:
        """行动力不足弹窗（行军点击时 AP < 消耗，2026-09-18 实机 run9
        实锤：加入集结的行军同样耗行动力，140/150 自然上限跑不满 10 轮
        目标，历次「连续 3 轮失败」停机根因即此）。先领每日免费 500，再
        点第二行「使用」补一点，最后关弹窗 —— 实机 run10 教训：用完道具
        弹窗不会自动关（体力已够也开着），X 关一次可能被 toast 动画吞掉，
        必须循环确认。返回弹窗是否已关闭。"""
        if self._find("ap_refill") is None:
            return False
        self._handle.click(*self._AP_CLAIM_DAILY)
        time.sleep(1.5)
        if self._find("ap_refill") is not None:
            self._handle.click(*self._AP_USE_ROW2)
            time.sleep(1.5)
        return self._close_ap_dialog()

    def _close_ap_dialog(self) -> bool:
        """关行动力补充弹窗：X 点击可能被领取/使用的 toast 动画吞掉
        （2026-09-18 run10 实机：单次 X 后弹窗残留，mumu0 卡死 LAUNCH
        六连异常），点一次确认一次，最多 4 次。"""
        for _ in range(4):
            if self._find("ap_refill") is None:
                return True
            self._handle.click(*self._AP_DIALOG_X)
            time.sleep(1.2)
        return self._find("ap_refill") is None
