"""任务调度器模块.

提供任务调度、定时触发和优先级管理功能.

核心功能:
- 管理定时/条件/手动触发任务
- 任务优先级管理
- 触发时机计算
- 与事件总线通信

线程安全: 是
"""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from coordination.event_bus import EventBus, TaskTriggeredEvent
from infrastructure.logger import get_logger


class TriggerType(Enum):
    """触发器类型."""

    INTERVAL = "interval"  # 定时触发
    CONDITION = "condition"  # 条件触发
    MANUAL = "manual"  # 手动触发
    ONCE = "once"  # 一次性触发


@dataclass
class ScheduledTask:
    """调度任务.

    Attributes:
        id: 任务唯一标识
        task_type: 关联的策略类型
        trigger_type: 触发器类型
        interval_seconds: 间隔触发时的间隔秒数
        condition: 条件触发时的条件函数
        priority: 优先级 1-10, 10最高
        config: 任务配置参数
        enabled: 是否启用
        last_run: 上次执行时间戳
        next_run: 下次执行时间戳
        run_count: 执行次数
    """

    id: str
    task_type: str
    trigger_type: TriggerType
    interval_seconds: int = 0
    condition: Optional[Callable] = None
    priority: int = 5
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[float] = None
    next_run: Optional[float] = None
    run_count: int = 0


class TaskScheduler:
    """任务调度器.

    职责:
    - 管理定时/条件/手动触发任务
    - 任务优先级管理
    - 触发时机计算
    - 与事件总线通信

    线程安全: 是

    使用示例:
        bus = EventBus()
        scheduler = TaskScheduler(bus)
        task = ScheduledTask(
            id="gem_collect_1",
            task_type="gem_collect",
            trigger_type=TriggerType.INTERVAL,
            interval_seconds=300,
            priority=8,
        )
        scheduler.add_task(task)
        scheduler.start()
    """

    def __init__(self, event_bus: EventBus):
        """初始化任务调度器.

        Args:
            event_bus: 事件总线实例
        """
        self._tasks: Dict[str, ScheduledTask] = {}
        self._event_bus = event_bus
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._logger = get_logger(self.__class__.__name__)

    def add_task(self, task: ScheduledTask) -> str:
        """添加调度任务.

        Args:
            task: 调度任务对象

        Returns:
            任务ID
        """
        with self._lock:
            now = time.time()
            if task.trigger_type == TriggerType.INTERVAL:
                task.next_run = now + task.interval_seconds
            elif task.trigger_type == TriggerType.ONCE:
                task.next_run = now
            elif task.trigger_type == TriggerType.CONDITION:
                task.next_run = now  # 立即开始检查条件
            self._tasks[task.id] = task
            self._logger.info(
                f"Task added: {task.id}, type={task.task_type}, "
                f"trigger={task.trigger_type.value}"
            )
            return task.id

    def remove_task(self, task_id: str) -> bool:
        """移除调度任务.

        Args:
            task_id: 任务ID

        Returns:
            是否移除成功
        """
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._logger.info(f"Task removed: {task_id}")
                return True
            return False

    def enable_task(self, task_id: str) -> bool:
        """启用任务.

        Args:
            task_id: 任务ID

        Returns:
            是否启用成功
        """
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].enabled = True
                # 重新计算下次运行时间
                if self._tasks[task_id].trigger_type == TriggerType.INTERVAL:
                    self._tasks[task_id].next_run = (
                        time.time() + self._tasks[task_id].interval_seconds
                    )
                elif self._tasks[task_id].trigger_type == TriggerType.ONCE:
                    self._tasks[task_id].next_run = time.time()
                self._logger.info(f"Task enabled: {task_id}")
                return True
            return False

    def disable_task(self, task_id: str) -> bool:
        """禁用任务.

        Args:
            task_id: 任务ID

        Returns:
            是否禁用成功
        """
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].enabled = False
                self._logger.info(f"Task disabled: {task_id}")
                return True
            return False

    def trigger_manual(self, task_id: str) -> bool:
        """手动触发任务.

        Args:
            task_id: 任务ID

        Returns:
            是否触发成功
        """
        with self._lock:
            if task_id not in self._tasks:
                self._logger.warning(f"Task not found: {task_id}")
                return False

            task = self._tasks[task_id]
            self._event_bus.publish(TaskTriggeredEvent(task=task))
            task.last_run = time.time()
            task.run_count += 1
            self._logger.info(f"Task manually triggered: {task_id}")
            return True

    def get_tasks(self) -> List[ScheduledTask]:
        """获取所有任务.

        Returns:
            任务列表
        """
        with self._lock:
            return list(self._tasks.values())

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """获取指定任务.

        Args:
            task_id: 任务ID

        Returns:
            任务对象, 不存在时返回None
        """
        with self._lock:
            return self._tasks.get(task_id)

    def start(self) -> None:
        """启动调度器."""
        if self._running:
            self._logger.warning("Scheduler already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._scheduler_loop, daemon=True, name="TaskScheduler"
        )
        self._thread.start()
        self._logger.info("Task scheduler started")

    def stop(self) -> None:
        """停止调度器."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._logger.info("Task scheduler stopped")

    def _scheduler_loop(self) -> None:
        """调度循环."""
        while self._running:
            try:
                self._check_due_tasks()
                time.sleep(0.5)  # 检查间隔
            except Exception as e:
                self._logger.error(f"Scheduler loop error: {e}", exc_info=True)
                time.sleep(1.0)

    def _check_due_tasks(self) -> None:
        """检查并触发到期的任务."""
        now = time.time()
        with self._lock:
            due_tasks = []
            for task in self._tasks.values():
                if not task.enabled:
                    continue
                if task.trigger_type == TriggerType.MANUAL:
                    continue

                # 检查条件触发
                if task.trigger_type == TriggerType.CONDITION:
                    if task.condition is not None:
                        try:
                            if task.condition():
                                due_tasks.append(task)
                        except Exception as e:
                            self._logger.error(
                                f"Condition check error for {task.id}: {e}"
                            )
                    continue

                # 检查定时触发
                if task.next_run is not None and now >= task.next_run:
                    due_tasks.append(task)

            # 按优先级排序
            due_tasks.sort(key=lambda t: t.priority, reverse=True)

            for task in due_tasks:
                self._event_bus.publish(TaskTriggeredEvent(task=task))
                task.last_run = now
                task.run_count += 1

                if task.trigger_type == TriggerType.INTERVAL:
                    task.next_run = now + task.interval_seconds
                elif task.trigger_type == TriggerType.ONCE:
                    task.enabled = False
                    task.next_run = None
