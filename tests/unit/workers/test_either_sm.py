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
    recs = {k: rec for k in ("search_icon", "map_btn", "search_back",
                             "level_plus", "search_btn",
                             "rally_attack_popup", "red_rally", "blue_rally",
                             "preset_1", "troop_infantry", "march_btn",
                             "alliance_btn", "war_title", "join_btn", "swap_btn",
                             "fill_Boss")}
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
    for _ in range(200):
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
    for _ in range(200):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()


def test_empty_fill_targets_still_reaches_member_end():
    sm = _make_sm()  # fill_targets defaults to []
    for _ in range(200):
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
    for _ in range(200):
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
    for _ in range(200):
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


def test_wait_return_polls_queue_badge_until_empty(monkeypatch):
    # 配置了 queue_badge：填兵结束后进入 WAIT_RETURN，徽标在 → 不终态；
    # 徽标消失（部队回城）→ 终态（2026-09-11 验收反馈的返城等待机制）
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    sm._leader._rec["queue_badge"] = badge
    for _ in range(200):
        sm.step()
        if sm.current == "WAIT_RETURN":
            break
    assert sm.current == "WAIT_RETURN", f"未进入返城等待: {sm.history[-5:]}"
    assert not sm.is_terminal()
    # 战争面板 mock 换成独立的不匹配实例（共享 mock 恒匹配会让新的
    # 「先关面板」分支每拍点 X 返回，徽标永远读不到）
    wt = _mock_rec()
    wt.recognize.return_value.matched = False
    sm._leader._rec["war_title"] = wt
    _FakeTime.t += 60    # 越过 30s 检测节流
    for _ in range(2):   # 徽标持续可见：保持等待，不终态
        sm.step()
        _FakeTime.t += 60
    assert sm.current == "WAIT_RETURN"
    assert not sm.is_terminal()
    badge.recognize.return_value.matched = False   # 部队回城
    _FakeTime.t += 60
    sm.step()
    assert sm.is_terminal()
    assert sm.current == "MEMBER:END"


def test_wait_return_without_badge_keeps_old_behavior():
    # 未配置 queue_badge（v1 模板缺失时）：member END 即终态，行为不变
    sm = _make_sm(fill_targets=[])
    assert "queue_badge" not in sm._leader._rec
    for _ in range(200):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    assert sm.current == "MEMBER:END"
    assert "WAIT_RETURN" not in sm.history


def test_wait_return_closes_war_panel_before_reading_badge(monkeypatch):
    # VERIFY_JOINED 结束时重开了战争列表，面板盖住徽标区域 —— 2026-09-12
    # 实机：行军后 2s 首查误判「已回城」。等待循环必须先关面板；刚点完
    # X 那拍画面未及刷新，不下结论，下个周期再读
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    badge.recognize.return_value.matched = False   # 徽标不可见（被面板盖住）
    sm._leader._rec["queue_badge"] = badge
    for _ in range(200):
        sm.step()
        if sm.current == "WAIT_RETURN":
            break
    _FakeTime.t += 60
    sm.step()   # war_title 可见：点 X 并返回，不得就此判「已回城」
    assert sm.current == "WAIT_RETURN"
    assert not sm.is_terminal()
    assert (1671, 64) in sm._leader._handle.clicks
