import logging
import time

import numpy as np
import pytest
from unittest.mock import MagicMock
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.core.recognizers.pixel_stat import PRESET_TOP


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


class _NoSleepTime:
    """只吞掉 sleep 的 time 替身。`time()` 保持真实——_launch 用它盖 rally_id。"""

    def __init__(self, real):
        self._real = real
        self.sleeps = []

    def sleep(self, s):
        self.sleeps.append(s)

    def time(self):
        return self._real.time()


@pytest.fixture(autouse=True)
def _fast_time(monkeypatch):
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    # 等级回读的重读间隔在单测里置 0。连点节奏现由 anti_detection 持有，
    # 而这里的 handle 是裸 MockHandleSource（不经过 JitteringHandleSource），
    # 所以没有真实睡眠。
    monkeypatch.setattr("rok_assistant.workers.leader_sm.time",
                        _NoSleepTime(time))


def _mock_rec(matched=True, center=(50, 50)):
    rec = MagicMock()
    rec.recognize.return_value.matched = matched
    rec.recognize.return_value.bbox = MagicMock(center=lambda: center)
    return rec


RECOGNIZER_IDS = ("map_btn", "search_icon", "tab_fortress", "level_plus",
                  "level_minus", "search_btn", "red_rally", "toast_no_fortress",
                  "rally_attack_popup", "blue_rally", "preset_1",
                  "troop_cavalry", "march_btn", "war_title", "queue_panel",
                  "search_back", "ap_refill", "form_title", "replace_popup",
                  "queue_badge",   # 派遣队列徽标：发射验证用（默认在场）
                  "troop_infantry", "troop_archer")


def _make_sm(target_levels=(7,), wait=0.0):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _mock_rec() for k in RECOGNIZER_IDS}
    # 环境弹层默认不在场（专项测试再置 True）；其余弹层沿用上方默认
    # matched=True（rally_attack_popup 等在既有测试里被当作「已出现」依赖）
    recs["menu_expanded"] = _mock_rec(matched=False)   # 底部快捷菜单展开态
    recs["warning_panel"] = _mock_rec(matched=False)   # 「预警」警报面板
    recs["ap_refill"] = _mock_rec(matched=False)       # 行动力补充弹窗
    sm = LeaderStateMachine(handle, recs, target_levels=list(target_levels),
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
    sm, handle = _make_sm(target_levels=[3])
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
    sm, handle = _make_sm(target_levels=[7])
    for _ in range(3):   # 走到 SELECT_LEVEL：首轮全量 12 降 + 6 升
        sm.step()
        if sm.current == "SELECT_LEVEL":
            break
    base = handle.clicks.count((50, 50))
    assert base == 1 + 1 + 18   # search_icon + tab_fortress + 18 次等级点击

    sm2 = LeaderStateMachine(handle, {k: _mock_rec() for k in RECOGNIZER_IDS},
                             target_levels=[7], march_preset=1,
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
                             target_levels=[3], march_preset=1,
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
    # 单元素列表 = 旧行为：no_result_count 1..5 都走重试，第 5 次之后重试
    # guard（count < 5）失败、降级 guard 又因没有下一个等级而失败，于是走
    # END —— 恰好 5 次 CHECK_RESULT，不会更多
    assert sm.history.count("CHECK_RESULT") == 5
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
    sm, handle = _make_sm(target_levels=[3])
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


def test_launch_publishes_char_id_for_tracker():
    # publisher_id（factory 传 character.id）随事件带出：either_sm 的进程级
    # 集结事件登记簿靠它区分「自己/对方」的集结
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    events = []
    bus.subscribe("rally_launched", lambda p: events.append(p))
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _mock_rec() for k in RECOGNIZER_IDS}
    recs["menu_expanded"] = _mock_rec(matched=False)
    recs["warning_panel"] = _mock_rec(matched=False)
    recs["ap_refill"] = _mock_rec(matched=False)
    sm = LeaderStateMachine(handle, recs, target_levels=[7], march_preset=1,
                            march_troop_types=["cavalry"], event_bus=bus,
                            wait_members_seconds=0.0, publisher_id="char_jy")
    for _ in range(30):
        sm.step()
        if sm.is_terminal():
            break
    assert events[0]["char_id"] == "char_jy"


def test_silent_rejection_gives_up_without_waking_members():
    # 2026-09-18 run11 实锤：同联盟两号锁步向同一城寨开集结，后发者被
    # 游戏**静默拒绝**（表单关闭、无 toast、无队列徽标）。行军点击后
    # 徽标一直不出现 → 走 LAUNCH→END 放弃边，绝不发布 rally_launched
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    events = []
    bus.subscribe("rally_launched", lambda p: events.append(p))
    sm, handle = _make_sm()
    sm._bus = bus
    recs = sm._rec
    recs["queue_badge"].recognize.return_value.matched = False  # 徽标永不出场
    steps = 0
    while not sm.is_terminal() and steps < 40:
        sm.step()
        steps += 1
    assert sm.current == "END"
    assert sm._ctx.get("fail_reason") == "rally_rejected"
    assert sm.last_rally_event is None
    assert events == []
    # 放弃边直达 END，绝不进入等待成员阶段虚假吊着
    assert "WAIT_MEMBERS" not in sm.history


def test_launch_refills_ap_and_reclicks_march():
    # 2026-09-18 实机 run9：行军点击时行动力不足弹「行动力补充」（86/140），
    # 集结根本没发起却照旧发布事件 → 成员白等一轮。须补体力（每日免费
    # 500 领取 + 初级恢复 100）后补点行军，确认发出才发布事件
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    events = []
    bus.subscribe("rally_launched", lambda p: events.append(p))
    sm, handle = _make_sm()
    sm._bus = bus
    recs = sm._rec
    res = recs["ap_refill"].recognize.return_value
    calls = {"n": 0}

    def _ap(img):
        # 行军点击后弹窗出现，补体力两次 _find 内保持在场，点完「使用」
        # 后消失 —— 真实弹窗由 X 循环关掉
        calls["n"] += 1
        res.matched = 1 <= calls["n"] <= 3
        return res

    recs["ap_refill"].recognize.side_effect = _ap
    steps = 0
    while not sm.is_terminal() and steps < 60:
        sm.step()
        steps += 1
    assert (1448, 379) in handle.clicks   # 每日免费 500「领取」
    assert (1447, 570) in handle.clicks   # 第二行「使用」（紧急50/初级100）
    assert events != []                    # 补点行军后事件正常发布


def test_launch_closes_leftover_ap_dialog_before_march():
    # 2026-09-18 run10 实机：行动力补充弹窗残留盖住 march_btn，_launch
    # 先找行军只会一路异常，永远走不到补体力分支。入口必须先清弹窗
    sm, handle = _make_sm()
    recs = sm._rec
    res = recs["ap_refill"].recognize.return_value
    res.matched = True   # 入口即有弹窗残留；X 点击后消失

    def _ap(img):
        res.matched = (1638, 120) not in handle.clicks   # X 点击后消失
        return res

    recs["ap_refill"].recognize.side_effect = _ap
    steps = 0
    while not sm.is_terminal() and steps < 60:
        sm.step()
        steps += 1
    assert (1638, 120) in handle.clicks   # 弹窗被 X 关闭
    assert sm.last_rally_event is not None   # 关掉后行军照常发起


_MARCH_PT = (77, 88)   # 唯一化行军点击坐标


def _unique_march_point(sm):
    """把 march_btn 的点击坐标从默认 (50,50) 挪开。_make_sm 里所有 mock 的
    bbox 中心都是 (50,50)（`test_happy_path…` 就在数这个总数），不挪就没法
    只数行军点击。"""
    sm._rec["march_btn"].recognize.return_value.bbox = MagicMock(
        center=lambda: _MARCH_PT)


def _ap_popup_by_march_click(handle, res, reappear_until):
    """造「行军点击弹行动力不足、补体力关掉、再点行军又弹」的假弹窗。

    弹窗可见当且仅当：最近一次「行军(_MARCH_PT) / X(1638,120)」点击是行军，
    且行军被点次数 <= reappear_until（模拟 AP 还没补够）。领每日/使用
    这类中间点击不动弹窗状态。"""
    march = _MARCH_PT

    def _ap(img):
        n = sum(1 for c in handle.clicks if c == march)
        last = None
        for c in handle.clicks:
            if c in (march, (1638, 120)):
                last = c
        res.matched = last == march and n <= reappear_until
        return res

    return _ap


def test_launch_refills_ap_repeatedly_until_march_goes_out():
    # 2026-10-04 实机 ×3：补一次体力后点行军**又**弹「行动力不足」（AP 仍
    # 不够），原实现直接抛 `行动力补充后 march_btn 点击失败`，全靠 runner
    # 退避重试才恢复。现在应自己再补再点，直到行军真正发出去。
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    events = []
    bus.subscribe("rally_launched", lambda p: events.append(p))
    sm, handle = _make_sm()
    sm._bus = bus
    _unique_march_point(sm)
    res = sm._rec["ap_refill"].recognize.return_value
    # 前两次行军点击都弹窗，第三次才发出去 → 需要补两轮体力
    sm._rec["ap_refill"].recognize.side_effect = _ap_popup_by_march_click(
        handle, res, reappear_until=2)
    steps = 0
    while not sm.is_terminal() and steps < 60:
        sm.step()
        steps += 1
    assert events != []                                  # 最终发出去了
    assert handle.clicks.count(_MARCH_PT) == 3           # 行军点了 3 次
    assert handle.clicks.count((1448, 379)) == 2         # 补了 2 轮体力（每日领取）


def test_launch_gives_up_after_ap_refill_cap():
    # 体力真耗尽（补不动）时不能无限补：补满 _AP_REFILL_MAX 次仍点不出行军
    # → 放弃本轮（交给 runner 连续失败计数停机），而不是死循环
    import rok_assistant.workers.leader_sm as leader_sm
    # 值本身也要钉住：否则把常量改回 3 全绿（2026-10-09 复核发现）
    assert leader_sm._AP_REFILL_MAX == 8
    sm, handle = _make_sm()
    _unique_march_point(sm)
    res = sm._rec["ap_refill"].recognize.return_value
    # 弹窗永远复现：怎么补都不够
    sm._rec["ap_refill"].recognize.side_effect = _ap_popup_by_march_click(
        handle, res, reappear_until=99)
    with pytest.raises(
            RuntimeError,
            match=f"行动力补充 {leader_sm._AP_REFILL_MAX} 次后 march_btn 仍点不出去"):
        sm._launch({})
    # 行军点到上限就放弃（不死循环）；第 1 轮入口无残留弹窗 → 少补一次
    assert handle.clicks.count(_MARCH_PT) == leader_sm._AP_REFILL_MAX
    assert handle.clicks.count((1448, 379)) == leader_sm._AP_REFILL_MAX - 1


# ---- 预设槽选中态确认（2026-09-27）-----------------------------------------
# 旧实现 `self._click(f"preset_{N}")` 是盲点：返回值丢掉，模板失配=空操作
# （用游戏默认兵种）、模板串位=派错兵，两种都静默。现在点完必须确认高亮
# 移到了槽 N。判据是像素统计（selected_preset_N 识别器），几何实测钉死：
# cx=1655、cy=474+82*(N-1)。

_GEOM_X = 1655          # 预设列中心（实测）
_SLOT1_Y = 474          # 槽 1 中心（实测）


class _VerifyRec:
    """`selected_preset_N` 的替身。`mode` 决定它什么时候认账。"""

    def __init__(self, handle, mode="always"):
        self._h, self._mode = handle, mode
        self.calls = 0

    def recognize(self, img):
        self.calls += 1
        if self._mode == "always":
            ok = True
        elif self._mode == "never":
            ok = False
        elif self._mode == "after_geometry_click":
            # 只有出现过按实测几何点槽心的兜底点击才认账
            ok = any(x == _GEOM_X for x, _ in self._h.clicks)
        else:
            raise AssertionError(self._mode)
        r = MagicMock()
        r.matched = ok
        r.bbox = MagicMock(center=lambda: (_GEOM_X, _SLOT1_Y))
        return r


def _sm_with_verifier(mode, monkeypatch):
    sm, handle = _make_sm()
    rec = _VerifyRec(handle, mode)
    sm._rec["selected_preset_1"] = rec
    return sm, handle, rec


def test_select_preset_confirms_with_one_click(monkeypatch):
    """正常路径：模板点击即确认——**只点一次**，不引入额外点击。"""
    sm, handle, _rec = _sm_with_verifier("always", monkeypatch)

    sm._select_preset()

    assert handle.clicks == [(50, 50)], "模板命中且确认通过时不该多点"


def test_select_preset_falls_back_to_measured_geometry(monkeypatch):
    """模板失配（点击空操作）→ 按实测槽心几何兜底点一次，确认通过。"""
    sm, handle, _rec = _sm_with_verifier("after_geometry_click", monkeypatch)

    sm._select_preset()

    assert (_GEOM_X, _SLOT1_Y) in handle.clicks, "没有走几何兜底点击"
    assert len(handle.clicks) == 2, f"期望 模板1 + 几何1，实得 {handle.clicks}"


def test_select_preset_logs_which_path_confirmed(monkeypatch, caplog):
    """确认成功也必须进日志——否则实机只能靠「没抛异常」反推。

    旧实现的毛病就是「两种失败都静默」；成功再静默一次，等于把静默从失败
    挪到成功上，实机跑一轮根本分不清「模板确认了」和「几何兜底救回来的」。
    """
    sm, _h, _rec = _sm_with_verifier("always", monkeypatch)
    with caplog.at_level(logging.INFO):
        sm._select_preset()
    assert "预设槽 1 已确认（模板点击" in caplog.text

    sm2, _h2, _rec2 = _sm_with_verifier("after_geometry_click", monkeypatch)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        sm2._select_preset()
    assert "预设槽 1 已确认（几何补点" in caplog.text


def test_select_preset_raises_when_never_confirmed(monkeypatch):
    """3 轮都不确认 → 抛异常（runner 捕获后重试），绝不派错兵。"""
    sm, handle, _rec = _sm_with_verifier("never", monkeypatch)

    with pytest.raises(RuntimeError, match="预设槽 1 高亮未确认"):
        sm._select_preset()

    assert len(handle.clicks) == 6, "3 轮 × (模板 + 几何) = 6 次"


def test_select_preset_keeps_blind_click_without_verifier(monkeypatch):
    """没有 selected_preset_N 识别器 → 退回旧的盲点行为（不加验证、不抛）。

    manifest 没写 pixel_stats 的部署、以及 happy-path 的 26 击断言都靠这条。
    """
    sm, handle = _make_sm()
    assert "selected_preset_1" not in sm._rec

    sm._select_preset()

    assert handle.clicks == [(50, 50)]


# ---- 预设列基准自校准（2026-10-03 实机）-----------------------------------
# 实机：面板整体上移 42px（槽心 474 -> 432），march_btn/form_title 分毫未动，
# 写死的基准读不到高亮 -> 每轮 3 次确认全失败 -> worker 连错 6 次收工。
# 修法：用 preset_N 模板命中的位置反推基准。

def test_calibrate_preset_column_derives_the_base_from_the_template_hit():
    """命中位置就是槽 N 的槽心 -> 槽 1 基准 = y_hit，槽 2 基准 = y_hit-82。"""
    sm, _handle = _make_sm()
    hit = MagicMock()
    hit.bbox.center.return_value = (1655, 430)

    sm._calibrate_preset_column(hit, 1)
    assert sm._preset_base == 430

    sm._calibrate_preset_column(hit, 2)
    assert sm._preset_base == 430 - 82


def test_calibrate_preset_column_ignores_hits_outside_the_column():
    """列外的命中不是预设图标（manifest roi 是 x 1600..1712），别拿它定基准。"""
    sm, _handle = _make_sm()
    hit = MagicMock()
    hit.bbox.center.return_value = (50, 50)

    sm._calibrate_preset_column(hit, 1)

    assert sm._preset_base == PRESET_TOP


def test_calibrate_preset_column_pushes_the_base_into_the_judge():
    """校准必须传到判据上——否则点击按新基准、确认还按旧基准取样。"""
    sm, _handle = _make_sm()
    rec = MagicMock()
    sm._rec["selected_preset_1"] = rec
    hit = MagicMock()
    hit.bbox.center.return_value = (1655, 430)

    sm._calibrate_preset_column(hit, 1)

    rec.calibrate.assert_called_once_with(430)


def test_select_preset_self_calibrates_on_a_moved_panel():
    """实机回归：面板上移 42px 时，走真判据也必须确认通过。

    合成帧里槽 1 高亮在 cy=432（写死 474 的旧实现读不到，会抛异常），
    模板命中也在 432 -> 自校准 -> 确认通过。
    """
    from rok_assistant.core.recognizers.pixel_stat import (
        PRESET_HALF, PresetSlotJudge, build_preset_recognizers, slot_center)

    img = np.full((1080, 1920, 3), 30, np.uint8)
    cx, cy = slot_center(1, top=432.0)
    img[int(cy) - PRESET_HALF:int(cy) + PRESET_HALF,
        int(cx) - PRESET_HALF:int(cx) + PRESET_HALF] = 255

    handle = MockHandleSource(screenshot=img)
    recs = {k: _mock_rec() for k in RECOGNIZER_IDS}
    recs["preset_1"] = _mock_rec(center=(1655, 432))
    recs.update(build_preset_recognizers(["selected_preset_1"],
                                         PresetSlotJudge()))
    sm = LeaderStateMachine(handle, recs, target_levels=[7], march_preset=1,
                            march_troop_types=["cavalry"], event_bus=None,
                            wait_members_seconds=0.0)

    sm._select_preset()

    assert sm._preset_base == 432
    assert handle.clicks == [(1655, 432)], "确认通过时不该多点"


def test_form_troop_verifies_the_preset_before_troop_types(monkeypatch):
    """端到端：_form_troop 里确认失败会抛出，且**不会**继续点兵种。"""
    sm, handle, _rec = _sm_with_verifier("never", monkeypatch)

    with pytest.raises(RuntimeError, match="拒绝派错兵"):
        sm._form_troop({})

    # 所有 mock 都点在同一坐标，用**次数**区分：3 轮 × (模板 + 几何) = 6。
    # 多出来的就是 troop_* 点击——那意味着确认失败后还继续点兵种了。
    assert len(handle.clicks) == 6, \
        f"确认失败后不该继续点 troop_*（实得 {len(handle.clicks)} 次点击）"


# ---- 多等级搜索（2026-10-04）：某级搜不到就换列表里的下一个 ----

def _no_result_sm(levels, found_when=None):
    """造一个「搜不到」的车头。

    found_when 是判据回调，入参是共享 ctx；返回 True 才算搜到。默认永远
    搜不到。**不能按 recognize 调用次数判定**：每次 CHECK_RESULT 失败时
    _wait_for 会按 interval 重试 9 次（timeout 8.0 / interval 1.0），
    调用次数与「搜了几次」不是一回事。
    """
    sm, handle = _make_sm(target_levels=levels)

    def _recognize(_img):
        m = MagicMock()
        m.matched = bool(found_when and found_when(sm._ctx))
        m.bbox = MagicMock(center=lambda: (50, 50))
        return m

    sm._rec["red_rally"].recognize.side_effect = _recognize
    return sm, handle


def test_max_no_result_is_five():
    from rok_assistant.workers.leader_sm import _MAX_NO_RESULT
    assert _MAX_NO_RESULT == 5


def test_switch_to_next_level_resets_counter():
    """第一级搜满 5 次 → 换第二级，且计数清零（5 是每级额度，不是整轮）。"""
    sm, _handle = _no_result_sm([7, 5])
    steps = 0
    while sm.current != "END" and steps < 200:
        sm.step()
        steps += 1
        if sm._ctx.get("level_index") == 1:
            break
    assert sm._ctx.get("level_index") == 1
    assert sm._ctx.get("no_result_count") == 0
    assert not sm.is_terminal()


def test_full_cycle_over_three_levels_gives_up():
    """三个等级各 5 次 → 共 15 次搜索后放弃本轮（绕完一圈）。"""
    sm, _handle = _no_result_sm([6, 4, 5])
    steps = 0
    while not sm.is_terminal() and steps < 400:
        sm.step()
        steps += 1
    assert sm.is_terminal()
    assert sm.history.count("CHECK_RESULT") == 15
    assert sm._ctx.get("fail_reason") == "no_fortress_found"


def test_switch_order_follows_config_not_sorted():
    """顺序完全按配置：6→4→5 这种非降序也必须照走（用户明确要求）。"""
    from rok_assistant.workers.leader_sm import _LEVEL_CACHE
    sm, handle = _no_result_sm([6, 4, 5])
    seen = []
    steps = 0
    while not sm.is_terminal() and steps < 400:
        before = sm._ctx.get("level_index", 0)
        sm.step()
        steps += 1
        if sm._ctx.get("level_index", 0) != before:
            # 刚发生降级：_switch_level 里已调过 _select_level，缓存即当前级
            seen.append(_LEVEL_CACHE.get(handle))
    assert seen == [4, 5], f"降级顺序应为 4→5（实得 {seen}）"


def test_found_after_switch_launches_that_level():
    """降级后搜到城寨 → 发起的集结用的是**降级后**那一级。"""
    sm, _handle = _no_result_sm([7, 5], found_when=lambda ctx: ctx.get("level_index", 0) >= 1)
    steps = 0
    while not sm.is_terminal() and steps < 200:
        sm.step()
        steps += 1
    assert sm._ctx.get("level_index") == 1
    assert sm.last_rally_event["fortress_level"] == 5


# ---- 等级回读（2026-10-07）：读面板实际等级 → 点差量 → 回读校验 ----------
# 主路径不再盲降到底再升，而是读 manifest 的 fortress_level（Task 1/2）后只
# 点差量。读不出（旧配置 / OCR 失败 / 读到非 1..10）时逐字退回盲降。

from rok_assistant.core.recognizer import BBox, RecognizeResult


class _LevelStub:
    """假等级识别器：按调用顺序依次返回 levels，用尽后重复最后一个。
    None 表示读不出（matched=False）。"""

    def __init__(self, levels):
        self._levels = list(levels)
        self._i = 0

    def recognize(self, _img):
        lv = self._levels[min(self._i, len(self._levels) - 1)]
        self._i += 1
        if lv is None:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   data={"text": ""},
                                   recognizer_id="fortress_level")
        return RecognizeResult(
            matched=True, bbox=BBox(200, 520, 300, 545), confidence=0.9,
            data={"text": f"等级：{lv}", "value": str(lv)},
            recognizer_id="fortress_level")


def _make_sm_with_level(levels, target_levels=(7,)):
    """_make_sm + 注入 fortress_level 假识别器。"""
    sm, handle = _make_sm(target_levels=target_levels)
    sm._rec["fortress_level"] = _LevelStub(levels)
    return sm, handle


def _to_select_level(sm):
    sm.step()   # IDLE -> NORMALIZE
    sm.step()   # NORMALIZE -> SEARCH_FORTRESS
    sm.step()   # SEARCH_FORTRESS -> SELECT_LEVEL（执行 _select_level）


def test_select_level_skips_when_readback_equals_target():
    sm, handle = _make_sm_with_level([7], target_levels=(7,))
    _to_select_level(sm)
    # search_icon 1 + tab_fortress 1；一次 level_plus/minus 都没有
    assert len(handle.clicks) == 2


def test_select_level_clicks_exact_delta_up():
    # 读序 3 → 点 +3 → 回读 6：面板随点击变化，_LevelStub 按序返回
    sm, handle = _make_sm_with_level([3, 6], target_levels=(6,))
    _to_select_level(sm)
    # search_icon 1 + tab 1 + plus 3 = 5（不是固定 12+N）
    assert len(handle.clicks) == 5


def test_select_level_clicks_exact_delta_down():
    # 读序 9 → 点 -5 → 回读 4
    sm, handle = _make_sm_with_level([9, 4], target_levels=(4,))
    _to_select_level(sm)
    assert len(handle.clicks) == 1 + 1 + 5


def test_out_of_range_readback_falls_back_to_blind():
    sm, handle = _make_sm_with_level([15, 15, 15], target_levels=(7,))
    _to_select_level(sm)
    assert len(handle.clicks) == 1 + 1 + 12 + 6


def test_unreadable_level_falls_back_to_blind():
    sm, handle = _make_sm_with_level([None, None, None], target_levels=(7,))
    _to_select_level(sm)
    assert len(handle.clicks) == 1 + 1 + 12 + 6


def test_missing_recognizer_keeps_old_blind_behaviour():
    # 老配置 / 未更新 manifest：没有 fortress_level → 与改动前逐字相同
    sm, handle = _make_sm(target_levels=(7,))
    assert "fortress_level" not in sm._rec
    _to_select_level(sm)
    assert len(handle.clicks) == 1 + 1 + 12 + 6


def test_verify_corrects_a_lost_click():
    # 读序：初读 3 → 校验仍 3（点击被吞）→ 再校验 6（补点生效）
    sm, handle = _make_sm_with_level([3, 3, 6], target_levels=(6,))
    _to_select_level(sm)
    assert len(handle.clicks) == 1 + 1 + 3 + 3


def test_verify_gives_up_after_bounded_rounds_without_raising():
    sm, handle = _make_sm_with_level([3, 3, 3], target_levels=(6,))
    _to_select_level(sm)
    # 初读 3 + 两轮修正各 3 次，用尽 _LEVEL_VERIFY_ROUNDS 后只 warning
    assert len(handle.clicks) == 1 + 1 + 3 + 3 + 3
    assert not sm.is_terminal()


def test_readback_writes_cache_only_after_confirmation():
    from rok_assistant.workers.leader_sm import _LEVEL_CACHE
    sm, handle = _make_sm_with_level([6], target_levels=(6,))
    _to_select_level(sm)
    assert _LEVEL_CACHE.get(handle) == 6

    sm2, h2 = _make_sm_with_level([3, 3, 3], target_levels=(6,))
    _to_select_level(sm2)
    assert _LEVEL_CACHE.get(h2) is None      # 未确认 → 不写缓存


# ---- 多预设有序回退（2026-10-09）----

def _preset_sm(presets, selected_hits):
    """selected_hits: {预设号: 该槽的高亮识别器是否命中}。

    只给选中槽装 selected_preset_N 识别器，其余槽的 _rec.get 返回 None
    → 走「未配置判据」的盲点分支。这里刻意给全部槽都装，好让确认逻辑
    真的跑起来。
    """
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _mock_rec() for k in RECOGNIZER_IDS}
    recs["ap_refill"] = _mock_rec(matched=False)
    recs["menu_expanded"] = _mock_rec(matched=False)
    recs["warning_panel"] = _mock_rec(matched=False)
    for n in range(1, 6):
        recs[f"selected_preset_{n}"] = _mock_rec(matched=selected_hits.get(n, False))
    sm = LeaderStateMachine(handle, recs, target_levels=[7], event_bus=None,
                            wait_members_seconds=0.0, march_presets=presets)
    return sm, handle


def test_select_preset_falls_back_to_second_when_first_unconfirmed():
    """预设 1 高亮确认不了（返程中的主将载不出预设）→ 用预设 2 及其兵种。"""
    sm, _ = _preset_sm([(1, ["cavalry"]), (3, ["infantry"])], {3: True})
    assert sm._select_preset() == (3, ["infantry"])


def test_select_preset_uses_first_when_confirmed():
    sm, _ = _preset_sm([(2, ["archer"]), (4, ["infantry"])], {2: True, 4: True})
    assert sm._select_preset() == (2, ["archer"])


def test_select_preset_raises_when_all_unconfirmed():
    """全部确认不了仍抛异常（loud 失败不变）——绝不盲发一轮兵种不可信的集结。"""
    sm, _ = _preset_sm([(1, ["cavalry"]), (3, ["infantry"])], {})
    with pytest.raises(RuntimeError, match="高亮未确认"):
        sm._select_preset()


def test_form_troop_clicks_winning_preset_troops():
    """点的是**胜出预设自己**的兵种，不是全局兵种。"""
    sm, _ = _preset_sm([(1, ["cavalry"]), (3, ["infantry"])], {3: True})
    sm._rec["march_btn"] = _mock_rec(matched=True)
    ctx = {}
    sm._form_troop(ctx)
    assert ctx["used_preset"] == 3
    assert sm._rec["troop_infantry"].recognize.called
    assert not sm._rec["troop_cavalry"].recognize.called


def test_single_preset_keeps_legacy_constructor_path():
    """只传旧的 march_preset/march_troop_types 时，行为与改动前逐字相同。"""
    sm, _ = _make_sm()
    assert sm._march_presets == [(1, ["cavalry"])]


# ---- 体力补充：多口有界循环（2026-10-09）----

class _ScriptedRec:
    """按脚本返回 matched，用尽后保持最后一个值。"""

    def __init__(self, *flags):
        self._flags = list(flags)
        self.calls = 0

    def recognize(self, _img):
        i = min(self.calls, len(self._flags) - 1)
        self.calls += 1
        r = MagicMock()
        r.matched = self._flags[i]
        r.confidence = 1.0 if self._flags[i] else 0.0
        r.bbox = MagicMock(center=lambda: (50, 50))
        return r


def test_refill_ap_eats_multiple_items_in_one_call():
    """弹窗一直在（道具没吃完）→ 一口接一口，不是点一次就交给关窗。"""
    sm, handle = _make_sm()
    sm._rec["ap_refill"] = _ScriptedRec(True)
    assert sm._refill_ap() is False          # 关不掉（脚本里它一直在）
    used = [c for c in handle.clicks if c == (1447, 570)]
    assert len(used) == 3                    # _AP_EAT_MAX


def test_refill_ap_stops_early_when_dialog_closes():
    sm, handle = _make_sm()
    # 入口 _find True；循环第 1 口前的复查仍 True → 吃一口；吃完再查 False
    # → 停（Step 3 的循环是「先查后吃」，故这里第 2 个 flag 给 True）
    sm._rec["ap_refill"] = _ScriptedRec(True, True, False)
    assert sm._refill_ap() is True
    assert [c for c in handle.clicks if c == (1447, 570)] == [(1447, 570)]
