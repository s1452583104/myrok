"""宝石模式状态机单测。

两条贯穿全文件的约定：
  1. 时钟全部走 `Clock`（虚拟时间），**不烧真实秒数**——`_wait_for` 里
     最长的超时是 10s，真跑会把这一个文件拖成分钟级。
  2. 识别器**默认全灭**，按名字打开需要的——默认全亮会让归一化链路多出
     一串干扰点击，断言就没法读。
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock

import numpy as np
import pytest

from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.workers import gem_sm, state_machine


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)


@pytest.fixture
def clk(monkeypatch):
    c = Clock()
    for mod in (gem_sm, state_machine):
        monkeypatch.setattr(mod.time, "time", c.time)
        monkeypatch.setattr(mod.time, "sleep", c.sleep)
    return c


def _rec(matched=True, center=(50, 50)):
    r = MagicMock()
    r.recognize.return_value.matched = matched
    r.recognize.return_value.bbox = MagicMock(center=lambda: center)
    r.recognize.return_value.score = 1.0
    return r


def _rec_seq(*matched_values):
    """按调用次序依次返回 matched 的替身——用来演「点一下画面就变了」。

    末尾值会一直重复（调用次数不可预知时，最后一个值就是稳态）。
    """
    seq = list(matched_values)
    calls = {"n": 0}

    def side_effect(_img):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return _rec(seq[i]).recognize.return_value

    r = MagicMock()
    r.recognize.side_effect = side_effect
    return r


def _rec_at(*centers):
    """按调用次序返回**不同中心点**的识别器替身。

    模拟「拖了一格之后宝石换了个位置」——恒返回同一个中心的替身会让
    `_tried_gems` 永远命中同一个格，测试就再也走不出第二颗宝石。
    """
    seq = list(centers)
    calls = {"n": 0}

    def side_effect(_img):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return _rec(True, center=seq[i]).recognize.return_value

    r = MagicMock()
    r.recognize.side_effect = side_effect
    return r


ALL_IDS = ("search_icon", "alliance_btn", "map_btn", "queue_panel",
           "queue_badge", "queue_gather_icon", "queue_march_icon",
           "queue_flag_icon", "queue_battle_icon", "queue_return_icon",
           "net_error_confirm", "war_title", "form_title",
           "gem_icon", "gem_mine_zoom", "view_radial_menu",
           "view_btn_resource", "collect_dialog", "collect_btn",
           "back_from_detail", "join_create_btn", "march_btn",
           "gem_dialog_title")


def make_sm(clk, matched=(), **kw):
    handle = MockHandleSource(
        screenshot=np.zeros((1080, 1920, 3), dtype=np.uint8))
    recs = {k: _rec(k in matched) for k in ALL_IDS}
    sm = gem_sm.GemStateMachine(handle, recs, clock=clk.time,
                                sleeper=clk.sleep, rng=random.Random(0), **kw)
    return sm, handle, recs


def force_edges(sm, values):
    """把 `_edge_density` 换成按调用次序返回的序列（资源视角判据用）。

    直接换方法而不是造假图：`MockHandleSource` 给的是全零帧，Canny 边缘
    恒为 0，`after >= before * 1.5` 会**平凡通过**（0 >= 0），判据等于没测。
    """
    it = iter(values)
    last = values[-1]
    sm._edge_density = lambda: next(it, last)


def _to_scan(clk, matched):
    """把 SM 推到 SCAN 状态（各用例共用的开场）。

    5 拍：IDLE→NORMALIZE→COUNT_QUEUES→OPEN_RESOURCE_VIEW→SCAN（交接，只 reset）
    →SCAN 自环（第一拍扫图）。**宝石此时已经在手**（`matched` 里有 `gem_icon` 时），
    所以下一拍就是 SCAN → ZOOM_CONFIRM。
    """
    sm, handle, recs = make_sm(clk, matched=("alliance_btn", "view_radial_menu",
                                             "view_btn_resource", *matched))
    force_edges(sm, [0.02, 0.05])
    sm.step(); sm.step(); sm.step(); sm.step(); sm.step()
    assert sm.current == "SCAN"
    return sm, handle, recs


def _to_collect_dialog(clk, matched):
    """把 SM 推到 COLLECT_DIALOG 状态（双确认已通过）。

    `matched` 是**额外**要点亮的识别器；宝石链路那四个是固定开场。
    """
    sm, handle, recs = _to_scan(clk, ("gem_icon", "gem_mine_zoom",
                                      "collect_dialog", "gem_dialog_title",
                                      *matched))
    sm.step()                                       # SCAN -> ZOOM_CONFIRM
    sm.step()                                       # ZOOM_CONFIRM -> COLLECT_DIALOG
    assert sm.current == "COLLECT_DIALOG", sm.current
    assert sm.fail_reason is None
    return sm, handle, recs


def _to_click_collect(clk, matched):
    """推到 CLICK_COLLECT（采集框已受理，等着点蓝色「采集」按钮）。"""
    sm, handle, recs = _to_collect_dialog(clk, ("collect_btn", *matched))
    recs["collect_dialog"] = _rec_seq(False)        # 点采集后采集框消失
    sm.step()                                       # COLLECT_DIALOG -> CLICK_COLLECT
    assert sm.current == "CLICK_COLLECT", sm.current
    return sm, handle, recs


def _to_create_troop(clk, matched):
    """推到 CREATE_TROOP（`_create_troop` 已经点过气泡、等过表单）。"""
    sm, handle, recs = _to_click_collect(clk, matched)
    sm.step()                                       # CLICK_COLLECT -> CREATE_TROOP
    assert sm.current == "CREATE_TROOP", sm.current
    return sm, handle, recs


def test_starts_at_idle():
    sm, _, _ = make_sm(Clock())
    assert sm.current == "IDLE"
    assert not sm.is_terminal()


def test_normalize_returns_early_when_map_is_already_visible(clk):
    """地图视图的标志是右下角联盟旗帜可见——已在地图就一拍归一化完。"""
    sm, handle, _ = make_sm(clk, matched=("alliance_btn",))
    sm.step()
    assert sm.current == "NORMALIZE"
    assert handle.clicks == []          # 已经在地图上，一下都不该点
    assert sm.fail_reason is None


def test_normalize_clicks_away_a_leftover_troop_form(clk):
    """创建部队表单残留（全屏模态）盖住 HUD：点右上角 X 关掉再认。"""
    sm, handle, recs = make_sm(clk)
    # 表单被点掉之前一直在场；地图标志要等表单关掉才认得出
    recs["form_title"] = _rec_seq(True, False)
    recs["alliance_btn"] = _rec_seq(False, True)
    sm.step()                                   # IDLE -> NORMALIZE
    assert sm.current == "NORMALIZE"
    assert handle.clicks == [(1716, 69)]        # 点掉了表单的 X
    assert sm.fail_reason is None


def test_normalize_returns_from_city_view_via_map_button(clk):
    """城里（map_btn 可见、联盟旗帜不可见）→ 点「地图」按钮回地图视图。"""
    sm, handle, recs = make_sm(clk)
    # map_btn 要点两下才轮到点击：call1 = 归一化的 `_find` 守卫，
    # call2 = `_click` 内部那一次 `_find`（点击就发生在这一拍）
    recs["map_btn"] = _rec_seq(True, True, False)
    recs["alliance_btn"] = _rec_seq(False, True)
    sm.step()                                   # IDLE -> NORMALIZE
    assert handle.clicks == [(50, 50)]          # map_btn 的中心（替身固定返回）
    assert sm.current == "NORMALIZE"


def test_normalize_gives_up_cleanly_when_it_cannot_clean_up(clk):
    """收拾不出地图视图 → **干净中止本轮**，不是抛异常。

    抛异常会被 WorkerRunner 当成 step 失败：不重建 SM、退避重放，
    攒满 6 次直接停机（PROGRESS 已知问题 8/14）。
    """
    sm, _, _ = make_sm(clk)                     # 全灭：地图认不出来
    for _ in range(6):
        if sm.current == "END":
            break
        sm.step()
    assert sm.current == "END"
    assert sm.is_terminal()
    assert sm.fail_reason == state_machine.NORMALIZE_STUCK_REASON


def test_normalize_dismisses_net_error_at_the_measured_button(clk):
    """断网弹框要走基类的 `_click_net_error()`——落点是实测的 (960, 711)。

    这里钉的是**落点**：曾经写死成 (1638, 120)，那是行动力补充弹窗的 X，
    在 `net_error_confirm` 的 ROI [700,620,1220,800] **之外**。弹框点不掉时
    5 拍归一化全烧完、本轮以 `normalize_stuck` 中止——而它是环境类，
    不计入 runner 的连续失败，于是机器人会**静默地空转到天荒地老**。

    `_find` 调用次序（`_click_net_error` 自己那个有界循环也会查）：
      call1 = `_normalize_view` 的守卫
      call2 = `_click_net_error` 第 1 圈（在场 → 点一下）
      call3 = `_click_net_error` 第 2 圈（已消失 → 收手）
      call4 = `_normalize_view` 第 2 拍的守卫（已消失）
    """
    sm, handle, recs = make_sm(clk, matched=("alliance_btn",))
    recs["net_error_confirm"] = _rec_seq(True, True, False)
    sm.step()                                   # IDLE -> NORMALIZE
    assert (960, 711) in handle.clicks          # 点的是实测确认键，不是弹窗 X
    assert sm.current == "NORMALIZE"            # 弹框清掉后继续归一化
    assert sm.fail_reason is None               # 收拾干净了，没有 normalize_stuck


def test_count_queues_is_not_full_below_limit(clk):
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "queue_gather_icon",
                                     "queue_march_icon"))
    sm.step()                                   # IDLE -> NORMALIZE
    sm.step()                                   # NORMALIZE -> COUNT_QUEUES
    assert sm.current == "COUNT_QUEUES"
    ctx = sm._ctx
    assert ctx["queue_count"] == 2
    assert ctx["queues_full"] is False


def test_count_queues_full_at_limit(clk):
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "queue_gather_icon",
                                     "queue_march_icon", "queue_flag_icon",
                                     "queue_battle_icon", "queue_return_icon"))
    sm.step()
    sm.step()
    ctx = sm._ctx
    assert ctx["queue_count"] == 5
    assert ctx["queues_full"] is True


def test_count_queues_captures_only_one_frame(clk):
    """5 个队列图标识别器共用**一帧**。

    各走一次 `_find` 会截 5 帧，而 adb 每帧 150~300ms——真机上一轮要数十几次
    队列，这个差别是分钟级的。
    """
    sm, handle, recs = make_sm(clk, matched=("alliance_btn",))
    # 这两个识别器在 _count_queues 里各会被 _find 一次；去掉它们，截图次数
    # 就只剩「数图标」那一帧（`_find` 对没配的 id 直接返回 None，不截图）
    recs.pop("net_error_confirm")
    recs.pop("queue_badge")
    calls = {"n": 0}
    real = handle.capture

    def counted():
        calls["n"] += 1
        return real()

    handle.capture = counted
    sm.step()                                   # IDLE -> NORMALIZE
    before = calls["n"]
    sm.step()                                   # NORMALIZE -> COUNT_QUEUES
    assert calls["n"] - before == 1


def test_count_queues_without_any_icon_recognizer_aborts(clk):
    """一个 queue_*_icon 都没配 → queue_unknown 干净中止，**不能当成 0**。

    当成 0 会一路派兵到 march_rejected 才停，白烧一整轮。
    """
    sm, _, recs = make_sm(clk, matched=("alliance_btn",))
    for rid in gem_sm.QUEUE_ICON_IDS:
        recs.pop(rid)
    sm.step()
    sm.step()
    sm.step()                                   # COUNT_QUEUES -> END
    assert sm.current == "END"
    assert sm.fail_reason == gem_sm.QUEUE_UNKNOWN_REASON


def test_full_queue_enters_wait_and_wait_does_not_block(clk):
    """队列满 → 进 WAIT；WAIT 期间每拍空转，**不睡**（sleeper 不被调用）。"""
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "queue_gather_icon",
                                     "queue_march_icon", "queue_flag_icon",
                                     "queue_battle_icon", "queue_return_icon"))
    slept = []
    sm._sleep = lambda s: slept.append(s)
    sm.step()                                   # IDLE -> NORMALIZE
    sm.step()                                   # NORMALIZE -> COUNT_QUEUES
    sm.step()                                   # COUNT_QUEUES -> WAIT
    assert sm.current == "WAIT"
    assert sm._wait_deadline > clk.time()
    for _ in range(20):
        sm.step()
    assert sm.current == "WAIT"                 # 时间没到，一直停在这
    assert slept == []                          # 一拍都没睡


def test_wait_resumes_counting_after_deadline(clk):
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "queue_gather_icon",
                                     "queue_march_icon", "queue_flag_icon",
                                     "queue_battle_icon", "queue_return_icon"))
    sm.step()
    sm.step()
    sm.step()
    assert sm.current == "WAIT"
    clk.t = sm._wait_deadline + 1.0
    sm.step()                                   # WAIT -> COUNT_QUEUES
    assert sm.current == "COUNT_QUEUES"
    assert sm._ctx["waits_used"] == 1


def test_wait_window_is_inside_configured_range(clk):
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "queue_gather_icon",
                                     "queue_march_icon", "queue_flag_icon",
                                     "queue_battle_icon", "queue_return_icon"),
                       idle_wait_min=20, idle_wait_max=30)
    sm.step(); sm.step(); sm.step()
    span = sm._wait_deadline - clk.t
    assert 20 * 60 <= span <= 30 * 60


def test_second_full_reading_ends_the_round(clk):
    """等过一次还满 → 本轮结束（spec §6.4），**不是无限等**。"""
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "queue_gather_icon",
                                     "queue_march_icon", "queue_flag_icon",
                                     "queue_battle_icon", "queue_return_icon"))
    sm.step(); sm.step(); sm.step()             # -> WAIT
    clk.t = sm._wait_deadline + 1.0
    sm.step()                                   # WAIT -> COUNT_QUEUES
    sm.step()                                   # COUNT_QUEUES -> ROUND_DONE
    assert sm.current == "ROUND_DONE"
    sm.step()                                   # ROUND_DONE -> END
    assert sm.current == "END"
    assert sm.is_terminal()
    assert sm.fail_reason is None               # 队列满是正常收尾，不是失败


def test_count_queues_recounts_after_closing_net_error(clk):
    """断网弹框在场 → 关掉 → **本拍就地重数**，给出真实读数而非「未知」。

    `queue_count = -1` + `queues_full = False` 这一对同时表示「没满」和
    「读数未知」。Task 3.4 起 COUNT_QUEUES 有一条**无 guard** 的放行边，
    若弹框盖住队列栏时草草返回「未知」，那一拍会被当成「队列没满」直接
    放行去派兵 → march_rejected（真失败）。所以关掉弹框后必须重数。

    `_find("net_error_confirm")` 的真实调用次序（`_click_net_error` 自己
    有界循环 ≤3 次）：
      call1 = `_count_queues` 的守卫（在场 → 进分支）
      call2 = `_click_net_error` 第 1 圈（在场 → 点一下）
      call3 = `_click_net_error` 第 2 圈（已消失 → 收手）
      call4 = 关掉后的复核（已消失 → 就地重数）
    """
    sm, handle, recs = make_sm(clk, matched=("alliance_btn", "queue_gather_icon",
                                             "queue_march_icon", "queue_flag_icon",
                                             "queue_battle_icon", "queue_return_icon"))
    sm.step()                                   # IDLE -> NORMALIZE（此时无弹框）
    recs["net_error_confirm"] = _rec_seq(True, True, False, False)
    sm.step()                                   # NORMALIZE -> COUNT_QUEUES
    assert (960, 711) in handle.clicks          # 弹框走实测确认键点掉
    assert sm.current == "COUNT_QUEUES"
    ctx = sm._ctx
    assert ctx["queue_count"] == 5              # 真实读数，不是 -1
    assert ctx["queues_full"] is True
    assert sm.fail_reason is None               # 弹框关掉了，不是 queue_unknown


def test_count_queues_aborts_when_net_error_will_not_close(clk):
    """弹框关不掉 → 读数未知，干净中止（**不能**当成队列没满）。"""
    sm, _, recs = make_sm(clk, matched=("alliance_btn", "queue_gather_icon"))
    sm.step()                                   # IDLE -> NORMALIZE
    recs["net_error_confirm"] = _rec_seq(True)  # 一直在场，点不掉
    sm.step()                                   # NORMALIZE -> COUNT_QUEUES
    assert sm._ctx["fail_reason"] == gem_sm.QUEUE_UNKNOWN_REASON
    assert sm._ctx["queues_full"] is False
    sm.step()                                   # COUNT_QUEUES -> END
    assert sm.current == "END"
    assert sm.is_terminal()


def test_end_wait_recounts_in_place(clk):
    """WAIT 结束必须**就地重数**——不重数就会拿等之前的旧读数收本轮。

    判别性：等期间把 5 个队列图标都改成不命中（队列空出来了）。只有真的
    重数了，这一拍才会得到 0/不满；若 `_end_wait` 是空函数，ctx 里仍是等
    之前的 `queue_count=5 / queues_full=True`，本条即红。
    """
    sm, _, recs = make_sm(clk, matched=("alliance_btn", "queue_gather_icon",
                                        "queue_march_icon", "queue_flag_icon",
                                        "queue_battle_icon", "queue_return_icon"))
    sm.step(); sm.step(); sm.step()             # -> WAIT
    assert sm.current == "WAIT"
    for rid in gem_sm.QUEUE_ICON_IDS:
        recs[rid] = _rec(False)                 # 等期间队列空出来了
    clk.t = sm._wait_deadline + 1.0
    sm.step()                                   # WAIT -> COUNT_QUEUES（就地重数）
    assert sm.current == "COUNT_QUEUES"
    assert sm._ctx["queue_count"] == 0
    assert sm._ctx["queues_full"] is False
    sm.step()                                   # 不满 → 这一拍不收轮
    assert sm.current != "ROUND_DONE"


# ---- Task 3.4：进资源查看视角 ----


def test_long_press_then_click_resource_enters_scan(clk):
    """长按地图按钮 → 环形菜单 → 点「资源」→ 进 SCAN。"""
    sm, handle, _ = make_sm(clk, matched=("alliance_btn", "view_radial_menu",
                                          "view_btn_resource"))
    force_edges(sm, [0.02, 0.05])               # 进视角后边缘密度涨了 2.5 倍
    sm.step()                                   # IDLE -> NORMALIZE
    sm.step()                                   # NORMALIZE -> COUNT_QUEUES
    sm.step()                                   # COUNT_QUEUES -> OPEN_RESOURCE_VIEW
    assert handle.swipes == [(95, 990, 95, 990, 800)]   # 长按，不是点击
    assert sm.current == "OPEN_RESOURCE_VIEW"
    assert sm.fail_reason is None
    sm.step()                                   # OPEN_RESOURCE_VIEW -> SCAN
    assert sm.current == "SCAN"
    assert sm._scan_index == 0                  # 进视角后螺旋从头开始
    assert sm._tried_gems == set()


def test_missing_radial_menu_aborts_cleanly(clk):
    """长按没唤出环形菜单（点偏了/菜单改版）→ 干净中止本轮。"""
    sm, _, _ = make_sm(clk, matched=("alliance_btn",))
    sm.step(); sm.step(); sm.step()
    assert sm.fail_reason == gem_sm.RADIAL_MENU_MISSING_REASON
    sm.step()                                   # OPEN_RESOURCE_VIEW -> END
    assert sm.current == "END"
    assert sm.is_terminal()


def test_no_edge_gain_means_resource_view_not_entered(clk):
    """点了「资源」但画面没变小图标 → 判为没进视角，干净中止。

    相对判据（spec §8.2.1）：不写死绝对阈值——绝对阈值会被地形（山/海）
    和昼夜光照带跑。
    """
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "view_radial_menu",
                                     "view_btn_resource"))
    force_edges(sm, [0.02, 0.021])              # 只涨了 5%，不是缩放
    sm.step(); sm.step(); sm.step()
    assert sm.fail_reason == gem_sm.RESOURCE_VIEW_FAILED_REASON
    sm.step()
    assert sm.current == "END"


def test_view_judge_is_relative_not_absolute(clk):
    """同一张「很花」的地图上，没缩放也不该误判成进了视角。"""
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "view_radial_menu",
                                     "view_btn_resource"))
    force_edges(sm, [0.30, 0.31])               # 绝对值很高，但没涨
    sm.step(); sm.step(); sm.step()
    assert sm.fail_reason == gem_sm.RESOURCE_VIEW_FAILED_REASON


# ---- Task 3.5：回字形螺旋扫图 ----


def test_scan_vector_follows_square_spiral():
    """回字形：段长 1,1,2,2,3,3…，方向 右→下→左→上 循环。

    展开出来是 右1 下1 左2 上2 右3 下3 左4 上4…，走完正好是一圈圈扩大的
    方框（回字形）。
    """
    got = [gem_sm._scan_vector(k) for k in range(1, 13)]
    assert got == [(1, 0), (0, 1), (-1, 0), (-1, 0), (0, -1), (0, -1),
                   (1, 0), (1, 0), (1, 0), (0, 1), (0, 1), (0, 1)]


def test_scan_total_steps_matches_ring_count():
    assert gem_sm._scan_total_steps(3) == 12
    assert gem_sm._scan_total_steps(1) == 2


def test_scan_drags_one_cell_when_no_gem(clk):
    sm, handle, _ = make_sm(clk, matched=("alliance_btn", "view_radial_menu",
                                          "view_btn_resource"))
    force_edges(sm, [0.02, 0.05])
    sm.step(); sm.step(); sm.step(); sm.step()      # -> SCAN
    assert sm.current == "SCAN"
    before = len(handle.swipes)
    sm.step()                                       # SCAN -> SCAN（扫下一格）
    assert sm.current == "SCAN"
    assert sm._scan_index == 1
    # 第 1 步是「往右看一格」→ 手指得往左拖
    assert handle.swipes[before:] == [(900, 520, 100, 520, 500)]


def test_scan_hands_off_when_gem_found(clk):
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "view_radial_menu",
                                     "view_btn_resource", "gem_icon"))
    force_edges(sm, [0.02, 0.05])
    sm.step(); sm.step(); sm.step(); sm.step()      # -> SCAN
    sm.step()                                       # SCAN 自环：扫到宝石（verdict=gem）
    sm.step()                                       # SCAN -> ZOOM_CONFIRM
    assert sm.current == "ZOOM_CONFIRM"
    assert sm._pending_gem == (50, 50)              # 替身 bbox 中心
    assert sm._scan_index == 0                      # 没白拖一格


def test_scan_exhausts_after_configured_rings(clk):
    """scan_rings=1 → 2 步扫完 → 本轮正常结束（**不是失败**）。"""
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "view_radial_menu",
                                     "view_btn_resource"), scan_rings=1)
    force_edges(sm, [0.02, 0.05])
    sm.step(); sm.step(); sm.step(); sm.step()      # -> SCAN
    sm.step()                                       # 拖 1 格，index 0 -> 1
    sm.step()                                       # 拖 1 格，index 1 -> 2
    assert sm._scan_index == 2
    sm.step()                                       # 自环判 exhausted
    sm.step()                                       # 扫完 -> ROUND_DONE
    assert sm.current == "ROUND_DONE"
    assert sm.fail_reason is None
    sm.step()                                       # ROUND_DONE -> END
    assert sm.is_terminal()


def test_scan_skips_a_gem_that_already_failed_confirmation(clk):
    """确认失败过的点位记进 `_tried_gems`：否则同一颗宝石会被反复点开、
    反复关掉，整轮卡死在原地。"""
    sm, _, _ = make_sm(clk, matched=("alliance_btn", "view_radial_menu",
                                     "view_btn_resource", "gem_icon"))
    force_edges(sm, [0.02, 0.05])
    sm.step(); sm.step(); sm.step(); sm.step()      # -> SCAN
    sm._tried_gems.add(sm._gem_key((50, 50)))       # 这颗已经试过了
    sm.step()
    assert sm.current == "SCAN"                     # 没有再次交接
    assert sm._scan_index == 1                      # 改成扫下一格


# ---- Task 3.6：点开放大 + 宝石双确认 ----


def test_zoom_confirm_success_hands_off_to_dialog(clk):
    """放大后的宝石图标认出来了 → 交给 COLLECT_DIALOG 去点第二下。"""
    sm, handle, _ = _to_scan(clk, ("gem_icon", "gem_mine_zoom",
                                   "collect_dialog", "gem_dialog_title"))
    before = len(handle.clicks)
    sm.step()                                       # SCAN -> ZOOM_CONFIRM
    assert sm.current == "ZOOM_CONFIRM"
    assert handle.clicks[before] == (50, 50)        # 这一拍点了候选
    sm.step()                                       # ZOOM_CONFIRM -> COLLECT_DIALOG
    assert sm.current == "COLLECT_DIALOG"
    assert sm.fail_reason is None
    assert sm._gem_fail_streak == 0


def test_zoom_confirm_failure_records_tried_and_returns_to_scan(clk):
    """点开之后没认出放大的宝石（误检/被别的单位挡住）→ 记下这点，回螺旋。"""
    sm, _, _ = _to_scan(clk, ("gem_icon",))
    sm.step()                                       # -> ZOOM_CONFIRM
    sm.step()                                       # -> SCAN
    assert sm.current == "SCAN"
    assert sm._is_tried((50, 50))
    assert sm._gem_fail_streak == 1
    assert sm.fail_reason is None


def test_three_confirm_failures_abort_the_round(clk):
    """连续 3 个候选都确认不了 → 干净中止本轮（`gem_confirm_failed`）。

    上限是**有界**的：没有它，一颗怎么点都认不出的「宝石」会让这一轮
    永远在 SCAN ↔ ZOOM_CONFIRM 之间打转。
    """
    sm, _, recs = _to_scan(clk, ())
    # 三个**不同位置**的候选：同一位置会被 `_tried_gems` 挡住，走不到第三次
    recs["gem_icon"] = _rec_at((100, 100), (300, 300), (700, 700))
    for _ in range(9):
        sm.step()
        if sm.current == "END":
            break
    assert sm.current == "END"
    assert sm.fail_reason == gem_sm.GEM_CONFIRM_FAILED_REASON


def test_confirm_failure_counter_resets_after_a_success(clk):
    sm, _, recs = _to_scan(clk, ("collect_dialog", "gem_dialog_title"))
    recs["gem_icon"] = _rec_at((100, 100), (700, 700))
    sm.step()                                   # SCAN 自环：扫到 (100,100)
    sm.step()                                   # SCAN -> ZOOM_CONFIRM（腿一 gem_mine_zoom
                                                #   未命中 -> 放弃该点，streak=1）
    sm.step()                                   # ZOOM_CONFIRM -> SCAN（action 是 _scan_step：
                                                #   顺手扫到 (700,700)）
    assert sm._gem_fail_streak == 1
    # 换一颗宝石、这次能确认
    recs["gem_mine_zoom"] = _rec(True)
    sm.step()                                   # SCAN -> ZOOM_CONFIRM（腿一命中，streak 归零）
    sm.step()                                   # ZOOM_CONFIRM -> COLLECT_DIALOG
                                                #   （腿二：collect_dialog + gem_dialog_title 都命中）
    assert sm.current == "COLLECT_DIALOG"
    assert sm._gem_fail_streak == 0


def test_missing_ocr_recognizer_aborts_loudly(clk):
    """manifest 没配 `gem_dialog_title`（或 OCR 被关掉）→ 明确中止。

    **不能悄悄退回「只看图标」**：那等于把用户选定的双确认降级成单确认，
    而且降级这件事在日志里毫无痕迹。宁可烧一轮，也要让操作者看见
    「确认策略缺了一条腿」。

    判据放在 `_zoom_confirm` 开头（而不是等真要点第二下时才发现）：越早
    发现越省事——不然每颗宝石都要白点两下、白关一次面板才走到中止。
    """
    sm, _, recs = _to_scan(clk, ("gem_icon", "gem_mine_zoom"))
    recs.pop("gem_dialog_title")
    sm.step()                                       # SCAN -> ZOOM_CONFIRM
    assert sm.fail_reason == gem_sm.GEM_OCR_MISSING_REASON
    sm.step()                                       # ZOOM_CONFIRM -> END
    assert sm.current == "END"
    assert sm.is_terminal()


def test_collect_dialog_requires_both_icon_and_ocr(clk):
    """双确认：采集框模板 **且** 标题 OCR 读出「宝石」才算数。"""
    sm, handle, _ = _to_scan(clk, ("gem_icon", "gem_mine_zoom",
                                   "collect_dialog", "gem_dialog_title"))
    sm.step()                                       # -> ZOOM_CONFIRM
    before = len(handle.clicks)
    sm.step()                                       # -> COLLECT_DIALOG
    assert sm.current == "COLLECT_DIALOG"
    assert handle.clicks[before] == (50, 50)        # 在放大画面上点了第二下
    assert sm.fail_reason is None


def test_collect_dialog_without_ocr_text_is_treated_as_another_resource(clk):
    """采集框出来了但标题不是「宝石」→ 是别的资源，关掉回螺旋。

    **这是双确认的全部意义**：地图上「一小坨白色」既可能是宝石也可能是
    别的矿，光看图标会误派一支队伍去采 20 分钟。
    """
    sm, _, _ = _to_scan(clk, ("gem_icon", "gem_mine_zoom", "collect_dialog"))
    sm.step()                                       # -> ZOOM_CONFIRM
    sm.step()                                       # -> COLLECT_DIALOG
    assert sm.current == "COLLECT_DIALOG"
    sm.step()                                       # COLLECT_DIALOG -> SCAN
    assert sm.current == "SCAN"
    assert sm._is_tried((50, 50))
    assert sm._gem_fail_streak == 1
    assert sm.fail_reason is None


def test_no_collect_dialog_at_all_returns_to_scan(clk):
    """第二下没弹出采集框（点击被吞）→ 记下这点回螺旋。"""
    sm, _, _ = _to_scan(clk, ("gem_icon", "gem_mine_zoom"))
    sm.step()                                       # -> ZOOM_CONFIRM
    sm.step()                                       # -> COLLECT_DIALOG（判定失败）
    sm.step()                                       # COLLECT_DIALOG -> SCAN
    assert sm.current == "SCAN"
    assert sm._is_tried((50, 50))


# ---- Task 3.7：点蓝色「采集」按钮 ----


def test_click_collect_missing_button_is_a_real_failure(clk):
    """采集框在场但蓝色「采集」按钮认不出来 → collect_rejected（计入失败）。"""
    sm, _, _ = _to_collect_dialog(clk, ())
    sm.step()                                       # COLLECT_DIALOG -> CLICK_COLLECT
    assert sm.current == "CLICK_COLLECT"
    assert sm.fail_reason == gem_sm.COLLECT_REJECTED_REASON
    sm.step()                                       # CLICK_COLLECT -> END
    assert sm.current == "END"
    assert sm.is_terminal()


def test_click_collect_success_hands_off_to_create_troop(clk):
    sm, handle, recs = _to_collect_dialog(clk, ("collect_btn",))
    # 采集框在「点采集」之后消失——`_click_collect` 用 `_wait_for_gone` 确认受理
    recs["collect_dialog"] = _rec_seq(False)
    before = len(handle.clicks)
    sm.step()                                       # COLLECT_DIALOG -> CLICK_COLLECT
    assert sm.current == "CLICK_COLLECT"
    assert handle.clicks[before] == (50, 50)        # 点了蓝色「采集」按钮
    assert sm.fail_reason is None


def test_click_collect_dialog_stuck_open_is_a_real_failure(clk):
    """点了「采集」但采集框不关（游戏静默拒绝）→ 也是 collect_rejected。

    只看「点到了按钮没有」是不够的：静默拒绝会被记成成功派兵，而队列数
    纹丝不动 → 下一拍还是同一屏，白烧一整轮。
    """
    sm, _, _ = _to_collect_dialog(clk, ("collect_btn",))
    sm.step()                                       # 采集框点完不消失
    assert sm.fail_reason == gem_sm.COLLECT_REJECTED_REASON


# ---- Task 3.8：创建部队 + 只点行军 ----


def test_create_troop_clicks_bubble_then_waits_for_march_btn(clk):
    sm, handle, _ = _to_click_collect(clk, ("join_create_btn", "march_btn"))
    before = len(handle.clicks)
    sm.step()                                       # CLICK_COLLECT -> CREATE_TROOP
    assert sm.current == "CREATE_TROOP"
    assert handle.clicks[before] == (50, 50)        # 点了「创建部队」气泡按钮
    assert sm.fail_reason is None


def test_create_troop_tolerates_missing_bubble(clk):
    """气泡不在是正常的：游戏某些入口直接给表单，点击失败只当白费 ~2s。"""
    sm, handle, _ = _to_click_collect(clk, ("march_btn",))
    before = len(handle.clicks)
    sm.step()
    assert sm.current == "CREATE_TROOP"
    assert handle.clicks[before:] == []             # 一下都没点
    assert sm.fail_reason is None


def test_create_troop_timeout_aborts_cleanly_not_raise(clk):
    """表单等不到 → `form_missing` 干净中止。

    **不要学 `leader_sm._form_troop` 在这里 `raise RuntimeError`**：runner
    收到 step 异常不重建 SM，会在同一状态退避重放，攒满 6 次直接停机
    （PROGRESS 已知问题 8 / 14）。宝石模式全部走 ctx + END 边。
    """
    sm, _, _ = _to_click_collect(clk, ("join_create_btn",))
    sm.step()                                       # CLICK_COLLECT -> CREATE_TROOP
    assert sm.current == "CREATE_TROOP"
    assert sm.fail_reason == gem_sm.FORM_MISSING_REASON
    sm.step()                                       # CREATE_TROOP -> END
    assert sm.current == "END"
    assert sm.is_terminal()


def test_fill_form_clicks_only_march(clk):
    """**只点行军**：不点预设槽、不点兵种、不点「最大」队列。

    用户 2026-10-17 明确纠正：队列用游戏默认的。点「最大」会把兵全填进去，
    对采集这种长任务没有意义，还挤掉其他用途的兵。
    """
    sm, handle, recs = _to_create_troop(clk, ("join_create_btn", "march_btn"))
    # 行军点击之后表单关闭。次序：call1 = _fill_form 的 _click_retry，
    # call2 = _wait_for_gone 首查（表单还在，正在关），call3 起 = 已关
    recs["march_btn"] = _rec_seq(True, True, False)
    before = len(handle.clicks)
    sm.step()                                       # CREATE_TROOP -> FILL_FORM
    assert sm.current == "FILL_FORM"
    assert handle.clicks[before:] == [(50, 50)]     # **就这一下**
    assert sm.fail_reason is None


def test_fill_form_march_rejected_aborts(clk):
    """点了行军但表单不关 → 游戏拒绝，`march_rejected`（计入失败）。"""
    sm, _, recs = _to_create_troop(clk, ("join_create_btn", "march_btn"))
    recs["march_btn"] = _rec(True)                  # 点了行军，表单不关
    sm.step()                                       # CREATE_TROOP -> FILL_FORM
    assert sm.current == "FILL_FORM"
    assert sm.fail_reason == gem_sm.MARCH_REJECTED_REASON
    sm.step()                                       # FILL_FORM -> END
    assert sm.current == "END"


def test_successful_march_recounts_queues(clk):
    """派兵成功后**回到 COUNT_QUEUES 重数**（spec §6.1），用的是**新**读数。

    判别性全在最后两拍：队列图标是派兵**之后**才点亮的（这一队刚好把队列
    占满）。只有 `FILL_FORM → COUNT_QUEUES` 的 action 真的又跑了一遍
    `_count_queues`，这一拍才拿得到 `queues_full=True` 并路由到 WAIT；若
    沿用派兵前那个 `queues_full=False`（把 action 换成空函数即复现），
    `COUNT_QUEUES → OPEN_RESOURCE_VIEW` 那条无 guard 的边会抢先放行——
    「派完最后一队、队列刚好满」这一拍就被漏掉，正是 Ruling 4 要挡的回归。
    """
    sm, _, recs = _to_create_troop(clk, ("join_create_btn", "march_btn"))
    recs["march_btn"] = _rec_seq(True, False)
    sm.step()                                       # CREATE_TROOP -> FILL_FORM
    assert sm.current == "FILL_FORM"
    assert sm.fail_reason is None
    for rid in gem_sm.QUEUE_ICON_IDS:
        recs[rid] = _rec(True)                      # 行军后队列刚好被占满
    sm.step()                                       # FILL_FORM -> COUNT_QUEUES（就地重数）
    assert sm.current == "COUNT_QUEUES"
    assert sm._ctx["queue_count"] == 5              # 新读数，不是派兵前那个 0
    assert sm._ctx["waits_used"] == 0               # 重数本身不算一次等待
    sm.step()                                       # 满 → 进 WAIT（只有新读数能走到这）
    assert sm.current == "WAIT"
    assert sm._ctx["waits_used"] == 1
