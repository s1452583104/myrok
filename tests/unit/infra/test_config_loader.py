from pathlib import Path
import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import load_config, RootConfig

FIX = Path(__file__).parent.parent.parent / "fixtures"


def test_load_valid_config():
    cfg = load_config(FIX / "config_valid.yaml")
    assert isinstance(cfg, RootConfig)
    assert len(cfg.zhaiduo.instances) == 1
    assert cfg.zhaiduo.instances[0].id == "inst0"
    assert cfg.zhaiduo.instances[0].name == "阑珊号"
    assert cfg.app.mumu_manager_path.endswith("MuMuManager.exe")


def test_load_no_leader_raises():
    with pytest.raises(ValidationError, match="整个配置至少需要"):
        load_config(FIX / "config_no_leader.yaml")


def test_load_invalid_level_raises():
    with pytest.raises(ValidationError, match="target_levels"):
        load_config(FIX / "config_invalid_level.yaml")


def test_load_rejects_half_migrated_config(tmp_path):
    """顶层 instances 与 zhaiduo 同时存在（半迁移）也必须报错。

    旧守卫要求「zhaiduo 缺席」才拦，于是这种半迁移配置会被 pydantic 静默丢弃
    顶层那段、加载成功——对「硬报错、不迁移」的设计来说，静默丢数据比报错更糟。
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "instances:\n"
        "  - id: mumu0\n"
        "    characters: []\n"
        "zhaiduo:\n"
        "  instances:\n"
        "    - id: inst0\n"
        "      name: \"号\"\n"
        "      mumu_index: 0\n"
        "      characters:\n"
        "        - id: leader1\n"
        "          name: \"Hero\"\n"
        "          role: leader\n"
        "          target_levels: [8]\n"
        "          march_preset: 1\n"
        "          march_troop_types: [infantry]\n",
        encoding="utf-8")
    with pytest.raises(ValidationError, match="配置格式已更新"):
        load_config(cfg)
