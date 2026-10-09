from __future__ import annotations
import time
from typing import Callable, Union
from ..core.recognizer import RecognizeResult
from ..infra.anti_detection import AntiDetectionConfig, HumanProfile
from ..infra.logger import get_logger
from dataclasses import dataclass, field

logger = get_logger(__name__)


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
    def __init__(self, initial: str, human: HumanProfile | None = None):
        self._transitions: list[Transition] = []
        self.current = initial
        self.history: list[str] = [initial]
        self._ctx: dict = {}
        self.last_image = None  # last captured frame; kept for failure screenshots
        # 默认 profile 是确定性的（debug_no_jitter）：直接构造状态机
        # （测试、库用法）时行为与改动前逐字相同；生产路径由 runtime 注入
        # 配置驱动的 profile。
        self._human = human if human is not None else HumanProfile(
            AntiDetectionConfig(debug_no_jitter=True))
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

    def _click_result(self, r: RecognizeResult, rapid: bool = False) -> bool:
        x, y = r.bbox.center()
        self._handle.click(x, y, anchor=r.recognizer_id, rapid=rapid)
        return True

    def _click_xy(self, x: float, y: float, anchor: str | None = None) -> bool:
        """按绝对像素点一点（反检测抖动仍走 handle.click）。

        用于「实测钉死的固定位置」——预设槽列就是这种：44 帧逐像素实测
        `cy=474+82*(N-1)`、`cx=1655` 零漂移。模板腿失配（_click 空操作）时
        用它兜底，比让整轮空过强。`anchor` 让散布 σ 能按目标收紧。
        """
        self._handle.click(int(x), int(y), anchor=anchor)
        return True

    def _click(self, rec_id: str, rapid: bool = False) -> bool:
        r = self._find(rec_id)
        if r is None:
            return False
        return self._click_result(r, rapid=rapid)

    def _pause(self, base: float | None) -> float:
        """轮询间隔：调用方给了基准就抖动基准，没给就用 profile 的轮询节奏。"""
        return self._human.poll_interval() if base is None else self._human.jitter(base)

    def _find_retry(self, rec_id: str, attempts: int = 3,
                    interval: float | None = None) -> RecognizeResult | None:
        attempts = self._human.retry_attempts(attempts)
        for i in range(attempts):
            r = self._find(rec_id)
            if r is not None:
                return r
            if i < attempts - 1:
                time.sleep(self._pause(interval))
        return None

    def _click_retry(self, rec_id: str, attempts: int = 3,
                     interval: float | None = None) -> bool:
        r = self._find_retry(rec_id, attempts=attempts, interval=interval)
        if r is None:
            return False
        return self._click_result(r)

    def _wait_for_result(self, rec_id: str, timeout: float = 10.0,
                         interval: float | None = None) -> RecognizeResult | None:
        deadline = time.time() + timeout
        while True:
            r = self._find(rec_id)
            if r is not None:
                return r
            if time.time() >= deadline:
                return None
            pause = self._pause(interval)
            if pause > 0:
                time.sleep(min(pause, max(0.0, deadline - time.time())))

    def _wait_for(self, rec_id: str, timeout: float = 10.0,
                  interval: float | None = None) -> bool:
        return self._wait_for_result(rec_id, timeout=timeout, interval=interval) is not None

    def _wait_click(self, rec_id: str, timeout: float = 15.0,
                    interval: float | None = None) -> bool:
        r = self._wait_for_result(rec_id, timeout=timeout, interval=interval)
        if r is None:
            return False
        return self._click_result(r)

    # 行动力补充弹窗按钮（1920x1080 实机测量，2026-09-18 run9/run10 截图）：
    _AP_CLAIM_DAILY = (1448, 379)   # 每日免费 500「领取」（每日 1 次，有则白拿）
    _AP_USE_ROW2 = (1447, 570)      # 第二行「使用」：未领每日时=紧急50、
    #                                  领过后（该行上移）=初级100，都便宜够用
    _AP_DIALOG_X = (1638, 120)      # 弹窗右上角 X

    # 一次补体力最多吃几口道具（2026-10-09 用户要求「吃到没道具为止」）。
    # 上限是**有界**的：本项目观测不到「道具已吃完」这个信号——弹窗在体力
    # 已够时也保持打开（2026-09-18 run10 实机教训），而道具行的空/灰没有
    # 模板可判。所以这里只做到「一次多吃几口」，把「吃到没道具」交给上层
    # 的有界外循环（leader_sm._launch 的 _AP_REFILL_MAX）。实机确认弹窗
    # 长什么样之后再收紧（spec §7 未决项）。
    _AP_EAT_MAX = 3

    def _refill_ap(self) -> bool:
        """行动力不足弹窗：先领每日免费，再反复点第二行「使用」吃道具
        （最多 `_AP_EAT_MAX` 口，弹窗中途关掉就停），最后关弹窗。
        返回弹窗是否已关闭。

        2026-10-09：原实现只吃一口就走 `_close_ap_dialog`，一次补的体力
        常常不够一轮集结的消耗——`_launch` 里那圈「补一次→点行军→又弹」
        的有界重试正是这个不足的证据。现在一次多补几口。
        """
        if self._find("ap_refill") is None:
            return False
        self._handle.click(*self._AP_CLAIM_DAILY)
        time.sleep(self._human.jitter(1.5))
        for _ in range(self._AP_EAT_MAX):
            if self._find("ap_refill") is None:
                break
            self._handle.click(*self._AP_USE_ROW2)
            time.sleep(self._human.jitter(1.5))
        return self._close_ap_dialog()

    def _close_ap_dialog(self) -> bool:
        """关行动力补充弹窗：X 点击可能被领取/使用的 toast 动画吞掉
        （2026-09-18 run10 实机：单次 X 后弹窗残留，mumu0 卡死 LAUNCH
        六连异常），点一次确认一次，最多 4 次。"""
        for _ in range(4):
            if self._find("ap_refill") is None:
                return True
            self._handle.click(*self._AP_DIALOG_X)
            time.sleep(self._human.jitter(1.2))
        return self._find("ap_refill") is None

    # 断网弹框「确定」按钮中心（2026-10-09 实机截图实测 bbox
    # (779,666)-(1142,757)，中心 (960,711)）
    _NET_ERROR_CONFIRM_XY = (960, 711)
    _NET_ERROR_MAX_CLICKS = 3

    def _click_net_error(self) -> bool:
        """点掉断网弹框（「网络不稳定，连接已断开」）的「确定」，返回是否
        点过。

        有界循环：点一次确认一次，弹框还在才补点（点「确定」会触发重连，
        画面可能停在加载态 —— 那是**弹框已消失**的正常表现，不能当成没点
        掉而死循环）。归一化里紧跟一段 `_wait_for(地图标志)` 兜住重连窗口。
        """
        clicked = False
        for _ in range(self._NET_ERROR_MAX_CLICKS):
            if self._find("net_error_confirm") is None:
                break
            self._handle.click(*self._NET_ERROR_CONFIRM_XY)
            clicked = True
            logger.warning("检测到断网弹框，点击「确定」重连（第 %s 次）",
                           _ + 1)
            time.sleep(self._human.jitter(1.5))
        return clicked
