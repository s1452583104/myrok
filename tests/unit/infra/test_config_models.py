import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import (
    AppConfig, InstanceConfig, CharacterConfig, RoleEnum, FillLeader, RootConfig
)


def _leader(**kw):
    base = dict(id="c1", name="Hero", role=RoleEnum.LEADER, target_level=8,
                march_preset=1, march_troop_types=["infantry"])
    base.update(kw)
    return CharacterConfig(**base)


def _member(**kw):
    base = dict(id="c2", name="M1", role=RoleEnum.MEMBER, target_level=5,
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
    with pytest.raises(ValidationError, match="fill_target_leaders"):
        _root(_leader(), _member(fill_target_leaders=[]))


def test_either_role_with_fill_targets():
    c = _member(id="c3", name="F1", role=RoleEnum.EITHER)
    assert c.role == RoleEnum.EITHER


def test_either_requires_fill_targets():
    with pytest.raises(ValidationError, match="fill_target_leaders"):
        _root(_leader(), _member(id="c3", name="F1", role=RoleEnum.EITHER,
                                 fill_target_leaders=[]))


def test_leader_must_not_have_fill_targets():
    with pytest.raises(ValidationError, match="leader"):
        _root(_leader(fill_target_leaders=[FillLeader(instance="i1", name="X")]))


def test_instance_requires_leader_or_either():
    with pytest.raises(ValidationError, match="no leader"):
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
    with pytest.raises(ValidationError, match="Duplicate instance"):
        RootConfig(instances=[InstanceConfig(id="i1", mumu_index=0, characters=[_leader()]),
                              InstanceConfig(id="i1", mumu_index=1, characters=[_leader(id="c9", name="H2")])])


def test_duplicate_character_ids():
    with pytest.raises(ValidationError, match="Duplicate character"):
        RootConfig(instances=[InstanceConfig(id="i1", mumu_index=0, characters=[_leader()]),
                              InstanceConfig(id="i2", mumu_index=1, characters=[_leader(name="H2")])])


def test_app_config_mumu_fields():
    app = AppConfig()
    assert app.mumu_manager_path == ""
    assert app.adb_path == "adb"
