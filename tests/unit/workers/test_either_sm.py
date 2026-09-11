import numpy as np
from unittest.mock import MagicMock
import pytest
from rok_assistant.workers.either_sm import EitherStateMachine
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource


@pytest.fixture(autouse=True)
def _no_level_pace(monkeypatch):
    # leader 等级连点停顿（防丢点击）在单测里置 0，免真实睡眠
    monkeypatch.setattr("rok_assistant.workers.leader_sm._LEVEL_CLICK_PACE", 0.0)


def _mock_rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec


def _make_sm(fill_targets=None, bus=None):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = _mock_rec()
    # map_btn/search_icon: member 视图归一化需要（成员阶段先确认在地图视图）
    recs = {k: rec for k in ("search_icon", "map_btn", "level_plus", "search_btn",
                             "rally_attack_popup", "red_rally", "blue_rally",
                             "preset_1", "troop_infantry", "march_btn",
                             "alliance_btn", "war_btn", "sort_nearest", "join_btn")}
    sm = EitherStateMachine(handle_source=handle, recognizers=recs,
                            target_level=8, march_preset=1,
                            march_troop_types=["infantry"],
                            fill_target_leaders=fill_targets or [],
                            event_bus=bus)
    # red_rally 独立 mock：give-up 测试只关掉详情弹窗的命中，
    # 不影响共享 rec 的其他识别器
    recs["red_rally"] = _mock_rec()
    return sm


def test_delegates_to_leader_then_member():
    sm = _make_sm(fill_targets=[{"instance": "i1", "name": "Boss"}])
    assert isinstance(sm._leader, LeaderStateMachine)
    assert isinstance(sm._member, MemberStateMachine)
    for _ in range(60):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    # leader 阶段完整走完（开集结），member 阶段接手到 END
    assert any("LEADER:LAUNCH" in h for h in sm.history)
    assert any(h.startswith("MEMBER:") for h in sm.history)
    # 开完集结不停留：member 收到了 launch 事件（消费后留存于 last_event）
    assert sm._member._pending_event is None
    assert sm._member.last_event is not None
    assert sm._member.last_event["rally_id"].startswith("rally_")


def test_not_terminal_during_leader_phase():
    sm = _make_sm()
    sm.step()  # IDLE -> NORMALIZE
    assert not sm.is_terminal()
    assert sm.current.startswith("LEADER:")


def test_step_reuses_stored_context():
    sm = _make_sm(fill_targets=[{"instance": "i1", "name": "Boss"}])
    sm.step({"marker": "x"})  # context stored; subsequent bare step() must reuse it
    for _ in range(60):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()


def test_empty_fill_targets_still_reaches_member_end():
    sm = _make_sm()  # fill_targets defaults to []
    for _ in range(60):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    assert sm.current == "MEMBER:END"


class _FakeTime:
    """Deterministic clock（同 test_leader_sm）：state_machine 的
    _wait_for/_click_retry 在超时重试时会 sleep，替换其 time 模块让等待
    瞬时推进，避免 give-up 路径在测试里烧真实秒数。"""

    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_leader_give_up_becomes_terminal_with_fail_reason(monkeypatch):
    # 搜寨永无结果：leader 走 3 次重试后 give_up —— either SM 必须呈现为
    # 终态（供 runner 冷却重建重试），而不是抛 RuntimeError 卡死在错误循环
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm = _make_sm(fill_targets=[{"instance": "i1", "name": "Boss"}])
    sm._leader._rec["red_rally"].recognize.return_value.matched = False
    for _ in range(60):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    assert sm.current == "LEADER:END"
    assert sm._leader.last_rally_event is None
    assert sm.fail_reason == "no_fortress_found"
    # 停在 leader 终态，绝不能带着 None 事件进入 member 阶段
    assert not any(h.startswith("MEMBER:") for h in sm.history)


def test_member_give_up_becomes_terminal_with_fail_reason():
    # member FILTER 耗尽（与 test_member_sm 相同的白盒预置）：either SM
    # 同样呈现为终态，runner 重建后重试 —— 与纯 member 语义一致
    sm = _make_sm(fill_targets=[{"instance": "i1", "name": "Boss"}])
    sm._ctx["war_attempts"] = 11
    for _ in range(60):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    assert sm.current == "MEMBER:END"
    assert sm.fail_reason == "no_rally_found"


def test_last_image_delegates_to_active_phase():
    sm = _make_sm()
    assert sm.last_image is None  # 尚未运行
    sm.step()  # IDLE -> NORMALIZE（leader 阶段 _find 捕获过帧）
    assert sm.last_image is not None
