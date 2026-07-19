from __future__ import annotations
from typing import Callable, Any

class GuiController:
    def __init__(self, handle_sources: dict, event_bus=None, config=None):
        self.handle_sources = handle_sources
        self.event_bus = event_bus
        self.config = config
        self._status_subscribers: list[Callable] = []

    def subscribe_status(self, callback: Callable) -> None:
        self._status_subscribers.append(callback)

    def update_status(self, account_id: str, char_id: str, status: str) -> None:
        payload = {"account_id": account_id, "char_id": char_id, "status": status}
        for sub in self._status_subscribers:
            sub(payload)
        if self.event_bus:
            self.event_bus.publish("status_update", payload)
