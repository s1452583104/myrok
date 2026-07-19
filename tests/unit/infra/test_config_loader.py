from pathlib import Path
import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import load_config, RootConfig

FIX = Path(__file__).parent.parent.parent / "fixtures"


def test_load_valid_config():
    cfg = load_config(FIX / "config_valid.yaml")
    assert isinstance(cfg, RootConfig)
    assert len(cfg.accounts) == 1
    assert cfg.accounts[0].id == "test_account"


def test_load_no_leader_raises():
    with pytest.raises(ValidationError, match="no leader"):
        load_config(FIX / "config_no_leader.yaml")


def test_load_invalid_level_raises():
    with pytest.raises(ValidationError, match="target_level"):
        load_config(FIX / "config_invalid_level.yaml")
