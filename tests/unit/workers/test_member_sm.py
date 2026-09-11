import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource


class _FakeTime:
    """Deterministic clock（同 test_leader_sm）：_wait_for/_click_retry 的
    轮询睡眠替换为瞬时推进，免测试烧真实秒数。"""

    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _mock_rec(matched=True):
    rec = MagicMock()
    rec.recognize.return_value.matched = matched
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    return rec


RECOGNIZER_IDS = ("search_back", "map_btn", "alliance_btn", "war_title",
                  "join_btn", "swap_btn", "march_btn", "fill_Boss",
                  "queue_panel", "join_create_btn", "rally_attack_popup",
                  "ap_refill")


def _make_sm():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _mock_rec() for k in RECOGNIZER_IDS}
    # 录桩（守卫用户要求 2026-09-09「填兵不使用预设」）：新链路点「+」即以
    # 默认部队出兵，preset_*/troop_* 识别器根本不应存在。基类 _find 用
    # .get() 取识别器，缺键只会静默 no-op 而非 KeyError，所以把假识别器
    # 塞进去靠「recognize 从未被调用」让回归大声失败。
    rec_preset = _mock_rec()
    rec_troop = _mock_rec()
    recs["preset_1"] = rec_preset
    recs["troop_cavalry"] = rec_troop
    # 集结进攻弹窗默认不在场（只有残留专项测试置 True）；默认 True 会让
    # 所有 normalize 链路多出一次 (960,540) 空地点击。ap_refill 同理
    recs["rally_attack_popup"] = _mock_rec(matched=False)
    recs["ap_refill"] = _mock_rec(matched=False)
    sm = MemberStateMachine(handle_source=handle, recognizers=recs,
                            fill_target_leaders=[{"instance": "i1", "name": "Boss"}])
    return sm, handle, rec_preset, rec_troop


def test_member_receives_event_and_joins_without_preset(monkeypatch):
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, rec_preset, rec_troop = _make_sm()
    # war_title 在旗帜被点击前不可见（真实时序）：点击后出现面板标题
    wres = sm._rec["war_title"].recognize.return_value

    def _wt(img):
        wres.matched = len(handle.clicks) > 0
        return wres

    sm._rec["war_title"].recognize.side_effect = _wt
    sm.on_rally_launched({"rally_id": "r1", "fortress_level": 8, "march_preset": 1})
    for _ in range(40):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    # 4 次点击：OPEN_WAR 点联盟旗帜(50,50) + CLICK_JOIN 点目标行的「+」
    # （mock 名字中心 (50,50) + 固定几何偏移 -> (1335, 161)）+ FORM_TROOP
    # 点「创建部队」气泡按钮 + LAUNCH 点行军(50,50)。真实链路（2026-09-12
    # 实机连拍实锤）：点「+」-> 派遣队列侧栏展开 +「创建部队」气泡 -> 点
    # 气泡蓝色按钮出表单 -> 点行军（默认兵队），swap_btn 出现即成功。
    assert handle.clicks == [(50, 50), (1335, 161), (50, 50), (50, 50)]
    assert "FORM_TROOP" in sm.history and "LAUNCH" in sm.history
    # 预设槽位与兵种图标从未被识别（识别必先于点击，未被识别即绝无点击）
    assert rec_preset.recognize.call_count == 0
    assert rec_troop.recognize.call_count == 0
    # launch 事件已被消费并留存
    assert sm._pending_event is None
    assert sm.last_event["rally_id"] == "r1"
    assert sm._ctx["joined"] is True


def test_join_click_without_swap_confirmation_reopens_panel(monkeypatch):
    # 点了「+」走到行军后 swap_btn 未出现（加入未生效）：必须重开列表重试
    # 而不是谎报成功 —— 旧代码盲进（点击失败不回读）是实机幻走事故的根源
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    sm.on_rally_launched({"rally_id": "r1"})
    sm._rec["swap_btn"].recognize.return_value.matched = False
    reached_click = False
    for _ in range(40):
        sm.step()
        if sm.current == "CLICK_JOIN":
            reached_click = True
        if reached_click and sm.current == "OPEN_WAR":
            break
    assert reached_click
    assert sm.current == "OPEN_WAR"   # 回流重开列表，而不是 END
    assert sm._ctx["joined"] is False
    assert sm._ctx.get("fail_reason") is None


def test_form_troop_missing_march_btn_reopens_panel(monkeypatch):
    # 点「+」后创建部队弹窗没出来（march_btn 15s 等不到）：回流重开列表，
    # 绝不能跳过表单直接宣布成功（用户实机确认 2026-09-11：加入需
    # 创建部队→行军两步）
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    sm.on_rally_launched({"rally_id": "r1"})
    sm._rec["march_btn"].recognize.return_value.matched = False
    reached_form = False
    for _ in range(40):
        sm.step()
        if sm.current == "FORM_TROOP":
            reached_form = True
        if reached_form and sm.current == "OPEN_WAR":
            break
    assert reached_form
    assert sm.current == "OPEN_WAR"
    assert sm._ctx["form_open"] is False
    # 「+」一次点击 + 「创建部队」气泡按钮（表单仍没出来）+ _join_missed
    # 的清残留空地点击（960,300）；行军从未被点过
    assert handle.clicks == [(1335, 161), (50, 50), (960, 300)]


def test_normalize_exits_search_then_finds_flag(monkeypatch):
    # 搜索面板开着时联盟旗帜不可见（搜索模式专属底栏）：先点 search_back
    # 退出 —— 2026-09-11 实机发现。旗帜始终不出现时应 RuntimeError
    # （环境异常走 runner 错误路径），而不是静默继续
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    recs = sm._rec
    recs["alliance_btn"].recognize.return_value.matched = False
    recs["war_title"].recognize.return_value.matched = False   # 无面板残留
    recs["queue_panel"].recognize.return_value.matched = False  # 无侧栏展开
    sm.on_rally_launched({"rally_id": "r1"})
    try:
        for _ in range(10):
            sm.step()
    except RuntimeError as e:
        assert "联盟旗帜不可见" in str(e)
    else:
        raise AssertionError("应当抛 RuntimeError 而不是静默继续")
    # 唯一一次点击是 search_back（map_btn 在 elif 分支未被触达）
    assert handle.clicks == [(50, 50)]


def test_normalize_collapses_queue_sidebar(monkeypatch):
    # 派遣队列侧栏展开态盖掉整个底部栏（2026-09-11 实机 mumu1 卡死态）：
    # 归一化须先点侧栏外空地收起（含「创建部队」气泡），再走 map_btn 回图
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    recs = sm._rec
    recs["war_title"].recognize.return_value.matched = False
    recs["search_back"].recognize.return_value.matched = False
    # 点空地回到城市视图 -> 点 map_btn 回地图后旗帜才可见（真实时序）
    ares = recs["alliance_btn"].recognize.return_value

    def _ab(img):
        ares.matched = len(handle.clicks) >= 2   # 收起 + map_btn 之后
        return ares

    recs["alliance_btn"].recognize.side_effect = _ab
    sm.on_rally_launched({"rally_id": "r1"})
    for _ in range(6):
        sm.step()
        if sm.current == "OPEN_WAR":
            break
    assert sm.current == "OPEN_WAR"
    # 收起侧栏空地 + map_btn 回地图 + OPEN_WAR 点联盟旗帜
    assert handle.clicks == [(1550, 320), (50, 50), (50, 50)]


def test_poll_exhaustion_exits_to_end_with_failure_marker(monkeypatch):
    # 列表开着但始终没有绿「+」：轮询耗尽后 give-up（no_rally_found），
    # runner 冷却重建重试 —— 与旧 FILTER 耗尽语义一致
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    sm.on_rally_launched({"rally_id": "r1"})
    sm._rec["fill_Boss"].recognize.return_value.matched = False
    for _ in range(120):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    assert sm._ctx["failed"] is True
    assert sm._ctx["fail_reason"] == "no_rally_found"
    assert sm.history.count("FIND_JOIN") == 62   # 1 次进入 + 61 步（60 自环 + 耗尽出边各记一次）


def test_failed_join_clears_stale_match_and_repolls(monkeypatch):
    # 加入失败回流后必须清掉 join_found/target_click 再重新轮询：
    # 不清会用陈旧坐标无限点击、计数器冻结、永不重算（2026-09-11 实机
    # 事故：两台各空转 40+ 轮「点击加入集结」）。回归判据：目标行只在
    # 首轮被真匹配时点过一次「+」；目标消失后经轮询耗尽正常终态
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    sm.on_rally_launched({"rally_id": "r1"})
    # 首轮：名字匹配成功走到点「+」；行军按钮等不到（表单失败回流）
    sm._rec["march_btn"].recognize.return_value.matched = False
    reached_click = False
    for _ in range(30):
        sm.step()
        if sm.current == "CLICK_JOIN":
            reached_click = True
        if reached_click and sm.current == "OPEN_WAR":
            break
    assert reached_click
    # 回流后目标行消失：不得再点第二次「+」，必须走轮询并耗尽
    sm._rec["fill_Boss"].recognize.return_value.matched = False
    for _ in range(130):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    assert sm._ctx["failed"] is True
    assert sm._ctx["fail_reason"] == "no_rally_found"
    assert handle.clicks.count((1335, 161)) == 1   # 陈旧坐标没有被再次点击


def test_normalize_dismisses_leftover_rally_popup(monkeypatch):
    # 集结进攻弹窗残留（either 角色上轮被杀在选时间步，2026-09-12 实机
    # mumu1）：模态弹窗压住 HUD，归一化须点空地关闭
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    recs = sm._rec
    recs["alliance_btn"].recognize.return_value.matched = False
    recs["war_title"].recognize.return_value.matched = False
    recs["queue_panel"].recognize.return_value.matched = False
    recs["rally_attack_popup"].recognize.return_value.matched = True
    # 弹窗被点掉后地图视图旗帜可见（真实时序）
    ares = recs["alliance_btn"].recognize.return_value

    def _ab(img):
        ares.matched = len(handle.clicks) >= 1
        return ares

    recs["alliance_btn"].recognize.side_effect = _ab
    sm.on_rally_launched({"rally_id": "r1"})
    for _ in range(5):
        sm.step()
        if sm.current == "OPEN_WAR":
            break
    assert sm.current == "OPEN_WAR"
    # 弹窗空地关闭 + OPEN_WAR 点联盟旗帜
    assert handle.clicks == [(960, 540), (50, 50)]
