from unittest.mock import MagicMock

import numpy as np

from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.coordination.action_ledger import ActionLedger
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.member_sm import MemberStateMachine


def _rec(matched=True):
    rec = MagicMock()
    rec.recognize.return_value.matched = matched
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec


def _img():
    return np.zeros((100, 100, 3), dtype=np.uint8)


def test_leader_launch_writes_troops_out_and_rally_ts():
    """发车确认成功 → 账本记「在外」+ 发车时刻。
    没有这一步，门槛的 L0 判据就永远是「无记录」。"""
    handle = MockHandleSource(screenshot=_img())
    recs = {k: _rec() for k in ("march_btn", "queue_badge")}
    led = ActionLedger()
    sm = LeaderStateMachine(handle, recs, target_levels=[7], march_preset=1,
                            march_troop_types=["infantry"], ledger=led,
                            publisher_id="c1")
    sm._launch({})
    assert led.troops_out("c1") is True
    assert led.snapshot("c1").last_rally_launched_ts > 0.0


def test_leader_rejected_launch_does_not_write_ledger():
    """被静默拒绝（队列徽标没出现）→ **不能**记「在外」。
    账本一旦掺入未生效的动作，就退化回猜测。"""
    handle = MockHandleSource(screenshot=_img())
    recs = {k: _rec() for k in ("march_btn", "queue_badge")}
    recs["queue_badge"] = _rec(matched=False)
    led = ActionLedger()
    sm = LeaderStateMachine(handle, recs, target_levels=[7], march_preset=1,
                            march_troop_types=["infantry"], ledger=led,
                            publisher_id="c1")
    ctx = {}
    sm._launch(ctx)
    assert ctx.get("fail_reason") == "rally_rejected"
    assert led.has_record("c1") is False


def test_member_verify_join_writes_fill_done_and_troops_out():
    """橙「替换」出现 = 填兵确实发出去了，此时才写账本。
    上面的 ap_refill 分支是「行军根本没发出去」，不写。"""
    handle = MockHandleSource(screenshot=_img())
    recs = {k: _rec() for k in ("war_title", "swap_btn", "alliance_btn")}
    led = ActionLedger()
    sm = MemberStateMachine(handle, recs, fill_target_leaders=[],
                            char_id="c2", ledger=led)
    sm._verify_join({})
    assert led.troops_out("c2") is True
    assert led.snapshot("c2").last_fill_ts > 0.0


def test_member_verify_join_failure_does_not_write_ledger():
    handle = MockHandleSource(screenshot=_img())
    recs = {k: _rec() for k in ("war_title", "alliance_btn")}
    recs["swap_btn"] = _rec(matched=False)
    led = ActionLedger()
    sm = MemberStateMachine(handle, recs, fill_target_leaders=[],
                            char_id="c2", ledger=led)
    sm._verify_join({})
    assert led.has_record("c2") is False


def test_leader_launch_without_queue_badge_does_not_write_ledger():
    """未配置队列徽标识别器 = 没有任何确认手段 → 不写账本。
    账本是门槛信任的层级，写「大概发出去了」等于埋一颗迟早被读到的雷；
    宁可让门槛退回 fail-closed 的宽限路径。"""
    handle = MockHandleSource(screenshot=_img())
    recs = {k: _rec() for k in ("march_btn",)}   # 无 queue_badge
    led = ActionLedger()
    sm = LeaderStateMachine(handle, recs, target_levels=[7], march_preset=1,
                            march_troop_types=["infantry"], ledger=led,
                            publisher_id="c1")
    sm._launch({})
    assert led.has_record("c1") is False


def test_no_ledger_is_a_no_op():
    """不传 ledger 时行为与旧版完全一致——这是现有测试保持绿的前提。
    显式断言账本侧零副作用：SM 不持有账本，旁置账本对象保持空白。"""
    handle = MockHandleSource(screenshot=_img())
    recs = {k: _rec() for k in ("march_btn", "queue_badge")}
    led = ActionLedger()   # 见证对象：未注入 SM，必须分毫未动
    sm = LeaderStateMachine(handle, recs, target_levels=[7], march_preset=1,
                            march_troop_types=["infantry"], publisher_id="c1")
    sm._launch({})   # 不得抛异常
    assert sm._ledger is None
    assert led.has_record("c1") is False
