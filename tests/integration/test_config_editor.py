import pytest
from pathlib import Path
import yaml
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _valid_config_dict() -> dict:
    """A minimal config that passes RootConfig schema (1 account, 1 leader)."""
    return {
        "app": {"screen_width": 1280, "screen_height": 720},
        "accounts": [
            {
                "id": "acc1",
                "window_title_pattern": "MuMu",
                "characters": [
                    {
                        "id": "c1",
                        "name": "Hero",
                        "role": "leader",
                        "target_level": 8,
                        "march_preset": 1,
                        "march_troop_types": ["infantry"],
                    }
                ],
            }
        ],
    }


def test_editor_loads_yaml(tmp_path, qapp):
    from rok_assistant.gui.config_editor import ConfigEditor
    cfg = tmp_path / "test.yaml"
    cfg.write_text(yaml.safe_dump(_valid_config_dict()))
    ed = ConfigEditor(config_path=cfg)
    text = ed.toPlainText()
    assert "1280" in text


def test_editor_save_writes_file(tmp_path, qapp):
    from rok_assistant.gui.config_editor import ConfigEditor
    cfg = tmp_path / "test.yaml"
    cfg.write_text(yaml.safe_dump(_valid_config_dict()))
    ed = ConfigEditor(config_path=cfg)
    new_dict = _valid_config_dict()
    new_dict["app"]["screen_width"] = 800
    ed.setPlainText(yaml.safe_dump(new_dict))
    assert ed.save()
    loaded = yaml.safe_load(cfg.read_text())
    assert loaded["app"]["screen_width"] == 800


def test_editor_rejects_invalid_schema(tmp_path, qapp):
    """Schema-invalid YAML (target_level=11, out of 1-10) must NOT be saved."""
    from rok_assistant.gui.config_editor import ConfigEditor
    cfg = tmp_path / "test.yaml"
    cfg.write_text(yaml.safe_dump(_valid_config_dict()))
    ed = ConfigEditor(config_path=cfg)
    bad = _valid_config_dict()
    bad["accounts"][0]["characters"][0]["target_level"] = 11  # out of range
    ed.setPlainText(yaml.safe_dump(bad))
    assert ed.save() is False
    # Original file unchanged
    loaded = yaml.safe_load(cfg.read_text())
    assert loaded["accounts"][0]["characters"][0]["target_level"] == 8


def test_editor_rejects_empty_accounts(tmp_path, qapp):
    """Empty accounts list violates RootConfig min_length=1; must be rejected."""
    from rok_assistant.gui.config_editor import ConfigEditor
    cfg = tmp_path / "test.yaml"
    cfg.write_text(yaml.safe_dump(_valid_config_dict()))
    ed = ConfigEditor(config_path=cfg)
    ed.setPlainText("app: {}\naccounts: []\n")
    assert ed.save() is False
