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
    # 车头错峰抖动置 0：单测不烧真实睡眠；抖动专项测试自行覆盖
    monkeypatch.setattr("rok_assistant.workers.either_sm.random.uniform",
                        lambda a, b: 0.0)


def _mock_rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec


def _make_sm(fill_targets=None, bus=None, human=None):
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
                            target_levels=[8], march_preset=1,
                            march_troop_types=["infantry"],
                            fill_target_leaders=fill_targets or [],
                            event_bus=bus, human=human)
    # red_rally 独立 mock：give-up 测试只关掉详情弹窗的命中，
    # 不影响共享 rec 的其他识别器
    recs["red_rally"] = _mock_rec()
    return sm


def _badge_lights_on_launch(sm, state=None):
    """queue_badge 语义化 mock：轮次入口不可见（无队列在外 → 门槛放行），
    行军点击后（发射已完成，clicks ≥ 10）点亮（派遣队列被本轮集结占用）
    —— leader 的发射验证依赖徽标出现才承认发射成功；state["forced"]
    非 None 时以它为准（WAIT_RETURN 阶段由测试显式控制出/回城）。"""
    handle = sm._leader._handle
    badge = _mock_rec()
    sm._leader._rec["queue_badge"] = badge
    res = badge.recognize.return_value

    def _b(_img):
        if state is not None and state["forced"] is not None:
            res.matched = state["forced"]
        else:
            res.matched = len(handle.clicks) >= 10
        return res

    badge.recognize.side_effect = _b


class _SeqTracker:
    """集结事件登记簿桩：last_foreign_launch/skip 按预定序列逐次返回。
    门槛在 IDLE/NORMALIZE 各查一次、降级判定再查一次，序列可精确编排
    「门槛时无对方集结、发射被拒时对方集结已到」的真实竞态时序。"""

    def __init__(self, launches=(), skips=()):
        self._launches = list(launches)
        self._skips = list(skips)

    def last_foreign_launch(self, char_id, max_age):
        return self._launches.pop(0) if self._launches else None

    def last_foreign_skip(self, char_id, max_age):
        return self._skips.pop(0) if self._skips else None


class _HoldTracker:
    """恒定返回固定值的登记簿桩（稳定态查询用）。"""

    def __init__(self, foreign=None, skip=None):
        self.foreign = foreign
        self.skip = skip

    def last_foreign_launch(self, char_id, max_age):
        return self.foreign

    def last_foreign_skip(self, char_id, max_age):
        return self.skip


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


def test_member_exhaust_downgrades_when_own_rally_in_flight():
    # member FILTER 耗尽但自己的集结已发起且部队在途（leader 正常发射）：
    # 对方无集结可填是轮空而非失败（fail_streak 会误触连续失败停机
    # —— 2026-09-18 run11 实锤），弹出 fail_reason 按完成处理
    sm = _make_sm(fill_targets=[{"instance": "i1", "name": "Boss"}])
    sm._ctx["war_attempts"] = 11
    for _ in range(200):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    assert sm.current == "MEMBER:END"
    assert sm._leader.last_rally_event is not None
    assert sm.fail_reason is None
    assert sm._ctx.get("failed") is None


def test_last_image_delegates_to_active_phase():
    sm = _make_sm()
    assert sm.last_image is None  # 尚未运行
    # 门槛 QueueGate 需连续 VOTE_SIZE 帧同结论才放行（2026-09-30）：前两拍
    # 停在 IDLE 不委托 leader，故多走两拍才到 NORMALIZE 并捕获首帧
    for _ in range(3):
        sm.step()
    assert sm.current == "LEADER:NORMALIZE"
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
    state = {"forced": None}
    _badge_lights_on_launch(sm, state)   # 轮次入口不可见，发射后点亮
    for _ in range(200):
        sm.step()
        if sm.current == "WAIT_RETURN":
            break
    assert sm.current == "WAIT_RETURN", f"未进入返城等待: {sm.history[-5:]}"
    state["forced"] = True   # 填兵出发：徽标点亮
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
    state["forced"] = False   # 部队回城
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
    _badge_lights_on_launch(sm)   # 入口不可见（无队列在外），发射后点亮
    for _ in range(200):
        sm.step()
        if sm.current == "WAIT_RETURN":
            break
    _FakeTime.t += 60
    sm.step()   # war_title 可见：点 X 并返回，不得就此判「已回城」
    assert sm.current == "WAIT_RETURN"
    assert not sm.is_terminal()
    assert (1671, 64) in sm._leader._handle.clicks


def test_wait_return_gather_only_queue_does_not_block(monkeypatch):
    # 徽标只说明「有队列在城外」：采集队在外同样点亮徽标（2026-09-13 实机
    # mumu1 一队采集在外空等 25 分钟）。队列头像右下角图标区分：绿色锄头=
    # 采集、绿色脚印=行军、蓝色旗帜=驻扎/集结等待。无战斗队列图标在外
    # （仅采集）不阻塞开集结 —— 立即终态进下一轮
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    sm._leader._rec["queue_badge"] = badge
    for icon in ("queue_march_icon", "queue_flag_icon"):
        rec = _mock_rec()
        rec.recognize.return_value.matched = False   # 仅采集：无战斗队列图标
        sm._leader._rec[icon] = rec
    gather = _mock_rec()
    gather.recognize.return_value.matched = True   # 采集锄头图标可见
    sm._leader._rec["queue_gather_icon"] = gather
    wt = _mock_rec()
    wt.recognize.return_value.matched = False
    sm._leader._rec["war_title"] = wt
    for _ in range(200):
        sm.step()
        if sm.current == "WAIT_RETURN":
            break
    assert sm.current == "WAIT_RETURN"
    _FakeTime.t += 60
    sm.step()   # 徽标在但仅采集在外：本轮完成，不空等
    assert sm.is_terminal()
    assert sm.current == "MEMBER:END"


def test_wait_return_march_queue_still_waits(monkeypatch):
    # 徽标在、绿色脚印（行军中）在外：保持等待不终态
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    state = {"forced": None}
    _badge_lights_on_launch(sm, state)   # 轮次入口不可见，发射后点亮
    march = _mock_rec()   # 行军队在外：绿色脚印图标可见
    march.recognize.return_value.matched = False
    sm._leader._rec["queue_march_icon"] = march
    flag = _mock_rec()
    flag.recognize.return_value.matched = False
    sm._leader._rec["queue_flag_icon"] = flag
    for _ in range(200):
        sm.step()
        if sm.current == "WAIT_RETURN":
            break
    assert sm.current == "WAIT_RETURN"
    state["forced"] = True   # 填兵出发：徽标点亮
    # war_title 与 test_wait_return_polls 同理：进入 WAIT_RETURN 后再换成
    # 不匹配实例 —— 提前换会让 member _open_war 每拍真实 _wait_for(6s)，
    # 测试烧掉几十秒真实睡眠（2026-09-14 发现的既有测试 bug）
    wt = _mock_rec()
    wt.recognize.return_value.matched = False
    sm._leader._rec["war_title"] = wt
    march.recognize.return_value.matched = True   # 本轮集结部队行军中
    _FakeTime.t += 60
    sm.step()
    assert not sm.is_terminal()
    assert sm.current == "WAIT_RETURN"
    state["forced"] = False   # 部队回城：徽标消失
    _FakeTime.t += 60
    sm.step()
    assert sm.is_terminal()
    assert sm.current == "MEMBER:END"


def test_gate_blocks_search_while_march_queue_out(monkeypatch):
    # 2026-09-13 用户要求：上一轮集结部队未回城就搜下一轮，会搜到上轮
    # 已锁定的城寨且车头回不了城 —— 行军/驻扎队列在外时轮次入口
    # （IDLE/NORMALIZE）拦截，不进搜索；回城后放行
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    sm._leader._rec["queue_badge"] = badge
    march = _mock_rec()   # 上一轮集结部队还在城外
    sm._leader._rec["queue_march_icon"] = march
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"   # 门槛拦下：轮次根本没启动
    assert not any("SEARCH" in h for h in sm.history)
    badge.recognize.return_value.matched = False   # 部队回城：徽标消失
    march.recognize.return_value.matched = False
    for _ in range(30):
        sm.step()
        if sm.current == "LEADER:SEARCH_FORTRESS":
            break
    assert sm.current == "LEADER:SEARCH_FORTRESS"


def test_gate_closes_search_panel_covering_sidebar(monkeypatch):
    # 2026-09-16 实机（21:08 mumu1）：搜索面板开着时右侧队列栏同样整体
    # 隐藏（搜索模式专属底栏），门槛判 unknown 拦截却没关面板，白等
    # 15 分钟宽限。搜索面板残留也应主动退出（点 search_back）再判读
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    badge.recognize.return_value.matched = False   # 面板盖住队列栏
    sm._leader._rec["queue_badge"] = badge
    ab = _mock_rec()
    ab.recognize.return_value.matched = False      # 搜索底栏替换了底部栏
    sm._leader._rec["alliance_btn"] = ab
    si = _mock_rec()
    si.recognize.return_value.matched = False      # 搜索面板下放大镜同样不可见
    sm._leader._rec["search_icon"] = si
    wt = _mock_rec()
    wt.recognize.return_value.matched = False
    sm._leader._rec["war_title"] = wt
    rap = _mock_rec()
    rap.recognize.return_value.matched = False      # 无集结弹窗残留（城市假象剔除）
    sm._leader._rec["rally_attack_popup"] = rap
    sb = _mock_rec()   # 搜索面板开着（search_back 可见）
    sm._leader._rec["search_back"] = sb
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"
    assert not any("SEARCH" in h for h in sm.history)
    assert sm._leader._handle.clicks   # 门槛点过 search_back（bbox 中心）


def test_gate_clicks_city_exit_when_not_on_map(monkeypatch):
    # 2026-09-16 实机（21:16 重启后两号齐卡城市视图）：城市视图下队列栏
    # 不显示、alliance_btn/map_btn 均不匹配（map_btn 模板是地图视图的
    # 「进入城市」城堡按钮），门槛无动作可做白等 15 分钟宽限。城市视图
    # 的出城按钮（地图图标，实机 (72,1034)）须由门槛直接点击
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    badge.recognize.return_value.matched = False
    sm._leader._rec["queue_badge"] = badge
    for tid in ("alliance_btn", "search_icon", "war_title", "warning_panel",
                "search_back", "rally_attack_popup"):
        rec = _mock_rec()
        rec.recognize.return_value.matched = False
        sm._leader._rec[tid] = rec
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"
    assert (72, 1034) in sm._leader._handle.clicks   # 门槛点了出城按钮


def test_gate_allows_search_when_only_search_icon_proves_map(monkeypatch):
    # 2026-09-18 实机（01:46 mumu1 卡 WAIT_RETURN 25 分钟）：简化模式下
    # 联盟快捷键整体不显示（alliance_btn 干净地图上仅 0.248），部队明明
    # 已回城却因「不在地图视图」fail-closed 白等。search_icon 只在地图
    # 视图出现、全屏面板打开时同样被盖住，是等效的地图视图判据：
    # 徽标不可见 + 放大镜可见 = 队列确实为空，应放行搜索
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    badge.recognize.return_value.matched = False   # 无队列徽标
    sm._leader._rec["queue_badge"] = badge
    ab = _mock_rec()
    ab.recognize.return_value.matched = False      # 简化模式下联盟键不显示
    sm._leader._rec["alliance_btn"] = ab
    for tid in ("war_title", "warning_panel", "search_back"):
        rec = _mock_rec()
        rec.recognize.return_value.matched = False
        sm._leader._rec[tid] = rec
    # search_icon 保持默认 matched=True（地图视图放大镜可见）
    for _ in range(10):
        sm.step()
    assert any("SEARCH_FORTRESS" in h for h in sm.history)
    assert (72, 1034) not in sm._leader._handle.clicks   # 不在地图视图，无需出城


def test_gate_closes_form_title_residual(monkeypatch):
    # 2026-09-18 实机（run4 02:04 mumu0）：上轮进程被杀在 FORM_TROOP，
    # 创建部队全屏模态残留盖住一切，门槛的关面板清单没有 form_title，
    # normalize 没机会跑 → 白等宽限期。门槛须自己关掉全屏模态
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    badge.recognize.return_value.matched = False   # 模态盖住队列栏
    sm._leader._rec["queue_badge"] = badge
    for tid in ("alliance_btn", "search_icon", "war_title", "warning_panel",
                "search_back"):
        rec = _mock_rec()
        rec.recognize.return_value.matched = False
        sm._leader._rec[tid] = rec
    ft = _mock_rec()   # 创建部队模态残留
    sm._leader._rec["form_title"] = ft
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"
    assert not any("SEARCH" in h for h in sm.history)
    assert (1671, 64) in sm._leader._handle.clicks   # 门槛主动关了模态


def test_gate_allows_search_when_only_gather_out(monkeypatch):
    # 仅采集队列在外：不阻塞搜索-集结（用户确认 1-3 队采集在外不影响）
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    sm._leader._rec["queue_badge"] = badge
    for icon in ("queue_march_icon", "queue_flag_icon"):
        rec = _mock_rec()
        rec.recognize.return_value.matched = False
        sm._leader._rec[icon] = rec
    gather = _mock_rec()
    gather.recognize.return_value.matched = True   # 采集锄头图标可见
    sm._leader._rec["queue_gather_icon"] = gather
    for _ in range(30):
        sm.step()
        if sm.current == "LEADER:SEARCH_FORTRESS":
            break
    assert sm.current == "LEADER:SEARCH_FORTRESS"


def test_gate_blocks_search_on_unknown_queue_icon(monkeypatch):
    # 2026-09-14 实机（mumu0 22:27:16）：徽标在但行军/旗帜/采集图标都
    # 不可辨 —— 旧实现放行，部队实际在别人集结里，照样开了第二个集结。
    # fail-closed：未知图标按「在外」处理，轮次入口拦截
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

        @classmethod
        def sleep(cls, s):
            cls.t += s

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    sm._leader._rec["queue_badge"] = badge
    for icon in ("queue_march_icon", "queue_flag_icon", "queue_gather_icon"):
        rec = _mock_rec()
        rec.recognize.return_value.matched = False
        sm._leader._rec[icon] = rec
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"   # 门槛拦下：轮次根本没启动
    assert not any("SEARCH" in h for h in sm.history)


def test_gate_panel_covering_badge_blocks(monkeypatch):
    # 2026-09-16 实机（重启后 mumu1/mumu0 双双误放行）：战争列表面板开着
    # 时右侧队列栏整体隐藏，queue_badge 判 False → 门槛误判「无队列在外」
    # 放行搜索，而填兵部队实际还在他人集结里。fail-closed：徽标不可见但
    # 已知覆盖面板（战争列表/预警/创建部队/集结弹窗/行动力）开着时按
    # unknown 处理，先归一化关面板再谈放行
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    badge.recognize.return_value.matched = False   # 面板盖住队列栏
    sm._leader._rec["queue_badge"] = badge
    ab = _mock_rec()
    ab.recognize.return_value.matched = False      # 面板也盖住联盟旗帜（不在地图视图）
    sm._leader._rec["alliance_btn"] = ab
    si = _mock_rec()
    si.recognize.return_value.matched = False      # 面板同样盖住放大镜（地图视图判据失效）
    sm._leader._rec["search_icon"] = si
    war = _mock_rec()   # 战争列表面板开着
    sm._leader._rec["war_title"] = war
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"
    assert not any("SEARCH" in h for h in sm.history)
    assert (1671, 64) in sm._leader._handle.clicks   # 门槛主动关了战争面板


def test_gate_unknown_queue_icon_proceeds_after_grace(monkeypatch):
    # 未知图标不能永久卡死调度：持续超过宽限期后放行（告警日志语义，
    # 行为上等价于 v1 的放行，但多了 5 分钟缓冲与记录）
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

        @classmethod
        def sleep(cls, s):
            cls.t += s

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime)
    # 宽限计时器自 2026-09-30 起由 QueueGate 持有，时钟在 queue_gate 模块：
    # 不替换它，FakeTime 的推进对门槛不可见，unknown 永不「超时」
    monkeypatch.setattr("rok_assistant.workers.queue_gate.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    sm._leader._rec["queue_badge"] = badge
    for icon in ("queue_march_icon", "queue_flag_icon", "queue_gather_icon"):
        rec = _mock_rec()
        rec.recognize.return_value.matched = False
        sm._leader._rec[icon] = rec
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"
    _FakeTime.t += 901.0   # 超过宽限期
    for _ in range(30):
        sm.step()
        if sm.current == "LEADER:SEARCH_FORTRESS":
            break
    assert sm.current == "LEADER:SEARCH_FORTRESS"


def test_wait_return_unknown_queue_icon_keeps_waiting(monkeypatch):
    # 2026-09-14 实机（mumu0 22:27:16 / mumu1 22:37:43）：徽标在但图标
    # 不可辨时旧实现误判「仅采集/已回城」提前终态。未知图标应继续等待
    # （WAIT_RETURN 有 25 分钟上限兜底，不会死等）
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

        @classmethod
        def sleep(cls, s):
            cls.t += s

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    state = {"forced": None}
    _badge_lights_on_launch(sm, state)   # 轮次入口不可见，发射后点亮
    for icon in ("queue_march_icon", "queue_flag_icon", "queue_gather_icon"):
        rec = _mock_rec()
        rec.recognize.return_value.matched = False
        sm._leader._rec[icon] = rec
    wt = _mock_rec()
    wt.recognize.return_value.matched = False
    sm._leader._rec["war_title"] = wt
    for _ in range(200):
        sm.step()
        if sm.current == "WAIT_RETURN":
            break
    assert sm.current == "WAIT_RETURN"
    state["forced"] = True   # 填兵出发：徽标点亮
    _FakeTime.t += 60
    sm.step()   # 徽标在但图标不可辨：继续等待，不提前终态
    assert not sm.is_terminal()
    assert sm.current == "WAIT_RETURN"


def test_gate_blocks_on_return_queue_icon(monkeypatch):
    # 2026-09-16 用户报告：预设槽 1 主将未回城（右侧队列黄色返回态图标）
    # 时照常发起集结，游戏让默认武将代开车，打不过寨子白烧行动力。
    # 黄色返回/红色战斗图标与行军/驻扎同属战斗队列 —— 必须按 battle
    # 拦截（无宽限放行），而不是 unknown（宽限一到就放行，正是本次事故）
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    sm._leader._rec["queue_badge"] = badge
    ret = _mock_rec()   # 黄色返回图标可见
    sm._leader._rec["queue_return_icon"] = ret
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"   # 门槛拦下：轮次根本没启动
    assert not any("SEARCH" in h for h in sm.history)
    _FakeTime.t += 901.0   # 越过 unknown 宽限期：battle 判定不受宽限影响
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"
    assert not any("SEARCH" in h for h in sm.history)


def test_gate_blocks_on_battle_queue_icon(monkeypatch):
    # 红色交叉刀剑（战斗中）图标：同上按战斗队列拦截（无宽限放行）
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    sm._leader._rec["queue_badge"] = badge
    bat = _mock_rec()   # 红色战斗图标可见
    sm._leader._rec["queue_battle_icon"] = bat
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"
    _FakeTime.t += 901.0
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"
    assert not any("SEARCH" in h for h in sm.history)


def test_gate_blocks_on_recall_queue_icon(monkeypatch):
    # 红盘白色上箭头（召回/取消集结撤回中）图标：战斗队列第五态，
    # 同样按 battle 拦截（无宽限放行）—— 2026-09-16 实机补采模板
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    sm._leader._rec["queue_badge"] = badge
    rec_ = _mock_rec()   # 召回图标可见
    sm._leader._rec["queue_recall_icon"] = rec_
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"
    _FakeTime.t += 901.0
    for _ in range(10):
        sm.step()
    assert sm.current == "LEADER:IDLE"
    assert not any("SEARCH" in h for h in sm.history)


def test_wait_return_return_queue_icon_keeps_waiting(monkeypatch):
    # 黄色返回态出现在 WAIT_RETURN：部队正在返程，继续等待不提前终态
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

        @classmethod
        def sleep(cls, s):
            cls.t += s

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    state = {"forced": None}
    _badge_lights_on_launch(sm, state)   # 轮次入口不可见，发射后点亮
    for icon in ("queue_march_icon", "queue_flag_icon", "queue_gather_icon"):
        rec = _mock_rec()
        rec.recognize.return_value.matched = False
        sm._leader._rec[icon] = rec
    wt = _mock_rec()
    wt.recognize.return_value.matched = False
    sm._leader._rec["war_title"] = wt
    for _ in range(200):
        sm.step()
        if sm.current == "WAIT_RETURN":
            break
    assert sm.current == "WAIT_RETURN"
    state["forced"] = True   # 填兵出发：徽标点亮
    sm._leader._rec["queue_return_icon"] = _mock_rec()   # 返程图标可见
    _FakeTime.t += 60
    sm.step()
    assert not sm.is_terminal()
    assert sm.current == "WAIT_RETURN"


def test_foreign_rally_gate_skips_own_launch():
    # 2026-09-18 run11 实锤：窗内对方已发起集结时，同一城寨再开集结会被
    # 游戏**静默拒绝**（表单关闭、无 toast、无队列徽标）。让车门槛：
    # 本轮跳过开集结，直接转成员流程填对方的集结，并发布 rally_skipped
    # （对方据其提前收尾成员阶段）
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    skips = []
    bus.subscribe("rally_skipped", lambda p: skips.append(p))
    sm = _make_sm(fill_targets=[{"instance": "i1", "name": "Boss"}], bus=bus)
    foreign = {"char_id": "other", "rally_id": "rally_1"}
    sm._tracker = _HoldTracker(foreign=foreign)
    for _ in range(200):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    # 本轮根本没进搜索-发射：门槛直接转填兵
    assert not any("SEARCH" in h for h in sm.history)
    assert not any(h == "LEADER:LAUNCH" for h in sm.history)
    assert skips == [{"char_id": sm._char_id}]
    assert sm._member.last_event is foreign


def test_rally_rejected_downgrades_when_foreign_rally_fresh(monkeypatch):
    # 自己的发射被静默拒绝且窗内对方确有集结（门槛查询时对方的还没到，
    # 降级判定时已到 —— run11 的真实竞态时序）：竞态输家轮空，不计失败
    # （fail_streak 会误触连续失败停机），冷却重建后由让车门槛转填兵
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

        @classmethod
        def sleep(cls, s):
            cls.t += s

    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime)
    sm = _make_sm(fill_targets=[])
    badge = _mock_rec()
    badge.recognize.return_value.matched = False   # 行军点击后徽标永不出现=被拒
    sm._leader._rec["queue_badge"] = badge
    foreign = {"char_id": "other", "rally_id": "rally_1"}
    sm._tracker = _SeqTracker(launches=[None, None, foreign])
    for _ in range(60):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    assert sm.current == "LEADER:END"
    assert sm._leader.last_rally_event is None
    assert sm.fail_reason is None            # 降级：失败标记已弹出
    assert sm._ctx.get("failed") is None
    assert not any(h.startswith("MEMBER:") for h in sm.history)


def test_member_short_circuits_on_foreign_skip(monkeypatch):
    # 对方发布过 rally_skipped（它转填了我方集结）：自己无集结可填，成员
    # 流程不再白烧 6 分钟轮询，直接提前转入返城等待（自己的集结部队在途）
    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

        @classmethod
        def sleep(cls, s):
            cls.t += s

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime)
    sm = _make_sm(fill_targets=[{"instance": "i1", "name": "Boss"}])
    _badge_lights_on_launch(sm)   # 入口不可见，发射后点亮 → 可进返城等待
    sm._tracker = _HoldTracker(skip={"char_id": "other"})
    for _ in range(200):
        sm.step()
        if sm.current == "WAIT_RETURN":
            break
    assert sm.current == "WAIT_RETURN"
    # 成员流程被跳过：没进过填兵轮询（对方无集结可填）
    assert not any("FIND_JOIN" in h for h in sm.history)
    assert sm.fail_reason is None


def test_either_sm_stores_injected_profile():
    # EitherStateMachine 没有基类，human 参数不会经 super().__init__ 落到
    # self._human —— 必须自行存储，否则返城检测拍的 self._human.jitter 会
    # AttributeError（brief 原文在此处判断错误）。
    from rok_assistant.infra.anti_detection import AntiDetectionConfig, HumanProfile
    prof = HumanProfile(AntiDetectionConfig(debug_no_jitter=True))
    sm = _make_sm(human=prof)
    assert sm._human is prof


def test_either_sm_wait_return_poll_goes_through_jitter(monkeypatch):
    # 返城徽标检测间隔必须经 profile.jitter(_WAIT_RETURN_POLL)，而不是把
    # 30.0 常量直接加到 _next_check —— 后者没有断言能察觉，去规律化落空。
    from rok_assistant.infra.anti_detection import AntiDetectionConfig, HumanProfile
    from rok_assistant.workers import either_sm as either_sm_mod

    class _FakeTime:
        t = 1000.0

        @classmethod
        def time(cls):
            return cls.t

        @classmethod
        def sleep(cls, s):
            cls.t += s

    monkeypatch.setattr("rok_assistant.workers.either_sm.time", _FakeTime)
    seen = []
    prof = HumanProfile(AntiDetectionConfig(debug_no_jitter=True))
    prof.jitter = MagicMock(side_effect=lambda base: (seen.append(base), 0.0)[1])
    sm = _make_sm(fill_targets=[], human=prof)
    _badge_lights_on_launch(sm)   # 入口不可见，发射后点亮 → 可进返城等待
    for _ in range(200):
        sm.step()
        if sm.current == "WAIT_RETURN":
            break
    assert sm.current == "WAIT_RETURN", f"未进入返城等待: {sm.history[-5:]}"
    # 只保留「检测拍」这一次 step 里的 jitter 调用，排除进等待前子状态机的
    # 其它抖动记录，断言更精确
    seen.clear()
    sm.step()   # 进入检测拍：_step_wait_return 走到 :260 的 _next_check 赋值
    assert either_sm_mod._WAIT_RETURN_POLL in seen, \
        f"返城检测间隔未经 jitter，记录={seen[:8]}"
