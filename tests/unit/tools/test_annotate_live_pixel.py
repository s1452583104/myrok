# -*- coding: utf-8 -*-
"""`tools/annotate_live.py` 的像素判据接入（预览侧）。

预览跑的是**裸 YOLO**，不走识别器栈，所以 `pixel_stats` 装好了也不会自动出现在
预览里——得在 `_detections` 里显式接一步（同 `_ocr_level_text` 的先例）。

锁两件事：

1. **YOLO 在那几类上的输出必须被滤掉。** 模型对 `selected_preset_N` 给出的类别
   本身就是错的（实测在标注为槽 3 的位置给出 `preset_4@0.06`），不滤就是真框假框
   一起画在屏幕上。
2. **像素检出要落在实测几何上**，且**不声称哪一行排序项是激活的**——三行只按布局
   位置命名，没有判据。
"""
from __future__ import annotations

import numpy as np
import pytest

from rok_assistant.core.recognizers.pixel_stat import (
    PRESET_HALF,
    SORT_DARK_ROI,
    SORT_OPT_X,
    SORT_OPT_YS,
    SORT_SELECTOR_PX,
    slot_center,
)
from tools import annotate_live

NATIVE_W, NATIVE_H = 1920, 1080
NAMES = {
    25: "preset_1", 26: "preset_2", 27: "preset_3",
    28: "preset_4", 29: "preset_5", 30: "preset_6",
    53: "selected_preset_1", 54: "selected_preset_2", 55: "selected_preset_3",
    56: "selected_preset_4", 57: "selected_preset_5", 58: "selected_preset_6",
    59: "sort_selector", 60: "sort_opt_latest",
    61: "sort_opt_nearest", 62: "sort_opt_shortest",
}
INV = {v: k for k, v in NAMES.items()}


class _Box:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = [np.array(xyxy, dtype=float)]
        self.conf = [conf]
        self.cls = [cls]


class _Result:
    def __init__(self, boxes):
        self.boxes = boxes


def _yolo(*boxes):
    return [_Result(list(boxes))]


def _frame(bright=(), sort_bar=False, dropdown=False) -> np.ndarray:
    # 底用 150 而不是全黑：全黑帧会让「下拉展开」判据（meanV < 90）在收起帧上也
    # 成立。实测收起帧那块是 118~187，所以底必须亮过 90 才是个诚实的收起帧。
    img = np.full((NATIVE_H, NATIVE_W, 3), 150, np.uint8)
    for s in bright:
        cx, cy = slot_center(s)
        img[int(cy) - PRESET_HALF:int(cy) + PRESET_HALF,
            int(cx) - PRESET_HALF:int(cx) + PRESET_HALF] = 255
    if sort_bar:
        x1, y1, x2, y2 = SORT_SELECTOR_PX
        img[y1 + 10:y2 - 10, x1 + 150:x2 - 150] = (60, 200, 230)   # BGR 黄
    if dropdown:
        x1, y1, x2, y2 = SORT_DARK_ROI
        img[y1:y2, x1:x2] = 25
    return img


# --- 滤掉 YOLO 的状态类输出 -----------------------------------------------

@pytest.mark.parametrize("name,cid", [("selected_preset_3", 55),
                                      ("sort_selector", 59),
                                      ("sort_opt_latest", 60)])
def test_yolo_output_for_state_classes_is_filtered_out(name, cid):
    """模型这几类给的框/类别是错的，预览里必须滤掉（否则真框假框一起画）。"""
    img = _frame(bright=(3,))
    dets = annotate_live._detections(
        img, _yolo(_Box((1600, 450, 1700, 500), 0.91, cid)), NAMES, 0.5, INV)

    assert [d["name"] for d in dets] == ["selected_preset_3"], \
        "YOLO 那条该被滤掉，只留像素判据那条"
    assert all(d["src"] == "pixel" for d in dets)


def test_ordinary_classes_are_not_filtered():
    """不在接管名单里的类照常透传。"""
    img = _frame()
    dets = annotate_live._detections(
        img, _yolo(_Box((10, 10, 30, 30), 0.9, 25)), NAMES, 0.5, INV)

    assert [d["name"] for d in dets] == ["preset_1"]
    assert dets[0]["src"] == "yolo"


def test_conf_threshold_still_applies_to_yolo_only():
    """阈值只该管 YOLO——像素判据没有「置信度」，它的 conf 是实测统计量。"""
    img = _frame(bright=(2,))
    dets = annotate_live._detections(
        img, _yolo(_Box((10, 10, 30, 30), 0.2, 25)), NAMES, 0.5, INV)

    assert [d["name"] for d in dets] == ["selected_preset_2"]


# --- 预设选中槽 -------------------------------------------------------------

@pytest.mark.parametrize("slot", [1, 2, 6])
def test_highlighted_slot_becomes_a_detection_at_the_measured_box(slot):
    dets = annotate_live._pixel_dets(_frame(bright=(slot,)), INV)

    assert len(dets) == 1
    d = dets[0]
    cx, cy = slot_center(slot)
    assert d["name"] == f"selected_preset_{slot}"
    assert d["cid"] == INV[f"selected_preset_{slot}"]
    assert d["xyxy"] == (int(cx) - PRESET_HALF, int(cy) - PRESET_HALF,
                         int(cx) + PRESET_HALF, int(cy) + PRESET_HALF)
    assert d["conf"] > 0.9, "conf 放的是实测 frac"


def test_no_highlight_means_no_preset_detection():
    assert annotate_live._pixel_dets(_frame(), INV) == []


def test_slot_7_is_measured_but_not_drawn():
    """第 7 槽真实存在，但 `march_preset` 取值域到 6——预览也不画它。"""
    assert annotate_live._pixel_dets(_frame(bright=(7,)), INV) == []


def test_unknown_cid_is_skipped_not_crashed():
    """类表里没有 selected_preset_* 时（旧模型）不炸，只是不画。"""
    assert annotate_live._pixel_dets(_frame(bright=(3,)), {}) == []


# --- 排序 UI ---------------------------------------------------------------

def test_sort_bar_only_when_the_bar_is_actually_there():
    """战争详情页那个位置是列表行，没有条——不该画 sort_selector。"""
    assert [d["name"] for d in annotate_live._pixel_dets(
        _frame(), INV, {"war_title"})] == []

    dets = annotate_live._pixel_dets(_frame(sort_bar=True), INV, {"war_title"})
    assert [d["name"] for d in dets] == ["sort_selector"]
    assert dets[0]["conf"] > 0.01


def test_sort_ui_is_not_looked_for_off_the_war_list():
    """**回归测试**：黄字闸门是在 02_warlist 内部标定的，换界面就不成立。

    实测创建部队弹窗上那块（罩着兵种行）黄字占比 0.03 —— 照样过 0.010 的闸，
    不按界面门控就会在兵种列表上画一个假的「排序条」。
    """
    img = _frame(sort_bar=True, dropdown=True)

    assert annotate_live._pixel_dets(img, INV, set()) == []
    assert [d["name"] for d in annotate_live._pixel_dets(img, INV, {"war_title"})] \
        == ["sort_selector", "sort_opt_latest", "sort_opt_nearest", "sort_opt_shortest"]


def test_dropdown_rows_are_added_only_when_open():
    collapsed = annotate_live._pixel_dets(_frame(sort_bar=True), INV, {"war_title"})
    assert len(collapsed) == 1

    opened = annotate_live._pixel_dets(_frame(sort_bar=True, dropdown=True),
                                       INV, {"war_title"})
    assert [d["name"] for d in opened] == [
        "sort_selector", "sort_opt_latest", "sort_opt_nearest", "sort_opt_shortest"]
    x1, x2 = SORT_OPT_X
    for d, (_n, cy) in zip(opened[1:], SORT_OPT_YS.items()):
        assert d["xyxy"][0] == x1 and d["xyxy"][2] == x2
        assert (d["xyxy"][1] + d["xyxy"][3]) / 2 == pytest.approx(cy, abs=0.5)


def test_the_three_sort_rows_carry_no_claim_about_which_is_active():
    """三行的 conf 必须**完全一样**——有差别就等于在声称哪一行是激活项，
    而激活项没有判据（三行填充/亮度一致，只有文字不同）。"""
    rows = [d for d in annotate_live._pixel_dets(
        _frame(sort_bar=True, dropdown=True), INV, {"war_title"})
        if d["name"].startswith("sort_opt_")]

    assert len(rows) == 3
    assert len({d["conf"] for d in rows}) == 1


# --- 绘制 -----------------------------------------------------------------

def test_pixel_detections_are_marked_in_the_drawn_label(monkeypatch):
    """画面上要能一眼看出哪条是量出来的、哪条是模型给的。"""
    monkeypatch.setattr(annotate_live, "_font", lambda size=18: None)
    img = _frame(bright=(3,))

    vis = annotate_live.annotate(img, annotate_live._pixel_dets(img, INV))

    assert vis.shape == img.shape
    assert not np.array_equal(vis, img), "什么都没画上去"
