from __future__ import annotations
import threading
from datetime import datetime
from pathlib import Path

from ..infra.logger import get_logger

logger = get_logger(__name__)


class WorkerRunner:
    """每角色一个线程：循环 step 状态机、发布状态、异常截图、终态冷却重建。

    状态经 EventBus 的 "status_update" 发布（仅变化时）：
    payload = {"instance_id", "char_id", "char_name", "state", "ts"}。
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
                 screenshot_dir: Path | None = None):
        self.instance_id = instance_id
        self.char_id = char_id
        self.char_name = char_name
        self._sm_factory = sm_factory
        self.sm = sm_factory()
        self._handle = handle_source
        self._bus = event_bus
        self._poll = poll_interval
        self._cooldown = restart_cooldown
        self._error_backoff = error_backoff
        self._pause_poll = pause_poll
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else Path("recordings")
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
                    self._set_status("cooldown")
                    self._stop_event.wait(self._cooldown)
                    if self._stop_event.is_set():
                        break
                    self.sm = self._sm_factory()   # 冷却后重建，进入下一轮
                    self._set_status(self.sm.current)
                    continue
                self.sm.step()
                self._set_status(self.sm.current)
            except Exception as e:   # 任何异常：截图 + 记录 + 退避后继续（不杀线程）
                logger.exception("worker %s/%s step failed: %s",
                                 self.instance_id, self.char_id, e)
                self._save_failure_screenshot()
                self._set_status("error")
                self._stop_event.wait(self._error_backoff)
                continue   # 退避即全部恢复延时，不再叠加 poll 等待
            self._stop_event.wait(self._poll)

    def _set_status(self, state: str) -> None:
        if state == self._status:
            return
        self._status = state
        logger.info("worker %s/%s -> %s", self.instance_id, self.char_id, state)
        if self._bus:
            self._bus.publish("status_update", {
                "instance_id": self.instance_id, "char_id": self.char_id,
                "char_name": self.char_name, "state": state,
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
