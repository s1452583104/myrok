import time
import threading
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from infrastructure import get_logger
from .event_bus import EventBus, TaskCompletedEvent, TaskFailedEvent


class TriggerType(Enum):
    INTERVAL = "interval"       # 定时触发
    CONDITION = "condition"     # 条件触发
    MANUAL = "manual"           # 手动触发
    ONCE = "once"               # 一次性触发


@dataclass
class ScheduledTask:
    """调度任务"""
    id: str
    task_type: str              # 关联的策略类型
    trigger_type: TriggerType
    interval_seconds: int = 0   # 间隔触发时使用
    condition: Optional[Callable] = None  # 条件触发时使用
    priority: int = 5           # 优先级 1-10，10最高
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[float] = None
    next_run: Optional[float] = None
    run_count: int = 0


class TaskScheduler:
    """任务调度器"""
    
    def __init__(self, event_bus: EventBus):
        self._tasks: Dict[str, ScheduledTask] = {}
        self._event_bus = event_bus
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._logger = get_logger(self.__class__.__name__)
    
    def add_task(self, task: ScheduledTask) -> str:
        """
        添加调度任务
        
        Args:
            task: 任务对象
            
        Returns:
            str: 任务ID
        """
        with self._lock:
            now = time.time()
            if task.trigger_type == TriggerType.INTERVAL:
                task.next_run = now + task.interval_seconds
            elif task.trigger_type == TriggerType.ONCE:
                task.next_run = now
            self._tasks[task.id] = task
            self._logger.info(f"Task added: {task.id}, type={task.task_type}")
            return task.id
    
    def remove_task(self, task_id: str) -> bool:
        """
        移除任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否成功移除
        """
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._logger.info(f"Task removed: {task_id}")
                return True
            return False
    
    def enable_task(self, task_id: str) -> bool:
        """
        启用任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否成功启用
        """
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].enabled = True
                self._logger.info(f"Task enabled: {task_id}")
                return True
            return False
    
    def disable_task(self, task_id: str) -> bool:
        """
        禁用任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否成功禁用
        """
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].enabled = False
                self._logger.info(f"Task disabled: {task_id}")
                return True
            return False
    
    def start(self) -> None:
        """
        启动调度器
        """
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
            self._thread.start()
            self._logger.info("Task scheduler started")
    
    def stop(self) -> None:
        """
        停止调度器
        """
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        self._logger.info("Task scheduler stopped")
    
    def get_tasks(self) -> List[ScheduledTask]:
        """
        获取所有任务
        
        Returns:
            List[ScheduledTask]: 任务列表
        """
        with self._lock:
            return list(self._tasks.values())
    
    def _scheduler_loop(self) -> None:
        """
        调度循环
        """
        while self._running:
            try:
                self._check_due_tasks()
                time.sleep(0.5)  # 检查间隔
            except Exception as e:
                self._logger.error(f"Scheduler loop error: {e}")
                time.sleep(1.0)
    
    def _check_due_tasks(self) -> None:
        """
        检查并触发到期的任务
        """
        now = time.time()
        with self._lock:
            due_tasks = []
            for task in self._tasks.values():
                if not task.enabled:
                    continue
                if task.trigger_type == TriggerType.MANUAL:
                    continue
                if task.next_run is not None and now >= task.next_run:
                    due_tasks.append(task)
            
            # 按优先级排序
            due_tasks.sort(key=lambda x: x.priority, reverse=True)
        
        for task in due_tasks:
            self._execute_task(task)
    
    def _execute_task(self, task: ScheduledTask) -> None:
        """
        执行任务
        
        Args:
            task: 任务对象
        """
        self._logger.info(f"Executing task: {task.id}, type={task.task_type}")
        
        try:
            # 执行任务
            # 这里需要与自动化引擎通信
            # 作为示例，直接发布任务完成事件
            task.last_run = time.time()
            task.run_count += 1
            
            # 更新下次运行时间
            if task.trigger_type == TriggerType.INTERVAL:
                task.next_run = task.last_run + task.interval_seconds
            elif task.trigger_type == TriggerType.ONCE:
                task.enabled = False
                task.next_run = None
            
            # 发布任务完成事件
            self._event_bus.publish(TaskCompletedEvent(task.id, "Task completed successfully"))
            
        except Exception as e:
            self._logger.error(f"Task execution failed: {e}")
            self._event_bus.publish(TaskFailedEvent(task.id, str(e)))
    
    def trigger_task(self, task_id: str) -> bool:
        """
        手动触发任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否成功触发
        """
        with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                self._execute_task(task)
                return True
            return False