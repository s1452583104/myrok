"""端到端集成测试：WorkerRunner × EventBus × Leader/Member 状态机（Task 9）。

用 MagicMock 识别器（全部命中）驱动真实流程，验证完整链路：
leader runner 走完开集结流程并发布 rally_launched → 事件路由到 member
runner 的 SM（复刻 RuntimeCoordinator 的 IDLE/WAIT_LAUNCH_EVENT 门控）→
member 填兵走到 END → leader 到 END 后被 runner 冷却重建，新 SM 回到 IDLE。
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
from unittest.mock import MagicMock

import numpy as np

from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.workers.runner import WorkerRunner

# 两个 SM 源码里 _find/_click/_wait_for 触碰过的全部识别器 id；
# MagicMock 识别器全部命中，流程零等待快速走完。
LEADER_IDS = (
    "search_icon", "map_btn", "tab_fortress", "level_minus", "level_plus",
    "search_btn", "toast_no_fortress", "red_rally", "rally_attack_popup",
    "blue_rally", "march_btn", "preset_1", "troop_cavalry",
)
# member 填兵不点预设/兵种（用户要求 2026-09-09）：无 preset_*/troop_* id；
# 实机链路（2026-09-11）：旗帜 -> 战争列表 -> 点绿「+」即默认部队出兵
MEMBER_IDS = (
    "search_icon", "map_btn", "search_back", "alliance_btn",
    "war_title", "join_btn", "swap_btn", "march_btn", "fill_车头",
)


def _rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec


def _recs(ids):
    return {k: _rec() for k in ids}


def test_leader_launches_member_fills_and_runner_rebuilds(monkeypatch):
    # 等级连点防丢停顿在 E2E 里置 0：mock 识别器下无需防丢，省 ~6s 真实睡眠
    monkeypatch.setattr("rok_assistant.workers.leader_sm._LEVEL_CLICK_PACE", 0.0)
    bus = EventBus()
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    handle = MockHandleSource(screenshot=img)

    leader_sms = []     # 记录 leader 经历过的每个 SM 实例
    statuses = []       # (char_id, state) —— runner 发布的 status_update 序列

    def leader_factory():
        sm = LeaderStateMachine(handle, _recs(LEADER_IDS),
                                target_levels=[7], march_preset=1,
                                march_troop_types=["cavalry"], event_bus=bus,
                                wait_members_seconds=0.0)
        leader_sms.append(sm)
        return sm

    def member_factory():
        return MemberStateMachine(handle, _recs(MEMBER_IDS),
                                  [{"instance": "i0", "name": "车头"}])

    # member 的 restart_cooldown 取很大：member 一旦到 END 就保持终态，
    # 断言窗口确定（否则 member 重建回 IDLE 会与 leader 的重建节拍竞争，
    # 轮询瞬间可能永远凑不齐断言条件）
    leader = WorkerRunner("i0", "boss", "车头", leader_factory, handle, bus,
                          poll_interval=0.05, restart_cooldown=0.1,
                          error_backoff=0.1)
    member = WorkerRunner("i1", "sub", "成员", member_factory, handle, bus,
                          poll_interval=0.05, restart_cooldown=600.0,
                          error_backoff=0.1)

    def _route(event):
        # 复刻 RuntimeCoordinator 的路由：成员 SM 只在等事件的状态收事件
        sm = member.sm
        if sm.current in ("IDLE", "WAIT_LAUNCH_EVENT"):
            sm.on_rally_launched(event)

    def _record(payload):
        statuses.append((payload["char_id"], payload["state"]))

    bus.subscribe("rally_launched", _route)
    bus.subscribe("status_update", _record)
    leader.start()
    member.start()
    try:
        # 只用单调信号做轮询出口：member 到 END（长冷却保持终态）+
        # leader 已至少重建过一次。leader.sm.current == "IDLE" 的窗口
        # 只有微秒级（重建后 runner 立即 continue→step，不睡 poll），
        # 直接轮询它不稳定；改用 runner 发布的 status_update 序列作证。
        deadline = time.time() + 10
        while time.time() < deadline:
            if member.sm.current == "END" and len(leader_sms) >= 2:
                break
            time.sleep(0.02)

        # member 收到 leader 的集结事件并走完填兵流程到终态
        assert member.sm.current == "END"
        assert member.sm.last_event is not None
        assert member.sm.last_event["fortress_level"] == 7
        assert member.sm.last_event["march_preset"] == 1

        # leader 冷却后重建：runner 的状态序列必须出现 END → cooldown →
        # IDLE（终态是 END，SM 不可能自己变回 IDLE——重建后发布 IDLE
        # 即证明 sm 被换成了新实例）
        leader_states = [s for cid, s in statuses if cid == "boss"]
        assert "END" in leader_states
        # 超时兜底：给断言一个可读的信息，而不是让 index() 抛 ValueError
        assert "cooldown" in leader_states, f"10s 内 leader 未进入冷却: {leader_states}"
        cooldown_at = leader_states.index("cooldown")
        assert cooldown_at + 1 < len(leader_states), \
            f"leader 状态序列在 cooldown 处截断: {leader_states}"
        assert leader_states[cooldown_at + 1] == "IDLE"
        assert leader.reached_terminal()
        assert len(leader_sms) >= 2          # 至少重建过一次
        # 当前 SM 已不是最初那个实例（不用 is leader_sms[-1]：轮询间隙若恰好
        # 又一轮重建，[-1] 会抖动；is not [0] 是无竞态的重建证明）
        assert leader.sm is not leader_sms[0]
        assert leader_sms[0].last_rally_event is not None   # 首轮真的发过车

        # 全程真的发生了点击（mock 识别器全命中，两个 SM 共用同一 handle）
        assert handle.clicks
    finally:
        leader.stop()
        member.stop()
