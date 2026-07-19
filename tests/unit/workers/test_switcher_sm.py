import numpy as np
from rok_assistant.workers.switcher_sm import SwitcherStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def test_switcher_walks_4_steps():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    handle = MockHandleSource(screenshot=img)
    sm = SwitcherStateMachine(handle_source=handle, target_character="Boss",
                              recognizers={}, ocr=None)
    sm.run_until_done()
    # Should have clicked: avatar, settings_button, char_mgmt_button, target char
    assert len(handle.clicks) >= 4
    # Last state should be DONE
    assert sm.current == "DONE"

def test_switcher_state_progression():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    handle = MockHandleSource(screenshot=img)
    sm = SwitcherStateMachine(handle_source=handle, target_character="Boss",
                              recognizers={}, ocr=None)
    seen = []
    while not sm.is_done():
        seen.append(sm.current)
        sm.step()
    assert seen[0] == "IDLE"
    assert "OPEN_PROFILE" in seen
    assert "OPEN_SETTINGS" in seen
    assert "OPEN_CHAR_MGMT" in seen
    assert "PICK_CHAR" in seen
