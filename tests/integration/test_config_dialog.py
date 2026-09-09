import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import yaml
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from rok_assistant.gui.config_dialog import ConfigDialog


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _valid_config_dict() -> dict:
    return {
        "app": {"mumu_manager_path": "C:/mumu/MuMuManager.exe", "adb_path": "adb"},
        "instances": [
            {
                "id": "inst0", "name": "阑珊号", "mumu_index": 0,
                "characters": [
                    {"id": "c1", "name": "Hero", "role": "leader", "target_level": 8,
                     "march_preset": 1, "march_troop_types": ["infantry"]},
                    {"id": "c2", "name": "M1", "role": "member", "target_level": 5,
                     "march_preset": 2, "march_troop_types": ["cavalry"],
                     "fill_target_leaders": [{"instance": "inst0", "name": "Hero"}]},
                ],
            }
        ],
    }


def _write_config(tmp_path, data=None) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(data or _valid_config_dict()), encoding="utf-8")
    return cfg


def test_dialog_loads_and_builds_tree(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    labels = [dlg._tree.topLevelItem(i).text(0) for i in range(dlg._tree.topLevelItemCount())]
    assert any("阑珊号" in t for t in labels)
    assert any("全局设置" in t for t in labels)


def test_save_writes_yaml(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    cfg = _write_config(tmp_path)
    dlg = ConfigDialog(cfg)
    dlg._data["app"]["mumu_manager_path"] = "C:/other/MuMuManager.exe"
    assert dlg.save() is True
    loaded = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert loaded["app"]["mumu_manager_path"] == "C:/other/MuMuManager.exe"
    assert loaded["instances"][0]["characters"][1]["fill_target_leaders"][0]["name"] == "Hero"


def test_save_rejects_invalid_and_keeps_file(tmp_path, qapp, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: errors.append(k.get("text") or (a[2] if len(a) > 2 else "")))
    cfg = _write_config(tmp_path)
    dlg = ConfigDialog(cfg)
    dlg._data["instances"][0]["characters"][1]["fill_target_leaders"] = []
    assert dlg.save() is False
    assert any("fill_target_leaders" in e for e in errors)
    loaded = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert loaded["instances"][0]["characters"][1]["fill_target_leaders"] == [
        {"instance": "inst0", "name": "Hero"}]


def test_yaml_preview_reflects_data(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._refresh_yaml_preview()
    assert "阑珊号" in dlg._yaml_view.toPlainText()
    assert "fill_target_leaders" in dlg._yaml_view.toPlainText()
