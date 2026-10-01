from unittest.mock import MagicMock

import numpy as np
import pytest

from rok_assistant.core.recognizers.view_probe import (VIEW_ANCHORS,
                                                       View, ViewProbe)


def _recs(matching):
    """matching = {rec_id: confidence}，其余 id 一律不匹配。"""
    out = {}
    for view, ids in VIEW_ANCHORS.items():
        for rid in ids:
            rec = MagicMock()
            conf = matching.get(rid, 0.0)
            rec.recognize.return_value.matched = rid in matching
            rec.recognize.return_value.confidence = conf
            out[rid] = rec
    return out


IMG = np.zeros((100, 100, 3), dtype=np.uint8)


@pytest.mark.parametrize("view,rid", [
    (View.MAP, "search_icon"),
    (View.MAP, "alliance_btn"),
    (View.CITY, "map_btn"),
    (View.WAR_LIST, "war_title"),
    (View.SEARCH, "search_back"),
    (View.RALLY_POPUP, "rally_attack_popup"),
    (View.TROOP_FORM, "march_btn"),
    (View.MODAL, "ap_refill"),
])
def test_each_view_anchor_is_detected(view, rid):
    """每个视图的每个锚点单独出现时都必须被判成该视图。"""
    v = ViewProbe(_recs({rid: 0.95})).probe(IMG)
    assert v.view is view, f"{rid} 应判为 {view}，实得 {v.view}"


def test_modal_wins_over_map():
    """全屏模态会盖住地图：两者锚点同时命中时必须判模态，
    否则归一化会以为已在地图视图而漏关弹窗。"""
    v = ViewProbe(_recs({"ap_refill": 0.95, "search_icon": 0.99})).probe(IMG)
    assert v.view is View.MODAL


def test_troop_form_wins_over_map():
    v = ViewProbe(_recs({"march_btn": 0.90, "alliance_btn": 0.99})).probe(IMG)
    assert v.view is View.TROOP_FORM


def test_no_anchor_hit_is_unknown_not_map():
    """一个锚点都不命中 → UNKNOWN。绝不能默认成 MAP——
    「不知道在哪」和「在地图」是两个完全不同的处置。"""
    v = ViewProbe(_recs({})).probe(IMG)
    assert v.view is View.UNKNOWN
    assert v.confidence == 0.0
    assert v.hits == ()


def test_confidence_and_scores_are_reported():
    v = ViewProbe(_recs({"war_title": 0.87})).probe(IMG)
    assert v.confidence == pytest.approx(0.87)
    assert v.scores["war_title"] == pytest.approx(0.87)
    assert v.hits == ("war_title",)


def test_missing_recognizer_is_skipped_not_crashed():
    """未配置的锚点识别器必须跳过：真实配置里 replace_popup 等
    只在部分 manifest 里存在。"""
    recs = _recs({})
    del recs["replace_popup"]
    v = ViewProbe(recs).probe(IMG)
    assert v.view is View.UNKNOWN


def test_probe_only_calls_each_recognizer_once():
    """一次截屏判定一个视图，每个识别器只跑一次——
    否则归一化每拍要付十几次模板匹配的代价。"""
    recs = _recs({"war_title": 0.9})
    ViewProbe(recs).probe(IMG)
    for rid, rec in recs.items():
        assert rec.recognize.call_count == 1, rid
