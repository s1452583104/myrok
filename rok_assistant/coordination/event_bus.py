"""事件总线模块.

提供发布/订阅模式的事件通信机制, 用于模块间解耦.

核心功能:
- 事件订阅/取消订阅
- 同步事件分发
- 异步事件分发
- 任务队列等待
"""

import queue
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar

from infrastructure.logger import get_logger

# ========== 事件定义 ==========


@dataclass
class Event:
    """事件基类.

    Attributes:
        event_type: 事件类型标识
        timestamp: 事件发生时间戳
        source: 事件来源模块名称
    """

    event_type: str = "event"
    timestamp: float = field(default_factory=time.time)
    source: str = ""


# ---------- 引擎事件 ----------


@dataclass
class EngineStartedEvent(Event):
    """引擎启动事件."""
    event_type: str = "engine.started"


@dataclass
class EngineStoppedEvent(Event):
    """引擎停止事件."""
    event_type: str = "engine.stopped"


@dataclass
class EngineErrorEvent(Event):
    """引擎错误事件."""
    event_type: str = "engine.error"
    error_message: str = ""


@dataclass
class EnginePausedEvent(Event):
    """引擎暂停事件."""
    event_type: str = "engine.paused"


@dataclass
class EngineResumedEvent(Event):
    """引擎恢复事件."""
    event_type: str = "engine.resumed"


# ---------- 任务事件 ----------


@dataclass
class TaskTriggeredEvent(Event):
    """任务触发事件."""
    event_type: str = "task.triggered"
    task: Any = None  # ScheduledTask


@dataclass
class TaskCompletedEvent(Event):
    """任务完成事件."""
    event_type: str = "task.completed"
    task_id: str = ""
    result: Any = None


@dataclass
class TaskFailedEvent(Event):
    """任务失败事件."""
    event_type: str = "task.failed"
    task_id: str = ""
    error: str = ""


# ---------- 检测事件 ----------


@dataclass
class DetectionCompletedEvent(Event):
    """检测完成事件."""
    event_type: str = "detection.completed"
    result: Any = None  # DetectionResult


@dataclass
class DetectionErrorEvent(Event):
    """检测错误事件."""
    event_type: str = "detection.error"
    error_message: str = ""


# ---------- 配置事件 ----------


@dataclass
class ConfigChangedEvent(Event):
    """配置变更事件."""
    event_type: str = "config.changed"
    new_config: Any = None  # AppConfig


# ---------- 窗口事件 ----------


@dataclass
class WindowLostEvent(Event):
    """窗口丢失事件."""
    event_type: str = "window.lost"


@dataclass
class WindowFoundEvent(Event):
    """窗口找到事件."""
    event_type: str = "window.found"


# ========== 事件总线 ==========

T = TypeVar("T", bound=Event)
EventHandler = Callable[[T], None]


class EventBus:
    """事件总线.

    职责:
    - 事件发布/订阅
    - 同步事件分发
    - 异步事件分发
    - 任务队列管理

    线程安全: 是 (使用锁保护内部状态)

    使用示例:
        bus = EventBus()
        bus.subscribe("engine.started", lambda e: print("Engine started!"))
        bus.publish(EngineStartedEvent())
    """

    def __init__(self):
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._lock = threading.Lock()
        self._task_queue: queue.Queue = queue.Queue()
        self._logger = get_logger(self.__class__.__name__)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """订阅指定类型的事件.

        Args:
            event_type: 事件类型字符串
            handler: 事件处理回调函数
        """
        with self._lock:
            self._handlers[event_type].append(handler)
        self._logger.debug(f"Subscribed to {event_type}")

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """取消订阅指定类型的事件.

        Args:
            event_type: 事件类型字符串
            handler: 要移除的回调函数
        """
        with self._lock:
            if event_type in self._handlers and handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)
        self._logger.debug(f"Unsubscribed from {event_type}")

    def publish(self, event: Event) -> None:
        """同步发布事件, 阻塞直到所有处理器执行完毕.

        Args:
            event: 要发布的事件对象
        """
        with self._lock:
            handlers = list(self._handlers.get(event.event_type, []))

        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                self._logger.error(
                    f"Event handler error [{event.event_type}]: {e}",
                    exc_info=True,
                )

    def publish_async(self, event: Event) -> None:
        """异步发布事件, 在后台线程中执行处理器.

        Args:
            event: 要发布的事件对象
        """
        threading.Thread(target=self.publish, args=(event,), daemon=True).start()

    def publish_to_queue(self, event: Event) -> None:
        """将任务事件放入任务队列, 供等待者消费.

        Args:
            event: TaskTriggeredEvent 事件对象
        """
        try:
            self._task_queue.put_nowait(event)
        except queue.Full:
            self._logger.warning("Task queue is full, event dropped")

    def wait_for_task(self, timeout: float = 1.0) -> Optional[Any]:
        """阻塞等待任务分配.

        Args:
            timeout: 超时时间(秒)

        Returns:
            任务对象, 超时时返回None
        """
        try:
            event = self._task_queue.get(timeout=timeout)
            if isinstance(event, TaskTriggeredEvent):
                return event.task
            return None
        except queue.Empty:
            return None

    def clear(self) -> None:
        """清除所有订阅."""
        with self._lock:
            self._handlers.clear()
        self._logger.info("All event handlers cleared")
