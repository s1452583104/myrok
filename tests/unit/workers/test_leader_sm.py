import numpy as np
import pytest
from unittest.mock import MagicMock
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.core.handle_source import MockHandleSource


class _FakeTime:
    """Deterministic clock. state_machine helpers sleep on timeout retries;
    replacing its `time` module makes _wait_for/_click_retry advance instantly
    instead of burning real seconds in tests.

    Patches `state_machine.time` ONLY. `leader_sm.time` is intentionally NOT
    patched: with wait_members_seconds=0.0 the _wait_members sleep loop is
    skipped entirely, and _launch's time.time() only stamps rally_id."""

    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture(autouse=True)
def _fast_time(monkeypatch):
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    # 等级连点防丢的停顿在单测里置 0，免真实睡眠
    monkeypatch.setattr("rok_assistant.workers.leader_sm._LEVEL_CLICK_PACE", 0.0)


def _mock_rec(matched=True):
    rec = MagicMock()
    rec.recognize.return_value.matched = matched
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    return rec


RECOGNIZER_IDS = ("map_btn", "search_icon", "tab_fortress", "level_plus",
                  "level_minus", "search_btn", "red_rally", "toast_no_fortress",
                  "rally_attack_popup", "blue_rally", "preset_1",
                  "troop_cavalry", "march_btn", "war_title", "queue_panel",
                  "search_back", "ap_refill", "form_title", "replace_popup")


def _make_sm(target_level=7, wait=0.0):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _mock_rec() for k in RECOGNIZER_IDS}
    # 环境弹层默认不在场（专项测试再置 True）；其余弹层沿用上方默认
    # matched=True（rally_attack_popup 等在既有测试里被当作「已出现」依赖）
    recs["menu_expanded"] = _mock_rec(matched=False)   # 底部快捷菜单展开态
    recs["warning_panel"] = _mock_rec(matched=False)   # 「预警」警报面板
    sm = LeaderStateMachine(handle, recs, target_level=target_level,
                            march_preset=1, march_troop_types=["cavalry"],
                            event_bus=None, wait_members_seconds=wait)
    return sm, handle


def test_happy_path_reaches_end_and_publishes():
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    events = []
    bus.subscribe("rally_launched", lambda p: events.append(p))
    sm, handle = _make_sm()
    sm._bus = bus
    for _ in range(30):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    assert len(events) == 1
    assert events[0]["fortress_level"] == 7
    assert sm.last_rally_event["march_preset"] == 1
    # real flow must have clicked red_rally (the fixed bug: old code never did)
    # exact click count, all mocks center (50,50): search_icon 1 +
    # tab_fortress 1 + level_minus 12 + level_plus 6 + search_btn 1 +
    # red_rally 1 + blue_rally 1 + preset_1 1 + troop_cavalry 1 +
    # march_btn 1 = 26
    assert handle.clicks.count((50, 50)) == 26


def test_select_level_resets_with_minus_then_plus():
    sm, handle = _make_sm(target_level=3)
    sm.step()  # IDLE -> NORMALIZE (search_icon visible: no map_btn click)
    sm.step()  # NORMALIZE -> SEARCH_FORTRESS (1 click on search_icon)
    sm.step()  # SEARCH_FORTRESS -> SELECT_LEVEL (tab + minus*12 + plus*2 = 15 clicks)
    sm.step()  # SELECT_LEVEL -> CONFIRM_SEARCH (1 click on search_btn)
    # actions fire on the edge into the next state: 1 + 15 + 1 = 17
    assert len(handle.clicks) == 17


def test_select_level_reuses_cached_level():
    # 等级缓存：同一句柄第二轮只点差量；等级已是目标则零点击
    # （2026-09-11 验收反馈：每轮 12 降 + N 升太慢）
    from rok_assistant.workers.leader_sm import _LEVEL_CACHE
    sm, handle = _make_sm(target_level=7)
    for _ in range(3):   # 走到 SELECT_LEVEL：首轮全量 12 降 + 6 升
        sm.step()
        if sm.current == "SELECT_LEVEL":
            break
    base = handle.clicks.count((50, 50))
    assert base == 1 + 1 + 18   # search_icon + tab_fortress + 18 次等级点击

    sm2 = LeaderStateMachine(handle, {k: _mock_rec() for k in RECOGNIZER_IDS},
                             target_level=7, march_preset=1,
                             march_troop_types=["cavalry"])
    assert _LEVEL_CACHE.get(handle) == 7
    for _ in range(3):
        sm2.step()
        if sm2.current == "SELECT_LEVEL":
            break
    # 第二轮：等级已是 7 → 只有 search_icon + tab_fortress 两次点击
    assert handle.clicks.count((50, 50)) == base + 2

    # 目标变化时只点差量：7 → 3 为 4 次 minus
    sm3 = LeaderStateMachine(handle, {k: _mock_rec() for k in RECOGNIZER_IDS},
                             target_level=3, march_preset=1,
                             march_troop_types=["cavalry"])
    for _ in range(3):
        sm3.step()
        if sm3.current == "SELECT_LEVEL":
            break
    assert handle.clicks.count((50, 50)) == base + 2 + 2 + 4


def test_no_result_toast_retries_then_ends():
    sm, handle = _make_sm()
    recs = sm._rec
    recs["red_rally"].recognize.return_value.matched = False  # no detail popup ever
    steps = 0
    while not sm.is_terminal() and steps < 60:
        sm.step()
        steps += 1
    assert sm.is_terminal()
    # cap math: no_result_count 1,2,3 then the retry guard (count < 3) fails
    # and CHECK_RESULT takes the END edge — exactly 3 entries, never 4
    assert sm.history.count("CHECK_RESULT") == 3
    assert sm._ctx.get("failed") is True  # give_up sets the member_sm convention
    assert sm._ctx.get("fail_reason") == "no_fortress_found"


def test_locked_fortress_dismisses_and_researches():
    sm, handle = _make_sm()
    recs = sm._rec
    # red_rally visible (detail popup there) but rally_attack_popup never
    # appears => locked: dismiss at empty ground, renormalize, re-search
    recs["rally_attack_popup"].recognize.return_value.matched = False
    steps = 0
    while not sm.is_terminal() and steps < 120:
        sm.step()
        steps += 1
    assert sm.is_terminal()  # locked_count cap reached -> END, no infinite loop
    assert sm._ctx.get("locked_count") == 5
    assert sm._ctx.get("fail_reason") == "locked_fortress"
    assert (960, 540) in handle.clicks  # empty-ground dismiss taps happened


def test_failed_march_click_does_not_publish():
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    events = []
    bus.subscribe("rally_launched", lambda p: events.append(p))
    sm, handle = _make_sm()
    sm._bus = bus
    sm._rec["march_btn"].recognize.return_value.matched = False
    steps = 0
    with pytest.raises(RuntimeError):
        while not sm.is_terminal() and steps < 30:
            sm.step()
            steps += 1
    # a failed march_btn click must never wake members
    assert events == []
    assert sm.last_rally_event is None


def test_normalize_closes_leftover_war_panel(monkeypatch):
    # 战争列表开着会盖住左下角按钮（成员阶段回流/上一轮残留）：
    # 归一化必须先点面板右上角 X（1671,64）再继续 —— 2026-09-11 实机
    # 首跑 mumu1 因此异常循环
    sm, handle = _make_sm()
    recs = sm._rec
    recs["search_icon"].recognize.return_value.matched = False
    recs["queue_panel"].recognize.return_value.matched = False   # 无侧栏展开
    try:
        for _ in range(5):
            sm.step()
    except RuntimeError:
        pass   # 后续 search 仍会失败（search_icon 恒不可见），只看面板被关
    assert (1671, 64) in handle.clicks


def test_normalize_collapses_queue_sidebar(monkeypatch):
    # 派遣队列侧栏展开态盖掉整个底部栏（2026-09-11 实机 mumu1 卡死态）：
    # 归一化须先点侧栏外空地收起，再走 map_btn 回地图
    sm, handle = _make_sm()
    recs = sm._rec
    recs["search_icon"].recognize.return_value.matched = False
    recs["war_title"].recognize.return_value.matched = False
    try:
        for _ in range(5):
            sm.step()
    except RuntimeError:
        pass   # 后续 search 仍会失败（search_icon 恒不可见），只看侧栏被收
    assert (1550, 320) in handle.clicks


def test_normalize_exits_leftover_search_panel(monkeypatch):
    # 搜索面板残留（上轮进程被杀在搜索中，2026-09-12 实机 mumu0）：
    # 搜索模式专属底栏盖掉 map_btn，归一化必须先点 search_back 退搜索
    sm, handle = _make_sm()
    recs = sm._rec
    recs["search_icon"].recognize.return_value.matched = False
    recs["war_title"].recognize.return_value.matched = False
    recs["queue_panel"].recognize.return_value.matched = False
    recs["rally_attack_popup"].recognize.return_value.matched = False  # 无弹窗残留
    recs["ap_refill"].recognize.return_value.matched = False   # 无行动力弹窗
    recs["form_title"].recognize.return_value.matched = False  # 无表单残留
    recs["replace_popup"].recognize.return_value.matched = False  # 无替换弹窗
    recs["map_btn"].recognize.return_value.matched = False   # 退搜索后已在地图视图
    # search_back 点击后搜索面板关闭、地图视图 search_icon 可见（真实时序）
    sres = recs["search_back"].recognize.return_value

    def _sb(img):
        sres.matched = not handle.clicks
        return sres

    recs["search_back"].recognize.side_effect = _sb
    ires = recs["search_icon"].recognize.return_value

    def _si(img):
        ires.matched = len(handle.clicks) >= 1
        return ires

    recs["search_icon"].recognize.side_effect = _si
    for _ in range(4):
        sm.step()
        if sm.current == "SEARCH_FORTRESS":
            break
    assert sm.current == "SEARCH_FORTRESS"
    # search_back（归一化）+ search_icon（进入 SEARCH_FORTRESS 的动作）；
    # map_btn 未被点（真实地图视图不匹配）
    assert handle.clicks == [(50, 50), (50, 50)]


def test_normalize_collapses_expanded_bottom_menu(monkeypatch):
    # 底部快捷菜单展开态（战役/道具/联盟/统帅/邮件，2026-09-15 实机
    # mumu0 00:20 成员阶段六连异常收工）：展开时联盟旗帜按钮被整体隐藏，
    # 归一化须先点右下角 ☰（1845,1010，实测再点一次即收起）
    sm, handle = _make_sm()
    recs = sm._rec
    recs["search_icon"].recognize.return_value.matched = False
    recs["war_title"].recognize.return_value.matched = False
    recs["queue_panel"].recognize.return_value.matched = False
    recs["rally_attack_popup"].recognize.return_value.matched = False
    recs["ap_refill"].recognize.return_value.matched = False
    recs["form_title"].recognize.return_value.matched = False
    recs["replace_popup"].recognize.return_value.matched = False
    recs["menu_expanded"].recognize.return_value.matched = True
    recs["warning_panel"].recognize.return_value.matched = False
    try:
        for _ in range(5):
            sm.step()
    except RuntimeError:
        pass   # 后续 search 仍会失败（search_icon 恒不可见），只看菜单被收
    assert (1845, 1010) in handle.clicks


def test_normalize_closes_warning_panel(monkeypatch):
    # 「预警」面板（增援/来攻警报，游戏会在警报触发时自动弹出，2026-09-15
    # 实机 mumu1 00:09 六连异常收工）：全屏模态盖住一切，归一化须点右上角
    # X（1671,64，与战争列表同位）再继续
    sm, handle = _make_sm()
    recs = sm._rec
    recs["search_icon"].recognize.return_value.matched = False
    recs["war_title"].recognize.return_value.matched = False
    recs["queue_panel"].recognize.return_value.matched = False
    recs["rally_attack_popup"].recognize.return_value.matched = False
    recs["ap_refill"].recognize.return_value.matched = False
    recs["form_title"].recognize.return_value.matched = False
    recs["replace_popup"].recognize.return_value.matched = False
    recs["warning_panel"].recognize.return_value.matched = True
    try:
        for _ in range(5):
            sm.step()
    except RuntimeError:
        pass   # 后续 search 仍会失败（search_icon 恒不可见），只看面板被关
    assert (1671, 64) in handle.clicks


def test_no_result_invalidates_level_cache_and_resyncs_on_retry():
    # 等级缓存失步自愈：plus 连点被游戏丢失后缓存停在目标值、面板低 1 级，
    # 「跳过调整」永远搜错等级（2026-09-12 实机 mumu0：缓存 7 实际 6，
    # 连续 9 搜全空 -> 断路器停机）。无结果必须清缓存，重试前全量重同步
    from rok_assistant.workers.leader_sm import _LEVEL_CACHE, _LEVEL_CACHE_LOCK
    sm, handle = _make_sm(target_level=3)
    with _LEVEL_CACHE_LOCK:
        _LEVEL_CACHE[handle] = 3   # 假缓存：声称已是目标等级
    recs = sm._rec
    recs["red_rally"].recognize.return_value.matched = False
    ctx = {}
    sm._check_result(ctx)
    assert ctx["search_outcome"] == "no_result"
    with _LEVEL_CACHE_LOCK:
        assert _LEVEL_CACHE.get(handle) is None    # 缓存已被清
    sm._retry_search(ctx)
    # tab_fortress 1 + 降底 12 + 升到 3 级 2 + search_btn 1 = 16 次点击
    assert len(handle.clicks) == 16
