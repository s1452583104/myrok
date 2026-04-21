import threading
import time
from enum import Enum
from typing import Optional, List, Dict, Callable, Any
from dataclasses import dataclass
from core import BaseTaskStrategy
from infrastructure import get_logger, EngineError, TaskExecutionError
from coordination import EventBus, EngineStartedEvent, EngineStoppedEvent, EngineErrorEvent
from .game_controller import GameController
from .detection_service import DetectionService


class EngineState(Enum):
    """引擎状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    STOPPING = "stopping"


@dataclass
class TaskContext:
    """任务上下文"""
    game_controller: GameController
    detection_service: DetectionService
    config: Dict[str, Any]


@dataclass
class TaskResult:
    """任务结果"""
    success: bool
    error: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class AutomationTask:
    """自动化任务"""
    def __init__(self, task_id: str, task_type: str, config: Dict[str, Any]):
        self.id = task_id
        self.task_type = task_type
        self.config = config


class AutomationEngine:
    """自动化任务引擎"""
    
    def __init__(
        self,
        game_controller: GameController,
        detection_service: DetectionService,
        event_bus: EventBus,
    ):
        self._state = EngineState.IDLE
        self._game_controller = game_controller
        self._detection_service = detection_service
        self._event_bus = event_bus
        self._current_task: Optional[AutomationTask] = None
        self._task_history: List[TaskResult] = []
        self._strategies: Dict[str, BaseTaskStrategy] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._logger = get_logger(self.__class__.__name__)
    
    def start(self) -> None:
        """
        启动自动化引擎
        """
        if self._state != EngineState.IDLE:
            self._logger.warning(f"Engine not in IDLE state: {self._state}")
            return

        self._state = EngineState.RUNNING
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()
        self._event_bus.publish(EngineStartedEvent())
        self._logger.info("Automation engine started")
    
    def stop(self) -> None:
        """
        停止自动化引擎
        """
        self._state = EngineState.STOPPING
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        self._state = EngineState.IDLE
        self._event_bus.publish(EngineStoppedEvent())
        self._logger.info("Automation engine stopped")
    
    def pause(self) -> None:
        """
        暂停自动化引擎
        """
        if self._state == EngineState.RUNNING:
            self._state = EngineState.PAUSED
            self._logger.info("Automation engine paused")
    
    def resume(self) -> None:
        """
        恢复自动化引擎
        """
        if self._state == EngineState.PAUSED:
            self._state = EngineState.RUNNING
            self._logger.info("Automation engine resumed")
    
    def execute_task(self, task: AutomationTask) -> TaskResult:
        """
        执行单个任务
        
        Args:
            task: 任务对象
            
        Returns:
            TaskResult: 任务结果
        """
        try:
            self._current_task = task
            strategy = self._strategies.get(task.task_type)

            if strategy is None:
                error = f"No strategy for task type: {task.task_type}"
                self._logger.error(error)
                return TaskResult(success=False, error=error)

            # 执行任务
            context = TaskContext(
                game_controller=self._game_controller,
                detection_service=self._detection_service,
                config=task.config,
            )

            result = strategy.execute(context)
            self._task_history.append(result)

            if result.success:
                self._logger.info(f"Task {task.id} completed successfully")
            else:
                self._logger.error(f"Task {task.id} failed: {result.error}")

            return result
        except Exception as e:
            error = f"Task execution failed: {e}"
            self._logger.error(error)
            return TaskResult(success=False, error=error)
    
    def register_strategy(self, task_type: str, strategy: BaseTaskStrategy) -> None:
        """
        注册任务策略
        
        Args:
            task_type: 任务类型
            strategy: 策略实例
        """
        self._strategies[task_type] = strategy
        self._logger.info(f"Strategy registered for task type: {task_type}")
    
    def get_state(self) -> EngineState:
        """
        获取引擎状态
        
        Returns:
            EngineState: 引擎状态
        """
        return self._state
    
    def _main_loop(self) -> None:
        """
        主循环
        """
        retry_count = 0
        max_retries = 3

        while not self._stop_event.is_set():
            try:
                if self._state == EngineState.PAUSED:
                    time.sleep(1.0)
                    continue

                # 等待调度器分配任务
                task = self._event_bus.wait_for_task(timeout=1.0)
                if task is None:
                    continue

                # 执行任务
                self.execute_task(task)
                retry_count = 0

            except Exception as e:
                retry_count += 1
                self._logger.error(f"Main loop error (retry {retry_count}): {e}")

                if retry_count >= max_retries:
                    self._state = EngineState.ERROR
                    self._event_bus.publish(EngineErrorEvent(str(e)))
                    break

                import time
                time.sleep(min(2 ** retry_count, 10))  # 指数退避
    
    @property
    def state(self) -> EngineState:
        """
        引擎状态属性
        """
        return self._state
    
    def shutdown(self) -> None:
        """
        关闭自动化引擎
        """
        self.stop()
        self._logger.info("Automation engine shutdown")