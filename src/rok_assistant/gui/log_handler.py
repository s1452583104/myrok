"""把日志行按「属于哪个角色」投递到 GUI 卡片。

归属靠 **worker 线程名**（`runner.py:117` 命名成
`worker:<instance_id>:<char_id>`），所以 worker 侧一行日志调用都不用改。
解析不出来的（主线程的配置加载、连不上实例等）返回空串，由调用方
决定去向（当前是状态栏）。
"""
from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal

_WORKER_PREFIX = "worker:"


def char_id_from_thread_name(name: str) -> str:
    """`worker:<instance_id>:<char_id>` -> `<char_id>`；其它一律返回 ""。

    char_id 自身可能含冒号，所以只切前两段，剩余整体返回。
    """
    if not name or not name.startswith(_WORKER_PREFIX):
        return ""
    rest = name[len(_WORKER_PREFIX):]
    parts = rest.split(":", 1)
    if len(parts) != 2 or not parts[1]:
        return ""
    return parts[1]


class QtLogHandler(logging.Handler, QObject):
    """把日志行经 Qt 信号送到主线程。

    worker 线程里 `emit`，Qt 自动排队到主线程 —— 与 `controller.py:89`
    的 status_changed 同一模式。`char_id` 为空串表示非 worker 线程。
    """

    record_emitted = pyqtSignal(str, str)

    def __init__(self) -> None:
        logging.Handler.__init__(self)
        QObject.__init__(self)
        # 只输出正文：时间戳由卡片侧的 LogPanel.append_message 加，
        # 两边都加会出双时间戳（预检裁定 7）。
        self.setFormatter(logging.Formatter("%(message)s"))
        # 退出时 logging.shutdown 会对每个 handler 读 flushOnClose；此时
        # QObject 的 C++ 对象已被 PyQt 先一步销毁，getattr 抛 RuntimeError，
        # 而 shutdown 只吞 OSError/ValueError —— 异常会让它整个中断，后续
        # handler 不再 flush/close。预置 Python 侧属性即可绕过（同
        # logging.handlers.MemoryHandler 的做法），本 handler 无需 flush。
        self.flushOnClose = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
        except Exception:                      # noqa: BLE001 - 日志不能反过来炸
            self.handleError(record)
            return
        cid = char_id_from_thread_name(threading.current_thread().name)
        self.record_emitted.emit(cid, text)
