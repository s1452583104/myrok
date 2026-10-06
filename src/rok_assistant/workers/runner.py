from __future__ import annotations
import threading
from datetime import datetime
from pathlib import Path

from ..infra.logger import get_logger
from ..infra.anti_detection import AntiDetectionConfig, HumanProfile

logger = get_logger(__name__)

# 状态 → 中文提示（日志用）。未收录的状态如实打印原值，新增状态无需注册。
_STATE_ZH = {
    # Runner 自身生命周期（小写）
    "idle": "已启动，状态机就绪",
    "paused": "已暂停：模拟器窗口失联，等待恢复",
    "cooldown": "本轮结束，冷却后自动开始下一轮",
    "error": "出现异常，已截图记录，退避后自动重试",
    # 通用 SM 状态
    "IDLE": "待机",
    "END": "本轮结束",
    # 车头阶段（LEADER: 前缀）
    "LEADER:IDLE": "车头·待机",
    "LEADER:NORMALIZE": "车头·回到地图视图",
    "LEADER:SEARCH_FORTRESS": "车头·打开搜索面板",
    "LEADER:SELECT_LEVEL": "车头·设置城寨等级",
    "LEADER:CONFIRM_SEARCH": "车头·点击搜索",
    "LEADER:CHECK_RESULT": "车头·检查搜索结果",
    "LEADER:CLICK_RED_RALLY": "车头·点击城寨红色集结按钮",
    "LEADER:VERIFY_UNLOCKED": "车头·确认城寨未被锁定",
    "LEADER:SELECT_RALLY_TIME": "车头·发起集结进攻",
    "LEADER:FORM_TROOP": "车头·创建部队（预设槽+兵种）",
    "LEADER:LAUNCH": "车头·点击行军，集结出发",
    "LEADER:WAIT_MEMBERS": "车头·等待成员填兵",
    # 成员阶段（MEMBER: 前缀）
    "MEMBER:IDLE": "成员·待机",
    "MEMBER:WAIT_LAUNCH_EVENT": "成员·等待车头的发车事件",
    "MEMBER:SWITCH_TO_SELF": "成员·切换到自己视图",
    "MEMBER:NORMALIZE": "成员·回到地图视图",
    "MEMBER:OPEN_ALLIANCE": "成员·打开联盟面板",
    "MEMBER:OPEN_WAR": "成员·打开联盟战争列表",
    "MEMBER:SORT_BY_NEAREST": "成员·按距离排序集结列表",
    "MEMBER:FILTER": "成员·筛选可加入的集结",
    "MEMBER:CLICK_JOIN": "成员·点击加入集结",
    "MEMBER:VERIFY_JOINED": "成员·确认加入结果",
    "MEMBER:JOIN_CHECKED": "成员·加入校验完成",
    "MEMBER:FORM_TROOP": "成员·创建部队填兵",
    "MEMBER:LAUNCH": "成员·点击行军，填兵出发",
    "MEMBER:SWITCH_BACK": "成员·返回自己城市",
    # either 角色返城等待
    "WAIT_RETURN": "等待集结部队返城",
    # Runner 结束态
    "done": "已达停止条件，收工",
}

def _zh(state: str) -> str:
    return _STATE_ZH.get(state, state)


class WorkerRunner:
    """每角色一个线程：循环 step 状态机、发布状态、异常截图、终态冷却重建。

    状态经 EventBus 的 "status_update" 发布（仅变化时）：
    payload = {"instance_id", "char_id", "char_name", "state", "ts",
    "fail_reason"}。fail_reason 取自 sm.fail_reason（give-up/exhausted
    出口写入，未失败为 None）——现有消费方只读各自关心的键，新增键向后兼容。
    state 值域约定：小写 = Runner 自身生命周期状态（"idle" 哨兵、
    "paused"/"cooldown"/"error"）；大写 = SM 当前状态（如 "IDLE"/"END"），
    如实转发。首轮发布的大写 "IDLE" 表示工作线程已启动且 SM 就绪。
    Task 8 的 GUI 映射负责大小写呈现。

    线程安全：status / reached_terminal / sm 均为跨线程读的普通属性
    （CPython 下属性读写原子，安全）。sm 会被工作线程在终态冷却后整体
    替换 —— 外部（RuntimeCoordinator）读 runner.sm.current / 调
    on_rally_launched 是无锁快照读，极小概率读到刚重建的新 SM，可接受
    （事件路由由 Task 8 在 IDLE/WAIT_LAUNCH_EVENT 状态判断）。

    建议调用方显式传入 screenshot_dir；默认的 CWD 相对 "recordings"
    仅为兜底便利。
    """

    def __init__(self, instance_id: str, char_id: str, char_name: str,
                 sm_factory, handle_source, event_bus=None,
                 poll_interval: float = 2.0, restart_cooldown: float = 30.0,
                 error_backoff: float = 10.0, pause_poll: float = 5.0,
                 screenshot_dir: Path | None = None,
                 max_rounds: int | None = None,
                 max_consecutive_failures: int = 3,
                 human: HumanProfile | None = None):
        self.instance_id = instance_id
        self.char_id = char_id
        self.char_name = char_name
        self._sm_factory = sm_factory
        self.sm = sm_factory()
        self._handle = handle_source
        self._bus = event_bus
        self._poll = poll_interval
        self._cooldown = restart_cooldown
        # 冷却/轮询等待经此 profile 抖动（反检测：精确恒定的间隔是机器特征）。
        # 未注入时用确定性 profile，行为与改动前逐字相同。
        self._human = human if human is not None else HumanProfile(
            AntiDetectionConfig(debug_no_jitter=True))
        self._error_backoff = error_backoff
        self._pause_poll = pause_poll
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else Path("recordings")
        # 轮次与停止条件（2026-09-11 验收目标：跑满 N 轮或体力耗尽即收工）
        self._max_rounds = max_rounds
        self._max_fail_streak = max_consecutive_failures
        self._max_error_streak = max_consecutive_failures * 2
        self.rounds_done = 0          # 已完成的轮数（成功+失败都算）
        self._fail_streak = 0         # 连续失败终态计数（成功清零）
        self._error_streak = 0        # 连续 step 异常计数（成功 step 清零）
        self.stopped_reason: str | None = None   # 非 None = 主循环已退出
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "idle"
        self._reached_terminal = False

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return   # 重复 start 忽略，防止双线程驱同一状态机
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"worker:{self.instance_id}:{self.char_id}")
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ---- 查询 ----
    @property
    def status(self) -> str:
        return self._status

    @property
    def last_frame(self):
        return getattr(self.sm, "last_image", None)

    def reached_terminal(self) -> bool:
        return self._reached_terminal

    # ---- 主循环 ----
    def _run(self) -> None:
        # 主循环永不主动退出（除非 stop）：任何异常都被捕获，线程不死。
        while not self._stop_event.is_set():
            try:
                if not self._handle.is_alive():
                    self._set_status("paused")   # §3.5：窗口消失 → 暂停
                    self._stop_event.wait(self._pause_poll)
                    continue
                if self.sm.is_terminal():
                    self._reached_terminal = True
                    reason = getattr(self.sm, "fail_reason", None)
                    self.rounds_done += 1
                    if reason:
                        self._fail_streak += 1
                        logger.warning("worker %s/%s[%s] 第 %s 轮失败结束：%s"
                                       "（连续失败 %s/%s）",
                                       self.instance_id, self.char_id,
                                       self.char_name, self.rounds_done, reason,
                                       self._fail_streak, self._max_fail_streak)
                    else:
                        self._fail_streak = 0
                        logger.info("worker %s/%s[%s] 第 %s/%s 轮完成",
                                    self.instance_id, self.char_id,
                                    self.char_name, self.rounds_done,
                                    self._max_rounds)
                    stop = self._check_stop_conditions()
                    if stop:
                        break
                    self._set_status("cooldown")
                    self._stop_event.wait(self._human.jitter(self._cooldown))
                    if self._stop_event.is_set():
                        break
                    self.sm = self._sm_factory()   # 冷却后重建，进入下一轮
                    self._set_status(self.sm.current)
                    continue
                self.sm.step()
                self._error_streak = 0
                self._set_status(self.sm.current)
            except Exception as e:   # 任何异常：截图 + 记录 + 退避后继续（不杀线程）
                logger.exception("worker %s/%s step failed: %s",
                                 self.instance_id, self.char_id, e)
                self._save_failure_screenshot()
                self._set_status("error")
                self._error_streak += 1
                if self._error_streak >= self._max_error_streak:
                    self.stopped_reason = (
                        f"连续 {self._error_streak} 次 step 异常（疑似体力耗尽"
                        "或环境异常），停止")
                    logger.warning("worker %s/%s[%s] %s", self.instance_id,
                                   self.char_id, self.char_name,
                                   self.stopped_reason)
                    self._set_status("done")
                    break
                self._stop_event.wait(self._error_backoff)
                continue   # 退避即全部恢复延时，不再叠加 poll 等待
            self._stop_event.wait(self._human.jitter(self._poll))

    def _check_stop_conditions(self) -> bool:
        """终态后的停止条件检查（2026-09-11 验收目标：跑满 N 轮或连续失败
        即收工）。命中时置 stopped_reason、发 "done" 状态并让主循环退出。"""
        if self._max_rounds is not None and self.rounds_done >= self._max_rounds:
            self.stopped_reason = f"已完成 {self.rounds_done} 轮，达到轮数上限"
        elif self._fail_streak >= self._max_fail_streak:
            self.stopped_reason = (f"连续 {self._fail_streak} 轮失败"
                                   "（疑似体力耗尽或环境异常），停止")
        if self.stopped_reason is None:
            return False
        logger.info("worker %s/%s[%s] %s", self.instance_id, self.char_id,
                    self.char_name, self.stopped_reason)
        self._set_status("done")
        return True

    def _set_status(self, state: str) -> None:
        if state == self._status:
            return
        self._status = state
        logger.info("worker %s/%s[%s] -> %s", self.instance_id, self.char_id,
                    self.char_name, _zh(state))
        if self._bus:
            self._bus.publish("status_update", {
                "instance_id": self.instance_id, "char_id": self.char_id,
                "char_name": self.char_name, "state": state,
                "fail_reason": getattr(self.sm, "fail_reason", None),
                "ts": datetime.now().isoformat(timespec="seconds"),
            })

    def _save_failure_screenshot(self) -> None:
        img = self.last_frame
        if img is None:
            return
        try:
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)
            name = f"failure_{self.instance_id}_{self.char_id}_{datetime.now():%Y%m%d_%H%M%S}.png"
            path = self._screenshot_dir / name
            # Windows 下 cv2.imwrite 对非 ASCII 路径静默返回 False，
            # 改用 imencode + write_bytes 保证写入可靠。
            import cv2
            ok, buf = cv2.imencode(".png", img)
            if not ok:
                logger.error("失败截图编码出错: %s", path)
                return
            path.write_bytes(buf.tobytes())
        except Exception:
            logger.exception("保存失败截图出错")
