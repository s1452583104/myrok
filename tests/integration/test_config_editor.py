import pytest
from pathlib import Path
import yaml
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app

def test_editor_loads_yaml(tmp_path, qapp):
    from rok_assistant.gui.config_editor import ConfigEditor
    cfg = tmp_path / "test.yaml"
    cfg.write_text(yaml.safe_dump({"app": {"screen_width": 1280}, "accounts": []}))
    ed = ConfigEditor(config_path=cfg)
    text = ed.toPlainText()
    assert "1280" in text

def test_editor_save_writes_file(tmp_path, qapp):
    from rok_assistant.gui.config_editor import ConfigEditor
    cfg = tmp_path / "test.yaml"
    cfg.write_text("app: {}\naccounts: []\n")
    ed = ConfigEditor(config_path=cfg)
    ed.setPlainText("app:\n  screen_width: 800\naccounts: []\n")
    assert ed.save()
    loaded = yaml.safe_load(cfg.read_text())
    assert loaded["app"]["screen_width"] == 800
