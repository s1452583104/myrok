import numpy as np
from rok_assistant.gui.controller import GuiController
from rok_assistant.core.handle_source import MockHandleSource

def test_controller_initializes_from_config():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    c = GuiController(handle_sources={"acc1": handle})
    assert c.handle_sources["acc1"] is handle

def test_controller_update_status_pushes_to_event_bus():
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    received = []
    bus.subscribe("status_update", lambda p: received.append(p))
    c = GuiController(handle_sources={}, event_bus=bus)
    c.update_status("acc1", "char1", "searching")
    assert len(received) == 1
    assert received[0]["status"] == "searching"
