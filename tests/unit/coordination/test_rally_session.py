import numpy as np
from unittest.mock import MagicMock
from rok_assistant.coordination.rally_session import RallySession
from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.core.handle_source import MockHandleSource

def test_session_launches_and_notifies_members():
    bus = EventBus()
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    recs = {"search_icon": rec, "rally_attack_popup": rec, "red_rally": rec,
            "blue_rally": rec, "preset_1": rec, "march_btn": rec, "level_plus": rec,
            "search_btn": rec, "next_fortress_arrow": rec}
    leader_sm = MagicMock()
    leader_sm.is_terminal.side_effect = [False, False, True]
    leader_sm.step = MagicMock()
    leader_sm.last_rally_event = {"rally_id": "r1", "fortress_level": 8, "march_preset": 1}

    notified = []
    bus.subscribe("rally_launched", lambda p: notified.append(p))

    session = RallySession(leader_sm=leader_sm, event_bus=bus, member_sms=[])
    session.run()
    assert len(notified) == 1
    assert notified[0]["rally_id"] == "r1"
