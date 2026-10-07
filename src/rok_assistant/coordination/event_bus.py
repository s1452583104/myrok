from __future__ import annotations
from typing import Callable
from collections import defaultdict

from ..infra.logger import get_logger

logger = get_logger(__name__)

class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable) -> None:
        self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable) -> None:
        # 幂等：未订阅时静默返回。RuntimeCoordinator 需要「先撤后挂」来保证
        # 恰好一份订阅，而它可能在自然收工/stop 后已自行退订过——重复撤订
        # 不该抛 ValueError（list.remove 对缺失元素会抛）。
        handlers = self._handlers.get(event)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def publish(self, event: str, payload: dict) -> None:
        # 订阅者在 worker 线程内被调用（如 _set_status 的 except 路径），
        # 单个订阅者抛异常不能杀死调用线程、也不能中断其余订阅者。
        for handler in list(self._handlers[event]):
            try:
                handler(payload)
            except Exception:
                logger.exception("EventBus 订阅者处理事件 %s 时抛出异常", event)
