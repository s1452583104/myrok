import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import yaml
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QAbstractItemView, QMessageBox

from rok_assistant.gui.config_dialog import ConfigDialog
from rok_assistant.gui.config_dialog import CharacterEditDialog
from rok_assistant.gui.config_dialog import ROLE_LABELS


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


def test_save_failure_keeps_data_and_returns_false(tmp_path, qapp, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: errors.append(k.get("text") or (a[2] if len(a) > 2 else "")))
    cfg = _write_config(tmp_path)
    dlg = ConfigDialog(cfg)

    def _raise(*a, **k):
        raise PermissionError("file locked by editor")

    monkeypatch.setattr(Path, "write_text", _raise)
    assert dlg.save() is False
    assert any("无法写入" in e for e in errors)


def test_clamped_spin_preserves_original_value(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    data = _valid_config_dict()
    data["app"].setdefault("anti_detection", {})["click_offset_px"] = 100
    dlg = ConfigDialog(_write_config(tmp_path, data))
    assert dlg._data["app"]["anti_detection"]["click_offset_px"] == 100
    w = dlg._widgets[("app", "anti_detection", "click_offset_px")]
    assert "超出范围" in w.toolTip()


def test_tree_navigation_switches_stack(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._tree.setCurrentItem(dlg._tree.topLevelItem(2))
    assert dlg._stack.currentIndex() == 2
    dlg._data["app"]["adb_path"] = "C:/x/adb.exe"
    dlg._tree.setCurrentItem(dlg._tree.topLevelItem(1))
    assert dlg._stack.currentIndex() == 1
    assert "C:/x/adb.exe" in dlg._yaml_view.toPlainText()


def test_on_save_accepts_only_when_valid(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._on_save()
    assert dlg.result() == 1
    dlg2 = ConfigDialog(_write_config(tmp_path))
    dlg2._data["instances"][0]["characters"][1]["fill_target_leaders"] = []
    dlg2._on_save()
    assert dlg2.result() == 0


def test_yaml_preview_reflects_data(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._refresh_yaml_preview()
    assert "阑珊号" in dlg._yaml_view.toPlainText()
    assert "fill_target_leaders" in dlg._yaml_view.toPlainText()


def test_add_instance_generates_unique_id(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._add_instance()
    assert len(dlg._data["instances"]) == 2
    assert dlg._data["instances"][1]["id"] == "inst1"
    assert dlg._data["instances"][1]["characters"] == []
    # 新实例不合法（无角色），保存必须被拒
    assert dlg.save() is False


def test_add_and_edit_character_roundtrip(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    char = {"id": "c9", "name": "New", "role": "either", "target_level": 7,
            "march_preset": 3, "march_troop_types": ["archer"],
            "fill_target_leaders": [{"instance": "inst0", "name": "Hero"}]}
    dlg._save_character(0, None, char)
    chars = dlg._data["instances"][0]["characters"]
    assert len(chars) == 3
    assert chars[2]["role"] == "either"
    assert dlg.save() is True
    loaded = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert loaded["instances"][0]["characters"][2]["name"] == "New"


def test_character_edit_dialog_rejects_member_without_fills(qapp):
    dlg = CharacterEditDialog(None, None, [{"instance": "inst0", "name": "Hero"}])
    dlg.name_edit.setText("X")
    dlg.role_combo.setCurrentText(ROLE_LABELS["member"])
    assert dlg.validate() is not None  # 返回错误信息（非 None）


def test_delete_character(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._delete_character(0, 1)  # 删 M1（有 fill target 引用，删除后 leader 无妨）
    assert [c["name"] for c in dlg._data["instances"][0]["characters"]] == ["Hero"]
    assert dlg.save() is True


def test_delete_character_with_incoming_reference_blocks_save(tmp_path, qapp, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: errors.append(str(a)))
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._delete_character(0, 0)  # 删 Hero；M1 的填兵目标悬空
    assert dlg.save() is False


def test_manual_adb_instance_keeps_none_mumu_index(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    data = _valid_config_dict()
    inst = data["instances"][0]
    inst["mumu_index"] = None
    inst["adb_address"] = "127.0.0.1:16384"
    dlg = ConfigDialog(_write_config(tmp_path, data))
    assert dlg._data["instances"][0]["mumu_index"] is None
    assert dlg._data["instances"][0]["adb_address"] == "127.0.0.1:16384"


def test_table_has_no_inline_edit(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    assert dlg._tables[0].editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers


def test_delete_instance_requires_confirmation(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    def _no(*a, **k):
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", _no)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._delete_instance(0)
    assert len(dlg._data["instances"]) == 1  # 回答 No → 不删

    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    dlg._delete_instance(0)
    assert dlg._data["instances"] == []  # 回答 Yes → 删除


def test_rename_propagates_to_fill_targets(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    hero = dict(dlg._data["instances"][0]["characters"][0])
    dlg._save_character(0, hero, dict(hero, name="Hero2"))
    m1 = dlg._data["instances"][0]["characters"][1]
    assert m1["fill_target_leaders"] == [{"instance": "inst0", "name": "Hero2"}]
    assert dlg.save() is True


def test_mode_switch_to_mumu_clears_addr_field(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    data = _valid_config_dict()
    inst = data["instances"][0]
    inst["mumu_index"] = None
    inst["adb_address"] = "127.0.0.1:16384"
    dlg = ConfigDialog(_write_config(tmp_path, data))
    dlg._mode_combos[0].setCurrentIndex(0)
    assert dlg._data["instances"][0]["mumu_index"] == 0
    assert dlg._data["instances"][0]["adb_address"] == ""
    assert dlg._widgets[("instances", 0, "adb_address")].text() == ""


def test_reload_tree_preserves_selection(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._tree.setCurrentItem(dlg._tree.topLevelItem(2))  # 实例 0
    dlg._add_instance()
    cur = dlg._tree.currentItem()
    assert cur.data(0, Qt.ItemDataRole.UserRole) == ("page", 0)


def test_test_connection_reports_error(tmp_path, qapp, monkeypatch):
    dlg = ConfigDialog(_write_config(tmp_path))

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("no adb")

    monkeypatch.setattr("rok_assistant.gui.config_dialog.create_handle_source", Boom)
    dlg._test_connection(0)
    assert "连接失败" in dlg._status_labels[0].text()


def test_test_connection_unconfigured_shows_hint(tmp_path, qapp, monkeypatch):
    data = _valid_config_dict()
    data["instances"][0]["mumu_index"] = None
    data["instances"][0]["adb_address"] = "127.0.0.1:16384"  # 先合法加载
    dlg = ConfigDialog(_write_config(tmp_path, data))
    dlg._data["instances"][0]["adb_address"] = ""  # 模拟用户清空了地址
    dlg._test_connection(0)
    assert "未配置" in dlg._status_labels[0].text()


def test_detect_all_instances_lists_status(tmp_path, qapp, monkeypatch):
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._detect_all_instances()
    assert "inst0" in dlg._detect_output.toPlainText()


def test_main_window_has_config_button(qapp, monkeypatch):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow()
    assert w.config_btn.text().endswith("配置")
