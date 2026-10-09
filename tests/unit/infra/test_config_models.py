import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import (
    AppConfig, InstanceConfig, CharacterConfig, RoleEnum, FillLeader, RootConfig
)


def _leader(**kw):
    base = dict(id="c1", name="Hero", role=RoleEnum.LEADER, target_levels=[8],
                march_preset=1, march_troop_types=["infantry"])
    base.update(kw)
    return CharacterConfig(**base)


def _member(**kw):
    base = dict(id="c2", name="M1", role=RoleEnum.MEMBER, target_levels=[5],
                march_preset=2, march_troop_types=["cavalry"],
                fill_target_leaders=[FillLeader(instance="i1", name="Hero")])
    base.update(kw)
    return CharacterConfig(**base)


def _root(*characters) -> RootConfig:
    return RootConfig(instances=[InstanceConfig(
        id="i1", mumu_index=0, characters=list(characters))])


def test_leader_minimal():
    c = _leader()
    assert c.role == RoleEnum.LEADER
    assert c.fill_target_leaders == []


def test_member_requires_fill_targets():
    with pytest.raises(ValidationError, match="必须配置"):
        _root(_leader(), _member(fill_target_leaders=[]))


def test_either_role_roundtrip():
    cfg = _root(_leader(),
                _member(id="c3", name="F1", role=RoleEnum.EITHER))
    either = cfg.instances[0].characters[1]
    assert either.role == RoleEnum.EITHER
    assert either.fill_target_leaders[0].name == "Hero"


def test_either_requires_fill_targets():
    with pytest.raises(ValidationError, match="必须配置"):
        _root(_leader(), _member(id="c3", name="F1", role=RoleEnum.EITHER,
                                 fill_target_leaders=[]))


def test_leader_must_not_have_fill_targets():
    with pytest.raises(ValidationError, match="不能配置"):
        _root(_leader(fill_target_leaders=[FillLeader(instance="i1", name="X")]))


def test_instance_requires_leader_or_either():
    with pytest.raises(ValidationError, match="整个配置至少需要"):
        _root(_member(id="c9", name="OnlyM"))


def test_instance_duplicate_names():
    with pytest.raises(ValidationError, match="duplicate"):
        _root(_leader(), _member(name="Hero"))


def test_mumu_and_adb_both_set_rejected():
    with pytest.raises(ValidationError, match="只能填一个"):
        RootConfig(instances=[InstanceConfig(
            id="i1", mumu_index=0, adb_address="127.0.0.1:16384",
            characters=[_leader()])])


def test_mumu_and_adb_both_empty_rejected():
    with pytest.raises(ValidationError, match="必须填一个"):
        RootConfig(instances=[InstanceConfig(id="i1", characters=[_leader()])])


def test_window_title_pattern_optional():
    inst = InstanceConfig(id="i1", mumu_index=0, characters=[_leader()])
    assert inst.window_title_pattern == ""


def test_fill_target_must_exist():
    with pytest.raises(ValidationError, match="不存在"):
        _root(_leader(),
              _member(fill_target_leaders=[FillLeader(instance="i1", name="Ghost")]))


def test_fill_target_must_be_leader_or_either():
    with pytest.raises(ValidationError, match="leader/either"):
        _root(_leader(), _member(),
              _member(id="c3", name="M2",
                      fill_target_leaders=[FillLeader(instance="i1", name="M1")]))


def test_cross_instance_fill_target_ok():
    a = InstanceConfig(id="i1", mumu_index=0, characters=[_leader()])
    b = InstanceConfig(id="i2", mumu_index=1,
                       characters=[_member(fill_target_leaders=[FillLeader(instance="i1", name="Hero")])])
    cfg = RootConfig(instances=[a, b])
    assert cfg.instances[1].characters[0].fill_target_leaders[0].instance == "i1"


def test_duplicate_instance_ids():
    with pytest.raises(ValidationError, match="实例 id 重复"):
        RootConfig(instances=[InstanceConfig(id="i1", mumu_index=0, characters=[_leader()]),
                              InstanceConfig(id="i1", mumu_index=1, characters=[_leader(id="c9", name="H2")])])


def test_duplicate_character_ids():
    with pytest.raises(ValidationError, match="角色 id 重复"):
        RootConfig(instances=[InstanceConfig(id="i1", mumu_index=0, characters=[_leader()]),
                              InstanceConfig(id="i2", mumu_index=1, characters=[_leader(name="H2")])])


def test_app_config_mumu_fields():
    app = AppConfig()
    assert app.mumu_manager_path == ""
    assert app.adb_path == "adb"


# ---- target_levels 多选（2026-10-04）----

def test_target_levels_order_is_preserved():
    """顺序完全自由（用户明确要求 6→4→5 合法）：校验不得重排。"""
    c = _leader(target_levels=[6, 4, 5])
    assert c.target_levels == [6, 4, 5]


def test_target_levels_empty_rejected():
    with pytest.raises(ValidationError, match="不能为空"):
        _leader(target_levels=[])


def test_target_levels_too_many_rejected():
    with pytest.raises(ValidationError, match="最多 3 个"):
        _leader(target_levels=[8, 7, 6, 5])


def test_target_levels_out_of_range_rejected():
    with pytest.raises(ValidationError, match="1..10"):
        _leader(target_levels=[11])


def test_target_levels_duplicate_rejected():
    with pytest.raises(ValidationError, match="有重复"):
        _leader(target_levels=[7, 7])


def test_target_levels_three_is_allowed():
    assert _leader(target_levels=[9, 8, 7]).target_levels == [9, 8, 7]


# ---- 多预设（2026-10-09）----

def test_march_presets_new_field_kept_in_order():
    c = _leader(march_presets=[{"preset": 3, "troops": ["archer"]},
                               {"preset": 1, "troops": ["infantry", "cavalry"]}])
    assert [p.preset for p in c.march_presets] == [3, 1]      # 顺序就是优先级
    assert c.march_presets[1].troops == ["infantry", "cavalry"]


def test_legacy_fields_migrate_into_one_preset():
    """老 config.yaml（只写 march_preset + march_troop_types）不改也能读。"""
    c = _leader()
    assert len(c.march_presets) == 1
    assert c.march_presets[0].preset == 1
    assert c.march_presets[0].troops == ["infantry"]


def test_march_presets_win_over_legacy_fields():
    """两者都写时以新字段为准，旧字段不参与。"""
    c = _leader(march_presets=[{"preset": 4, "troops": ["cavalry"]}],
                march_preset=2, march_troop_types=["archer"])
    assert len(c.march_presets) == 1
    assert c.march_presets[0].preset == 4


def test_neither_new_nor_legacy_field_raises():
    with pytest.raises(ValidationError, match="march_presets"):
        _leader(march_preset=None, march_troop_types=[])


def test_march_presets_reject_empty_troops():
    with pytest.raises(ValidationError, match="兵种"):
        _leader(march_presets=[{"preset": 1, "troops": []}])


def test_march_presets_reject_too_many():
    with pytest.raises(ValidationError, match="最多"):
        _leader(march_presets=[{"preset": 1, "troops": ["infantry"]},
                               {"preset": 2, "troops": ["infantry"]},
                               {"preset": 3, "troops": ["infantry"]},
                               {"preset": 4, "troops": ["infantry"]}])


def test_march_presets_reject_duplicate_slot():
    """同一槽位出现两次：第二条永远轮不到，是配置错误不是回退。"""
    with pytest.raises(ValidationError, match="重复"):
        _leader(march_presets=[{"preset": 2, "troops": ["infantry"]},
                               {"preset": 2, "troops": ["cavalry"]}])


def test_march_presets_reject_out_of_range_slot():
    with pytest.raises(ValidationError):
        _leader(march_presets=[{"preset": 6, "troops": ["infantry"]}])
