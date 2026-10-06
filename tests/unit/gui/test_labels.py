"""gui/labels.py：界面文案映射 + 校验错误路径翻译。"""
import pytest
from rok_assistant.gui.labels import (
    LABEL_ROLES, ROLE_LABELS, STATE_LABELS, humanize_loc, role_label, state_label,
)


def test_role_labels_round_trip():
    for k, v in ROLE_LABELS.items():
        assert LABEL_ROLES[v] == k
        assert role_label(k) == v


def test_role_label_unknown_falls_back():
    assert role_label("newbie") == "newbie"
    assert role_label(None) == ""


def test_state_label_known():
    assert state_label("WAIT_MEMBERS") == "等待成员填兵"
    assert state_label("cooldown") == "本轮结束，等待下一轮"
    assert state_label("paused") == "已暂停（模拟器窗口不见了）"


def test_state_label_unknown_and_empty_fall_back():
    assert state_label("BRAND_NEW_STATE") == "BRAND_NEW_STATE"
    assert state_label("") == ""
    assert state_label(None) == ""


def test_state_labels_have_no_duplicate_aliases():
    """每个键一个值就够了；同值多键（IDLE 与 LEADER:IDLE）是刻意的，
    但空值/空键一定是写漏了。"""
    assert all(k and v for k, v in STATE_LABELS.items())


def test_humanize_loc_translates_keys_and_one_bases_indexes():
    assert humanize_loc(("instances", 0, "characters", 1, "march_preset")) == \
        "模拟器 / 第1个 / 角色 / 第2个 / 行军预设"


def test_humanize_loc_keeps_unknown_segments():
    assert humanize_loc(("instances", 0, "brand_new_field")) == \
        "模拟器 / 第1个 / brand_new_field"


def test_humanize_loc_empty_for_root_level_error():
    """根级（跨字段）错误 loc 为空；调用方负责给个「整体配置」的兜底标题。"""
    assert humanize_loc(()) == ""


@pytest.mark.parametrize("key", [
    "app", "instances", "characters", "target_levels", "march_troop_types",
    "fill_target_leaders", "mumu_index", "adb_address", "anti_detection",
])
def test_known_config_keys_are_translated(key):
    assert humanize_loc((key,)) != key


def test_all_anti_detection_fields_have_chinese_labels():
    """配置校验报错会把 loc 翻中文；漏一个就露出英文键名。"""
    from rok_assistant.infra.anti_detection import AntiDetectionConfig
    from rok_assistant.gui.labels import LOC_LABELS
    import dataclasses
    for f in dataclasses.fields(AntiDetectionConfig):
        assert f.name in LOC_LABELS, f"缺 {f.name} 的中文名"
