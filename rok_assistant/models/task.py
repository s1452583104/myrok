from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable
from enum import Enum


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(Enum):
    """任务类型"""
    RESOURCE_COLLECT = "resource_collect"
    BUILDING_UPGRADE = "building_upgrade"
    ARMY_TRAINING = "army_training"
    GEM_COLLECT = "gem_collect"
    DAILY_TASK = "daily_task"


@dataclass
class Task:
    """任务基类"""
    id: str
    type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 5  # 1-10，10最高
    created_at: float = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None


@dataclass
class ScheduledTask(Task):
    """调度任务"""
    interval: int = 0  # 间隔秒数
    next_run: Optional[float] = None
    last_run: Optional[float] = None
    run_count: int = 0


@dataclass
class AutomationTask(Task):
    """自动化任务"""
    config: Dict[str, Any] = None
    strategy: Optional[Callable] = None


@dataclass
class TaskResult:
    """任务结果"""
    success: bool
    task_id: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time: float = 0