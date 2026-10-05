# -*- coding: utf-8 -*-
"""`pixel_stat` 预设选中态判据。

锁的核心是**两个实测陷阱**（都不是假想的边界情况，是 44 帧实测出来的）：

1. 顶部菱形 `cy≈389` 恒亮 `frac 0.80`——**比任何真选中槽都亮**，且恰好在槽 1
   上方一个槽距。从 y=391 起扫 6 格就会把它当成槽 1，这正是数据集里
   `preset_1` 有 3 个框标在菱形上、22 个框整体偏高一个槽距的来源。
2. 第 7 槽 `cy=966` 真实存在（实测 6 帧选中它），但 `march_preset` 只到 6，
   所以扫 7 格、只给 1..6 装识别器。

以及 fail-closed：过不了闸就一个都不匹配——最坏是「没点预设」，
**永远不会是「点错槽」**。
"""
from __future__ import annotations

import numpy as np
import pytest

from rok_assistant.core.recognizers.pixel_stat import (
    PRESET_CX,
    PRESET_DISTRACTOR_CY,
    PRESET_HALF,
    PRESET_MIN_FRAC,
    PRESET_MIN_RATIO,
    PRESET_PITCH,
    PRESET_SCAN_N,
    PRESET_TOP,
    PresetSlotJudge,
    bright_frac,
    build_preset_recognizers,
    panel_verdict,
    parse_slot,
    slot_center,
    slot_centers,
)

ALL_IDS = [f"selected_preset_{n}" for n in range(1, 7)]


def _frame(bright=(), distractor=False) -> np.ndarray:
    """暗底 + 指定槽刷白（选中态）+ 可选顶部菱形。"""
    img = np.full((1080, 1920, 3), 30, np.uint8)
    for s in bright:
        cx, cy = slot_center(s)
        img[int(cy) - PRESET_HALF:int(cy) + PRESET_HALF,
            int(cx) - PRESET_HALF:int(cx) + PRESET_HALF] = 255
    if distractor:
        # 实测 55x54、mean BGR [231,175,8]；max(BGR)=231 > 200，所以「亮」
        cy, cx = int(PRESET_DISTRACTOR_CY), int(PRESET_CX)
        img[cy - 27:cy + 27, cx - 27:cx + 27] = (231, 175, 8)
    return img


def _matched(recs, img) -> set[str]:
    return {k for k, r in recs.items() if r.recognize(img).matched}


# --- 几何 -----------------------------------------------------------------

def test_slot_geometry_matches_the_measured_table():
    """44 帧逐像素实测：cx=1655，槽 N 中心 474+82*(N-1)。"""
    assert PRESET_CX == 1655.0
    assert PRESET_TOP == 474.0
    assert PRESET_PITCH == 82.0
    assert PRESET_HALF == 22
    assert [cy for _, cy in slot_centers()] == [474, 556, 638, 720, 802, 884, 966]


def test_sampled_centers_never_land_on_the_top_diamond():
    """取样中心与菱形 389 的距离必须大于取样半径——否则就会读到菱形。"""
    assert all(abs(cy - PRESET_DISTRACTOR_CY) > PRESET_HALF
               for _, cy in slot_centers()), "取样中心落在顶部菱形上了"


# --- 陷阱 1：顶部菱形 -------------------------------------------------------

def test_the_bright_element_one_pitch_above_slot_1_never_yields_slot_1():
    """**回归测试**：只有菱形亮时，一个槽都不许匹配。

    菱形 frac 0.80 比真选中槽（0.72~0.75）还亮，若取样从 391 起就必然误判
    成「槽 1 选中」——数据集里那 25 个错标就是这么来的。
    """
    img = _frame(distractor=True)

    assert bright_frac(img, PRESET_CX, PRESET_DISTRACTOR_CY) > 0.75, \
        "菱形本身是亮的（陷阱成立）"
    assert panel_verdict(img).slot is None
    assert _matched(build_preset_recognizers(ALL_IDS), img) == set()


def test_slot_1_still_wins_when_the_diamond_is_also_bright():
    """菱形 + 槽 1 真高亮 → 判槽 1（菱形不参与竞争）。"""
    img = _frame(bright=(1,), distractor=True)

    assert panel_verdict(img).slot == 1
    assert _matched(build_preset_recognizers(ALL_IDS), img) == {"selected_preset_1"}


# --- 选中态判定 -------------------------------------------------------------

@pytest.mark.parametrize("slot", [1, 2, 3, 4, 5, 6])
def test_only_the_bright_slot_matches(slot):
    img = _frame(bright=(slot,))

    assert panel_verdict(img).slot == slot
    assert _matched(build_preset_recognizers(ALL_IDS), img) == \
        {f"selected_preset_{slot}"}


def test_selected_slot_margin_is_wide():
    """选中 1.0 vs 未选中 0.0（实机是 0.72~0.75 vs 0.07~0.09），余量远过闸。"""
    v = panel_verdict(_frame(bright=(4,)))

    assert v.fracs[3] == 1.0
    assert v.top_frac >= PRESET_MIN_FRAC
    assert v.top_frac >= PRESET_MIN_RATIO * v.second


def test_no_highlight_matches_nothing():
    """全暗帧（战争列表/地图/动画中间帧）→ 一个都不匹配，fail-closed。"""
    img = _frame()

    assert panel_verdict(img).slot is None
    assert _matched(build_preset_recognizers(ALL_IDS), img) == set()


def test_two_bright_slots_fail_the_ratio_gate():
    """两个槽同时亮（不该出现）→ 判「没有」而不是随便挑一个。"""
    img = _frame(bright=(2, 5))

    assert panel_verdict(img).slot is None
    assert _matched(build_preset_recognizers(ALL_IDS), img) == set()


def test_dim_highlight_below_min_frac_matches_nothing():
    """高亮被遮/半透明（占比 0.30 < 0.40）→ 不猜，判没有。"""
    img = _frame()
    cx, cy = slot_center(3)
    img[int(cy) - PRESET_HALF:int(cy) + PRESET_HALF,
        int(cx) - PRESET_HALF:int(cx) + PRESET_HALF] = 0
    # 只刷满约 1/3 的像素
    img[int(cy) - 8:int(cy) + 8, int(cx) - 8:int(cx) + 8] = 255

    assert bright_frac(img, cx, cy) < PRESET_MIN_FRAC
    assert panel_verdict(img).slot is None


# --- 陷阱 2：第 7 槽 --------------------------------------------------------

def test_slot_7_selection_matches_none_of_1_to_6():
    """第 7 槽真实存在且可能被选中，但 1..6 都不许匹配（march_preset 只到 6）。"""
    img = _frame(bright=(7,))

    v = panel_verdict(img)
    assert v.slot == 7, "第 7 槽要被识别出来（日志里能区分「没有」和「选的是 7」）"
    assert _matched(build_preset_recognizers(ALL_IDS), img) == set()


def test_scan_covers_seven_slots():
    assert PRESET_SCAN_N == 7


# --- 点击契约 -------------------------------------------------------------

def test_bbox_is_a_clickable_box_at_the_slot_center():
    """`_click_result` 无条件调 `r.bbox.center()`——bbox 必须是非 None 的全屏框。"""
    recs = build_preset_recognizers(ALL_IDS)
    r = recs["selected_preset_3"].recognize(_frame(bright=(3,)))

    assert r.bbox is not None
    cx, cy = slot_center(3)
    assert r.bbox.center() == (int(cx), int(cy))
    assert (r.bbox.x2 - r.bbox.x1, r.bbox.y2 - r.bbox.y1) == (44, 44)


def test_bbox_is_present_even_when_not_matched():
    """未匹配时也给出本槽位置（预览/排查要用），但 matched=False 不会被点。"""
    r = build_preset_recognizers(ALL_IDS)["selected_preset_5"].recognize(_frame())

    assert r.matched is False
    assert r.bbox.center() == (1655, 802)


# --- 运行时基准自校准（2026-10-03 实机）------------------------------------
# 实机面板整体上移 42px（槽心 474 -> 432），march_btn/form_title 分毫未动。
# 基准不能只写死，运行时要能从帧里校准。

def _moved_frame(top: float, slot: int) -> np.ndarray:
    """把「槽 N 高亮」画在基准 top 上（而不是实测的 474）。"""
    img = np.full((1080, 1920, 3), 30, np.uint8)
    cx, cy = slot_center(slot, top=top)
    img[int(cy) - PRESET_HALF:int(cy) + PRESET_HALF,
        int(cx) - PRESET_HALF:int(cx) + PRESET_HALF] = 255
    return img


def test_panel_verdict_accepts_a_calibrated_base():
    img = _moved_frame(432.0, 1)

    assert panel_verdict(img).slot is None, "写死 474 的默认基准本该读不到"
    assert panel_verdict(img, top=432.0).slot == 1


def test_calibrate_moves_the_recognizers_with_the_base():
    img = _moved_frame(432.0, 1)
    judge = PresetSlotJudge()
    recs = build_preset_recognizers(ALL_IDS, judge)
    assert _matched(recs, img) == set()

    judge.calibrate(432.0)

    assert _matched(recs, img) == {"selected_preset_1"}


def test_calibrate_invalidates_the_cached_frame():
    """同一帧先按旧基准出结论，校准后必须重算，不能吃旧缓存。"""
    img = _frame(bright=(2,))
    judge = PresetSlotJudge()
    recs = build_preset_recognizers(ALL_IDS, judge)
    assert _matched(recs, img) == {"selected_preset_2"}

    judge.calibrate(432.0)   # 基准挪走：同一帧的结论必须跟着变

    assert _matched(recs, img) == set()


# --- 缓存 -----------------------------------------------------------------

def test_verdict_is_computed_once_per_frame(monkeypatch):
    """6 个识别器查同一帧只扫一遍 7 个 patch。"""
    calls = []
    real = panel_verdict

    def counting(img, top=PRESET_TOP):
        calls.append(1)
        return real(img, top)

    monkeypatch.setattr("rok_assistant.core.recognizers.pixel_stat.panel_verdict",
                        counting)
    judge = PresetSlotJudge()
    recs = build_preset_recognizers(ALL_IDS, judge)
    img = _frame(bright=(2,))

    for r in recs.values():
        r.recognize(img)
    assert len(calls) == 1, "同一帧被重复计算了"

    nxt = _frame(bright=(3,))
    for r in recs.values():
        r.recognize(nxt)
    assert len(calls) == 2, "换帧必须重算"


def test_cache_holds_a_reference_so_id_reuse_cannot_alias(monkeypatch):
    """`id()` 在对象回收后会被复用——judge 必须持强引用，否则会读到上一帧结论。"""
    judge = PresetSlotJudge()
    judge.verdict(_frame(bright=(1,)))          # 缓存住
    other = _frame(bright=(6,))
    # 换一帧但形状相同：内容不同就必须得到不同结论
    assert judge.verdict(other).slot == 6
    assert judge._last is other, "缓存没持帧引用，id() 复用会串结论"


# --- id 解析 --------------------------------------------------------------

@pytest.mark.parametrize("tid,slot", [("selected_preset_1", 1),
                                      ("selected_preset_6", 6)])
def test_parse_slot_reads_the_id(tid, slot):
    assert parse_slot(tid) == slot


@pytest.mark.parametrize("tid", ["selected_preset_0", "selected_preset_7",
                                 "selected_preset_x", "selected_preset"])
def test_parse_slot_rejects_out_of_range_and_garbage(tid):
    """7 槽存在但只到 6（march_preset 取值域）；解析不了要 loud 失败。"""
    with pytest.raises(ValueError):
        parse_slot(tid)


# --- 健壮性 ---------------------------------------------------------------

def test_odd_frame_size_does_not_crash():
    """非 1080p 帧（裁剪帧）→ 空 patch → frac 0.0 → 判没有，不抛。"""
    img = np.full((162, 279, 3), 200, np.uint8)

    assert panel_verdict(img).slot is None
    assert _matched(build_preset_recognizers(ALL_IDS), img) == set()
