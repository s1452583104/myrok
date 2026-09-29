# -*- coding: utf-8 -*-
"""`pixel_stats:` 小节的校准锚点（2026-09-27 实测）。

与 `test_preset_roi_anchor.py` 同属「读**真实** manifest」的锚点测试：锚的不是
代码行为而是一次标定。数值推导与两个陷阱见 `recognizers/pixel_stat.py` 的
模块 docstring 与 manifest 末尾的注释。

这里额外锁一条**爆炸半径不变量**：`pixel_stats` 的 id 绝不能出现在
`registry._t` 里。`tools/auto_label_yolo.py` / `ingest_raw_imgs.py` /
`measure_preset_roi.py` / `relabel_extra_classes.py` 都会对 `_t` 的每个 spec
`cv2.imread(spec.file)`——放进去要么 KeyError（缺 file），要么为一个
dataset.yaml 里不存在的类注入垃圾框。
"""
from __future__ import annotations

from pathlib import Path

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
    PixelStatRecognizer,
    slot_centers,
)
from rok_assistant.core.template_registry import TemplateRegistry

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "templates" / "manifest.yaml"
PIXEL_IDS = [f"selected_preset_{i}" for i in range(1, 7)]


@pytest.fixture(scope="module")
def registry() -> TemplateRegistry:
    return TemplateRegistry.load(MANIFEST)


def test_manifest_declares_the_six_preset_slots(registry):
    assert [s.id for s in registry._pixel] == PIXEL_IDS
    assert {s.kind for s in registry._pixel} == {"preset_slot"}


def test_pixel_stat_ids_are_absent_from_the_template_table(registry):
    """爆炸半径不变量：`_t` 里一个 pixel_stat id 都不能有。

    有的话 auto_label_yolo 会对它 cv2.imread（KeyError 或垃圾框）。
    """
    for tid in PIXEL_IDS:
        assert tid not in registry._t, (
            f"{tid} 混进了 templates: —— auto_label_yolo/ingest_raw_imgs 会"
            f"对每个 spec cv2.imread(spec.file)")
    assert len(registry._t) == 53, "templates: 条目数变了，确认是有意的"


def test_build_recognizers_includes_the_pixel_stats(registry):
    recs = registry.build_recognizers()
    for tid in PIXEL_IDS:
        assert isinstance(recs[tid], PixelStatRecognizer), f"{tid} 没装配成像素判据"


def test_all_six_share_one_judge(registry):
    """6 个识别器必须共用同一个 judge，否则单帧要扫 6 遍。"""
    recs = registry.build_recognizers()
    judges = {id(recs[tid]._judge) for tid in PIXEL_IDS}
    assert len(judges) == 1


def test_geometry_constants_match_the_measured_table():
    """44 帧逐像素实测。改这些数必须重跑实测，别只改一边。"""
    assert (PRESET_CX, PRESET_TOP, PRESET_PITCH, PRESET_HALF) == (1655.0, 474.0, 82.0, 22)
    assert PRESET_SCAN_N == 7, "第 7 槽 cy=966 真实存在（实测 6 帧选中它）"
    assert (PRESET_MIN_FRAC, PRESET_MIN_RATIO) == (0.40, 3.0)


def test_sampled_centers_never_include_the_top_diamond():
    """取样中心必须全部避开顶部菱形（frac 0.80，比任何选中槽都亮）。

    菱形在 389，槽 1 在 474 —— 恰好差一个槽距。取样若从 391 起，
    index 0 就落在菱形上，判据会把菱形当成「槽 1 选中」。
    """
    centers = slot_centers()
    assert len(centers) == PRESET_SCAN_N
    for cx, cy in centers:
        assert abs(cy - PRESET_DISTRACTOR_CY) > PRESET_HALF, (
            f"取样中心 {cy} 落在顶部菱形 {PRESET_DISTRACTOR_CY} 上")
    assert min(cy for _, cy in centers) == PRESET_TOP, "第一个取样点必须是槽 1"
