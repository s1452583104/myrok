import numpy as np
import pytest
from unittest.mock import MagicMock
from rok_assistant.workers.switcher_sm import SwitcherStateMachine
from rok_assistant.core.handle_source import MockHandleSource

@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # 失败重试路径自带退避 sleep（_click_retry/_find_retry），单元测试里直接跳过
    monkeypatch.setattr("rok_assistant.workers.switcher_sm.time.sleep", lambda s: None)

def _result(matched: bool):
    r = MagicMock()
    r.matched = matched
    r.bbox = MagicMock(center=lambda: (50, 50))
    return r

def _rec(matched: bool = True):
    rec = MagicMock()
    rec.recognize.return_value = _result(matched)
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
    recs = {k: _rec() for k in ("settings_btn", "char_mgmt_btn",
                                "char_avatar_boss", "switch_confirm_yes",
                                "click_to_enter", "avatar_self_boss")}
    sm, handle = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.is_done()
    assert not sm.ctx.get("switch_failed")
    # avatar(fixed coords) + settings + char_mgmt + target avatar + confirm + click_to_enter = 6 clicks
    assert len(handle.clicks) == 6

def test_verify_skipped_when_no_template():
    recs = {k: _rec() for k in ("settings_btn", "char_mgmt_btn",
                                "char_avatar_boss", "switch_confirm_yes",
                                "click_to_enter")}
    sm, _ = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.is_done()
    assert sm.ctx.get("verify_skipped") is True   # §1.5.3: no avatar template, skip verify

def test_no_avatar_template_flags_failure():
    recs = {k: _rec() for k in ("settings_btn", "char_mgmt_btn",
                                "switch_confirm_yes", "click_to_enter")}
    sm, _ = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.ctx.get("switch_failed") is True

def test_avatar_never_found_short_circuits():
    # 头像模板配置了但永远识别不到：必须判失败并短路，不能继续点「是」
    recs = {k: _rec() for k in ("settings_btn", "char_mgmt_btn",
                                "switch_confirm_yes", "click_to_enter")}
    recs["char_avatar_boss"] = _rec(matched=False)
    sm, handle = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.is_done()
    assert sm.ctx.get("switch_failed") is True
    assert sm.ctx.get("fail_reason", "").startswith("avatar_not_found")
    # 只点了：固定头像 + 设置 + 角色管理；确认框和登录页绝不能被点
    assert handle.clicks == [(75, 60), (50, 50), (50, 50)]

def test_verify_retry_reruns_flow_then_done():
    # 第 1 轮校验 3 次全失败（每次 VERIFY 消耗 3 个 recognize 调用），
    # 第 2 轮第 1 次即成功 → 整个流程从 OPEN_PROFILE 重走一遍后 DONE
    verify = MagicMock()
    verify.recognize.side_effect = [_result(False), _result(False),
                                    _result(False), _result(True)]
    recs = {k: _rec() for k in ("settings_btn", "char_mgmt_btn",
                                "char_avatar_boss", "switch_confirm_yes",
                                "click_to_enter")}
    recs["avatar_self_boss"] = verify
    sm, handle = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.is_done()
    assert not sm.ctx.get("switch_failed")
    assert sm.history.count("OPEN_PROFILE") == 2   # 重走了 1 遍
    assert len(handle.clicks) == 12                # 2 遍 × 6 次点击

def test_verify_retries_exhausted_flags_failure():
    # 校验重试次数用尽（retries<2 只允许重走 1 遍）：判失败并给出 verify_failed
    recs = {k: _rec() for k in ("settings_btn", "char_mgmt_btn",
                                "char_avatar_boss", "switch_confirm_yes",
                                "click_to_enter")}
    recs["avatar_self_boss"] = _rec(matched=False)
    sm, handle = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.is_done()
    assert sm.ctx.get("switch_failed") is True
    assert sm.ctx.get("fail_reason") == "verify_failed"
    assert len(handle.clicks) == 12   # 2 遍完整流程；第 3 遍被 retries<2 挡住
