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
                  "ap_refill", "form_title", "replace_popup")


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
    recs["form_title"] = _mock_rec(matched=False)
    recs["replace_popup"] = _mock_rec(matched=False)
    recs["menu_expanded"] = _mock_rec(matched=False)   # 底部快捷菜单展开态
    recs["warning_panel"] = _mock_rec(matched=False)   # 「预警」警报面板
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


def test_normalize_closes_war_panel_residual_and_confirms_map(monkeypatch):
    # 2026-09-18 实机（run6 03:46 mumu0）：成员轮空放弃后战争面板残留，
    # 点 X 后面板有关闭过渡，紧接的检查在淡出中全落空 → 归一化超时抛
    # 「联盟旗帜不可见」连续计败。关面板后须等放大镜现形（地图视图
    # 确认）才算归一化成功，而不是继续往下走死路
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    recs = sm._rec
    recs["search_icon"] = _mock_rec(matched=False)
    recs["alliance_btn"].recognize.return_value.matched = False  # 无集结：旗帜不在
    recs["war_title"].recognize.return_value.matched = True   # 面板残留
    si = recs["search_icon"].recognize.return_value

    def _si(img):
        si.matched = bool(handle.clicks)   # 点过 X（面板已关）后才现形
        return si

    recs["search_icon"].recognize.side_effect = _si
    sm.on_rally_launched({"rally_id": "r1"})
    for _ in range(6):
        sm.step()
        if sm.current == "OPEN_WAR":
            break
    assert handle.clicks[0] == (1671, 64)   # 关了战争面板
    assert sm.current == "OPEN_WAR"          # 归一化成功进入下一步，未抛异常


def test_normalize_closes_form_title_residual_and_confirms_map(monkeypatch):
    # 2026-09-18 实机（run7 04:24 mumu0，失败截图 form_title=1.000）：
    # 创建部队表单残留时点一次 X 就往下走，淡出未完/首点未生效，后续
    # 检查全在模态底下落空 → 归一化抛「联盟旗帜不可见」连续计败。
    # 须关一次确认一次：表单还开着才补点 X，放大镜现形（地图视图确认）
    # 即归一化成功
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    recs = sm._rec
    recs["search_icon"] = _mock_rec(matched=False)
    recs["alliance_btn"].recognize.return_value.matched = False  # 无集结：旗帜不在
    recs["war_title"].recognize.return_value.matched = False     # 仅表单残留
    recs["queue_panel"].recognize.return_value.matched = False   # 无侧栏展开
    ft = recs["form_title"].recognize.return_value
    ft.matched = True   # 表单残留；第一次点 X 只触发淡出、第二次才真关
    si = recs["search_icon"].recognize.return_value

    def _ft(img):
        ft.matched = len(handle.clicks) < 2
        return ft

    def _si(img):
        si.matched = len(handle.clicks) >= 2   # 表单真关了放大镜才现形
        return si

    recs["form_title"].recognize.side_effect = _ft
    recs["search_icon"].recognize.side_effect = _si
    sm.on_rally_launched({"rally_id": "r1"})
    for _ in range(6):
        sm.step()
        if sm.current == "OPEN_WAR":
            break
    assert handle.clicks[0] == (1671, 64)   # 首次关表单
    assert handle.clicks[1] == (1671, 64)   # 表单还开着 → 补点
    assert sm.current == "OPEN_WAR"          # 归一化成功进入下一步，未抛异常


def test_poll_join_reopens_panel_closed_mid_poll(monkeypatch):
    # 2026-09-18 实机 run8：战争列表在轮询中途被游戏关掉（自己参与的
    # 集结发车等），FIND_JOIN 对着关掉的列表空轮询，烧完 60 次加入窗口
    # 后 no_rally_found 停机。每拍须先确认列表还开着，没了就重开再找
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    recs = sm._rec
    wt = recs["war_title"].recognize.return_value
    wt.matched = False   # 列表已被游戏关掉
    fb = recs["fill_Boss"].recognize.return_value
    fb.matched = False   # 列表没开时名字列无从匹配

    def _wt(img):
        wt.matched = len(handle.clicks) > 0   # 点过旗帜（重开）后列表现形
        return wt

    def _fb(img):
        fb.matched = len(handle.clicks) > 0
        return fb

    recs["war_title"].recognize.side_effect = _wt
    recs["fill_Boss"].recognize.side_effect = _fb
    sm._ctx["panel_open"] = True   # 直接进入 FIND_JOIN 轮询态
    sm.current = "FIND_JOIN"
    for _ in range(4):
        sm.step()
        if sm.current in ("CLICK_JOIN", "VERIFY_JOINED"):
            break
    assert (50, 50) in handle.clicks       # 重开：点了联盟旗帜
    assert (1335, 161) in handle.clicks    # 重开后找到目标行点了「+」
    assert sm._ctx["join_found"] is True


def test_verify_join_refills_ap_when_popup_blocks_march(monkeypatch):
    # 2026-09-18 实机 run9：加入行军点击时行动力不足（86/140），游戏弹
    # 「行动力补充」挡住一切，加入永远不生效 → 历次「连续 3 轮失败（疑似
    # 体力耗尽）」停机根因。须补体力（每日免费 500 领取 + 初级恢复 100）
    # 而非关弹窗 —— 关掉只会让加入继续失败，10 轮目标必须吃道具
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    recs = sm._rec
    recs["ap_refill"].recognize.return_value.matched = True   # 弹窗在场
    recs["war_title"].recognize.return_value.matched = False
    recs["swap_btn"].recognize.return_value.matched = False   # 行军没生效
    sm._ctx["marched"] = True
    sm.current = "VERIFY_JOINED"
    for _ in range(3):
        sm.step()
        if sm.current == "OPEN_WAR":
            break
    assert (1448, 379) in handle.clicks   # 每日免费 500「领取」
    assert (1447, 745) in handle.clicks   # 初级行动力恢复 100「使用」
    assert (1638, 120) in handle.clicks   # mock 里弹窗关不掉 → X 兜底
    assert sm._ctx["joined"] is False      # 本拍按加入未生效回流重试


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


def test_already_joined_replace_popup_skips_to_verify(monkeypatch):
    # 部队已在目标集结中：点「+」弹「部队替换」确认而非创建部队（2026-09-13
    # 实机 mumu0）。不替换、不点行军，直接走 VERIFY_JOINED 回读橙「替换」
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    sm.on_rally_launched({"rally_id": "r1"})
    # 点「+」后（CLICK_JOIN 之后）替换弹窗出现；VERIFY_JOINED 时 swap 可见
    rres = sm._rec["replace_popup"].recognize.return_value

    def _rp(img):
        rres.matched = handle.clicks.count((1335, 161)) >= 1   # 点过「+」后
        return rres

    sm._rec["replace_popup"].recognize.side_effect = _rp
    for _ in range(40):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    assert sm._ctx.get("already_joined") is True
    assert sm._ctx["joined"] is True
    # 行军从未被点过：替换会白回城还多烧行动力
    march_rec = sm._rec["march_btn"]
    assert march_rec.recognize.call_count == 0
    # 替换弹窗被 X 关闭（1500,170）
    assert (1500, 170) in handle.clicks


def test_normalize_dismisses_leftover_replace_popup(monkeypatch):
    # 部队替换弹窗残留（进程被杀在弹窗上，2026-09-13 实机 mumu0）：
    # 归一化须点弹窗右上角 X（1500,170）再继续
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    recs = sm._rec
    recs["alliance_btn"].recognize.return_value.matched = False
    recs["war_title"].recognize.return_value.matched = False
    recs["queue_panel"].recognize.return_value.matched = False
    recs["replace_popup"].recognize.return_value.matched = True
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
    assert handle.clicks == [(1500, 170), (50, 50)]


def test_normalize_collapses_expanded_bottom_menu(monkeypatch):
    # 底部快捷菜单展开态（战役/道具/联盟/统帅/邮件，2026-09-15 实机
    # mumu0 00:20 六连异常收工）：展开时联盟旗帜按钮被整体隐藏，归一化
    # 须先点右下角 ☰（1845,1010，实测再点一次即收起）再找旗帜
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    recs = sm._rec
    recs["alliance_btn"].recognize.return_value.matched = False
    recs["war_title"].recognize.return_value.matched = False
    recs["queue_panel"].recognize.return_value.matched = False
    mres = recs["menu_expanded"].recognize.return_value

    def _me(img):
        mres.matched = (1845, 1010) not in handle.clicks   # 点 ☰ 后收起
        return mres

    recs["menu_expanded"].recognize.side_effect = _me
    # 菜单收起后地图视图旗帜可见（真实时序）
    ares = recs["alliance_btn"].recognize.return_value

    def _ab(img):
        ares.matched = (1845, 1010) in handle.clicks
        return ares

    recs["alliance_btn"].recognize.side_effect = _ab
    sm.on_rally_launched({"rally_id": "r1"})
    for _ in range(6):
        sm.step()
        if sm.current == "OPEN_WAR":
            break
    assert sm.current == "OPEN_WAR"
    # 收起菜单点 ☰（收起后本就在地图视图）+ OPEN_WAR 点联盟旗帜
    assert handle.clicks == [(1845, 1010), (50, 50)]


def test_normalize_closes_warning_panel(monkeypatch):
    # 「预警」面板（增援/来攻警报，游戏会在警报触发时自动弹出，2026-09-15
    # 实机 mumu1 00:09 六连异常收工）：全屏模态盖住一切，归一化须点右上角
    # X（1671,64，与战争列表同位）再继续
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    sm, handle, _, _ = _make_sm()
    recs = sm._rec
    recs["alliance_btn"].recognize.return_value.matched = False
    recs["war_title"].recognize.return_value.matched = False
    recs["queue_panel"].recognize.return_value.matched = False
    wres = recs["warning_panel"].recognize.return_value

    def _wp(img):
        wres.matched = (1671, 64) not in handle.clicks   # 点 X 后关闭
        return wres

    recs["warning_panel"].recognize.side_effect = _wp
    # 面板被关掉后地图视图旗帜可见（真实时序：面板本就弹在地图视图上）
    ares = recs["alliance_btn"].recognize.return_value

    def _ab(img):
        ares.matched = (1671, 64) in handle.clicks
        return ares

    recs["alliance_btn"].recognize.side_effect = _ab
    sm.on_rally_launched({"rally_id": "r1"})
    for _ in range(6):
        sm.step()
        if sm.current == "OPEN_WAR":
            break
    assert sm.current == "OPEN_WAR"
    # 关面板点 X + OPEN_WAR 点联盟旗帜（地图视图，map_btn 不点）
    assert handle.clicks == [(1671, 64), (50, 50)]
