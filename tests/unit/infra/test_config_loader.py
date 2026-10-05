from pathlib import Path
import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import load_config, RootConfig

FIX = Path(__file__).parent.parent.parent / "fixtures"


def test_load_valid_config():
    cfg = load_config(FIX / "config_valid.yaml")
    assert isinstance(cfg, RootConfig)
    assert len(cfg.instances) == 1
    assert cfg.instances[0].id == "inst0"
    assert cfg.instances[0].name == "阑珊号"
    assert cfg.app.mumu_manager_path.endswith("MuMuManager.exe")


def test_load_no_leader_raises():
    with pytest.raises(ValidationError, match="整个配置至少需要"):
        load_config(FIX / "config_no_leader.yaml")


def test_load_invalid_level_raises():
    with pytest.raises(ValidationError, match="target_levels"):
        load_config(FIX / "config_invalid_level.yaml")
