from typing import Dict, List, Callable, Optional, Any
import threading
import time
from infrastructure import get_logger


class Event:
    """事件基类"""
    pass


class EngineStartedEvent(Event):
    """引擎启动事件"""
    pass


class EngineStoppedEvent(Event):
    """引擎停止事件"""
    pass


class EngineErrorEvent(Event):
    """引擎错误事件"""
    def __init__(self, error_message: str):
        self.error_message = error_message


class TaskCompletedEvent(Event):
    """任务完成事件"""
    def __init__(self, task_id: str, result: Any):
        self.task_id = task_id
        self.result = result


class TaskFailedEvent(Event):
    """任务失败事件"""
    def __init__(self, task_id: str, error: str):
        self.task_id = task_id
        self.error = error


class ConfigChangedEvent(Event):
    """配置变更事件"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config


class EventBus:
    """事件总线"""
    
    def __init__(self):
        self._subscribers: Dict[type, List[Callable]] = {}
        self._lock = threading.RLock()
        self._logger = get_logger(self.__class__.__name__)
    
    def subscribe(self, event_type: type, callback: Callable):
        """
        订阅事件
        
        Args:
            event_type: 事件类型
            callback: 回调函数
        """
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)
            self._logger.debug(f"Subscribed to {event_type.__name__}")
    
    def unsubscribe(self, event_type: type, callback: Callable):
        """
        取消订阅
        
        Args:
            event_type: 事件类型
            callback: 回调函数
        """
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(callback)
                    self._logger.debug(f"Unsubscribed from {event_type.__name__}")
                except ValueError:
                    pass
    
    def publish(self, event: Event):
        """
        发布事件
        
        Args:
            event: 事件对象
        """
        event_type = type(event)
        with self._lock:
            subscribers = self._subscribers.get(event_type, [])
        
        self._logger.debug(f"Publishing event: {event_type.__name__} to {len(subscribers)} subscribers")
        
        for callback in subscribers:
            try:
                callback(event)
            except Exception as e:
                self._logger.error(f"Error in event callback: {e}")
    
    def wait_for_event(self, event_type: type, timeout: float = None) -> Optional[Event]:
        """
        等待特定事件
        
        Args:
            event_type: 事件类型
            timeout: 超时时间（秒）
            
        Returns:
            Optional[Event]: 事件对象，超时返回None
        """
        result = None
        event_received = threading.Event()
        
        def callback(event):
            nonlocal result
            result = event
            event_received.set()
        
        self.subscribe(event_type, callback)
        
        try:
            if event_received.wait(timeout):
                return result
            return None
        finally:
            self.unsubscribe(event_type, callback)
    
    def wait_for_task(self, timeout: float = None) -> Optional[Any]:
        """
        等待任务
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            Optional[Any]: 任务对象，超时返回None
        """
        # 这里需要根据具体的任务队列实现
        # 作为示例，返回None
        time.sleep(0.1)  # 避免忙等
        return None