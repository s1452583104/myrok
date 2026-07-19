import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import (
    AppConfig, AccountConfig, CharacterConfig, RoleEnum, FillLeader, RootConfig
)


def test_character_config_leader_minimal():
    c = CharacterConfig(
        id="char1", name="Hero", role=RoleEnum.LEADER,
        target_level=8, march_preset=1,
        march_troop_types=["infantry", "archer"]
    )
    assert c.id == "char1"
    assert c.role == RoleEnum.LEADER


def test_character_config_member_with_nearest():
    c = CharacterConfig(
        id="char2", name="M1", role=RoleEnum.MEMBER,
        target_level=5, march_preset=2,
        march_troop_types=["infantry"],
        fill_target_leaders="nearest"
    )
    assert c.fill_target_leaders == "nearest"


def test_character_config_member_with_specific_leaders():
    c = CharacterConfig(
        id="char3", name="M2", role=RoleEnum.MEMBER,
        target_level=4, march_preset=3,
        march_troop_types=["cavalry"],
        fill_target_leaders=[FillLeader(account="acc1", name="Boss")]
    )
    assert isinstance(c.fill_target_leaders, list)
    assert c.fill_target_leaders[0].account == "acc1"


def test_character_config_invalid_target_level():
    with pytest.raises(ValidationError):
        CharacterConfig(
            id="x", name="X", role=RoleEnum.LEADER,
            target_level=11, march_preset=1, march_troop_types=["infantry"]
        )


def test_character_config_invalid_march_preset():
    with pytest.raises(ValidationError):
        CharacterConfig(
            id="x", name="X", role=RoleEnum.LEADER,
            target_level=5, march_preset=6, march_troop_types=["infantry"]
        )


def test_app_config_default_anti_detection():
    app = AppConfig()
    assert app.anti_detection.click_offset_px == 8
    assert app.anti_detection.debug_no_jitter is False


def test_root_config_requires_at_least_one_account():
    with pytest.raises(ValidationError):
        RootConfig(accounts=[])
