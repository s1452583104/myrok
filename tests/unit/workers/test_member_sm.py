import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def test_member_receives_event_and_joins():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95

    sm = MemberStateMachine(
        handle_source=handle, recognizers={"alliance_btn": rec, "war_btn": rec,
                                            "sort_nearest": rec, "join_btn": rec,
                                            "preset_1": rec, "march_btn": rec},
        march_preset=1, march_troop_types=["infantry"],
        fill_target_leaders="nearest"
    )

    sm.on_rally_launched({"rally_id": "r1", "fortress_level": 8, "march_preset": 1})
    for _ in range(30):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
