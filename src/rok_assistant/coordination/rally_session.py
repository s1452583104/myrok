from __future__ import annotations
from .event_bus import EventBus

class RallySession:
    """One end-to-end rally attempt. Drives leader, broadcasts events to members."""
    def __init__(self, leader_sm, event_bus: EventBus, member_sms: list):
        self._leader = leader_sm
        self._bus = event_bus
        self._members = member_sms
        # Wire leader's rally_launched to bus
        if hasattr(leader_sm, "_bus") and leader_sm._bus is None:
            leader_sm._bus = event_bus
        # Subscribe members
        for m in member_sms:
            event_bus.subscribe("rally_launched", m.on_rally_launched)

    def run(self, max_steps: int = 100) -> None:
        published_event = None
        for _ in range(max_steps):
            if self._leader.is_terminal():
                return
            self._leader.step()
            # After each step, check if the leader produced a rally event
            # and publish it once to the bus.
            event = getattr(self._leader, "last_rally_event", None)
            if event is not None and event is not published_event:
                self._bus.publish("rally_launched", event)
                published_event = event
