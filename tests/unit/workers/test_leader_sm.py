import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def test_leader_full_session_path():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    # Stub recognizers that always succeed
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    sm = LeaderStateMachine(
        handle_source=handle, recognizers={"search_icon": rec, "rally_attack_popup": rec,
                                            "red_rally": rec, "blue_rally": rec,
                                            "preset_1": rec, "march_btn": rec,
                                            "level_select": rec, "level_plus": rec,
                                            "search_btn": rec, "next_fortress_arrow": rec,
                                            "troop_infantry": rec},
        target_level=8, march_preset=1, march_troop_types=["infantry"]
    )
    for _ in range(30):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    # Should have called rally_launched at LAUNCH
    assert sm.last_rally_event is not None
    assert sm.last_rally_event["fortress_level"] == 8
