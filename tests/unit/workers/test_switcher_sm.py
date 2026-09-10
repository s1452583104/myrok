import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.switcher_sm import SwitcherStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def _mock_rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    return rec

def _make_sm(recognizers=None, load_wait=0.0):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    sm = SwitcherStateMachine(handle_source=handle, target_character="Boss",
                              recognizers=recognizers or {},
                              avatar_key="char_avatar_boss",
                              verify_key="avatar_self_boss",
                              load_wait_seconds=load_wait)
    return sm, handle

def test_walks_5_steps_with_confirm_and_relogin():
    recs = {k: _mock_rec() for k in ("settings_btn", "char_mgmt_btn",
                                     "char_avatar_boss", "switch_confirm_yes",
                                     "click_to_enter", "avatar_self_boss")}
    sm, handle = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.is_done()
    assert not sm.ctx.get("switch_failed")
    # avatar(fixed coords) + settings + char_mgmt + target avatar + confirm + click_to_enter = 6 clicks
    assert len(handle.clicks) == 6

def test_verify_skipped_when_no_template():
    recs = {k: _mock_rec() for k in ("settings_btn", "char_mgmt_btn",
                                     "char_avatar_boss", "switch_confirm_yes",
                                     "click_to_enter")}
    sm, _ = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.is_done()
    assert sm.ctx.get("verify_skipped") is True   # §1.5.3: no avatar template, skip verify

def test_no_avatar_template_flags_failure():
    recs = {k: _mock_rec() for k in ("settings_btn", "char_mgmt_btn",
                                     "switch_confirm_yes", "click_to_enter")}
    sm, _ = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.ctx.get("switch_failed") is True
