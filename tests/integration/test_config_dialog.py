import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import yaml
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QAbstractItemView, QMessageBox

from rok_assistant.gui.config_dialog import ConfigDialog
from rok_assistant.gui.config_dialog import CharacterEditDialog
from rok_assistant.gui.labels import ROLE_LABELS
from rok_assistant.infra.mumu import MumuLocatorError, MumuNotRunningError


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
                    {"id": "c1", "name": "Hero", "role": "leader",
                     "target_levels": [8, 7, 6],   # 多选：顺带覆盖表格渲染
                     "march_preset": 1, "march_troop_types": ["infantry"]},
                    {"id": "c2", "name": "M1", "role": "member", "target_levels": [5],
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
    # 与首启模板同前缀（mumu0/1…），不是另起一套叫法
    assert dlg._data["instances"][1]["id"] == "mumu0"
    dlg._add_instance()                       # 再加一台必须拿到不重名的 id
    assert dlg._data["instances"][2]["id"] == "mumu1"
    assert dlg._data["instances"][1]["characters"] == []
    # 新实例不合法（无角色），保存必须被拒
    assert dlg.save() is False


def test_add_and_edit_character_roundtrip(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    char = {"id": "c9", "name": "New", "role": "either", "target_levels": [7],
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
    """切到「按模拟器选择」要清掉手填的 adb 地址。

    没选中任何模拟器时 mumu_index 保持 None（以前是硬写成 0 —— 那正是
    「让用户猜一个界面上不存在的数字」的来源）。
    """
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    data = _valid_config_dict()
    inst = data["instances"][0]
    inst["mumu_index"] = None
    inst["adb_address"] = "127.0.0.1:16384"
    dlg = ConfigDialog(_write_config(tmp_path, data))
    dlg._mode_combos[0].setCurrentIndex(0)
    assert dlg._data["instances"][0]["adb_address"] == ""
    assert dlg._widgets[("instances", 0, "adb_address")].text() == ""
    assert dlg._data["instances"][0]["mumu_index"] is None


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
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch)
    dlg = _open(_write_config(tmp_path), qapp)
    dlg._detect_all_instances()
    out = dlg._detect_output.toPlainText()
    assert "模拟器 0 · 如愿：● 运行中" in out
    assert "inst0" not in out          # 内部 id 不再暴露给用户


def test_detect_all_instances_marks_stopped(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch)
    data = _valid_config_dict()
    data["instances"][0]["mumu_index"] = 2      # 「如愿-2」未启动
    dlg = _open(_write_config(tmp_path, data), qapp)
    dlg._detect_all_instances()
    assert "○ 未启动" in dlg._detect_output.toPlainText()


def test_detect_all_instances_handles_missing_index(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch)
    data = _valid_config_dict()
    data["instances"][0]["mumu_index"] = 7      # MuMu 里没这台
    dlg = _open(_write_config(tmp_path, data), qapp)
    dlg._detect_all_instances()
    assert "没找到编号 7" in dlg._detect_output.toPlainText()


# ---- 扫描模拟器 / 按名字选（2026-10-05）----

SCAN_RESULT = [
    {"index": 0, "name": "如愿", "running": True, "adb_address": "127.0.0.1:16384"},
    {"index": 1, "name": "15634025219", "running": False, "adb_address": None},
    {"index": 2, "name": "如愿-2", "running": False, "adb_address": None},
]


def _stub_scan(monkeypatch, result=None, error=None):
    def _fake(_manager, _runner=None):
        if error is not None:
            raise error
        return list(result if result is not None else SCAN_RESULT)
    monkeypatch.setattr("rok_assistant.gui.config_dialog.list_instances", _fake)


def _rows(dlg, idx=0) -> list[str]:
    lst = dlg._instance_lists[idx]
    return [lst.item(i).text() for i in range(lst.count())]


def _open(cfg, qapp) -> ConfigDialog:
    """构造对话框并让事件循环跑一拍 —— 首次扫描是 QTimer.singleShot(0) 排的，
    这样窗口能先画出来，不被 MuMuManager 的查询卡在构造函数里。"""
    dlg = ConfigDialog(cfg)
    qapp.processEvents()
    return dlg


def test_scan_lists_emulators_by_name_with_state(tmp_path, qapp, monkeypatch):
    """列表要显示 MuMu 里的名字和运行状态——用户就是照这个名字认机器的。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch)
    dlg = _open(_write_config(tmp_path), qapp)
    assert _rows(dlg) == ["● 如愿 · 运行中", "○ 15634025219 · 未启动", "○ 如愿-2 · 未启动"]


def test_scan_runs_once_at_open_and_is_cached(tmp_path, qapp, monkeypatch):
    """打开对话框时自动扫一次；切页/重扫按钮之外不该反复起子进程。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    calls = []

    def _counting(manager, _runner=None):
        calls.append(manager)
        return list(SCAN_RESULT)

    monkeypatch.setattr("rok_assistant.gui.config_dialog.list_instances", _counting)
    dlg = _open(_write_config(tmp_path), qapp)
    assert len(calls) == 1
    dlg._add_instance()             # 重建树不该触发重扫
    assert len(calls) == 1
    dlg._rescan()                   # 显式点按钮才再扫
    assert len(calls) == 2


def test_picking_by_name_sets_mumu_index(tmp_path, qapp, monkeypatch):
    """选中「如愿-2」→ mumu_index = 2（用户全程没看到数字）。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch)
    data = _valid_config_dict()
    data["instances"][0]["mumu_index"] = None
    data["instances"][0]["adb_address"] = "127.0.0.1:16384"   # 先以手动模式合法加载
    data["instances"][0]["name"] = ""
    dlg = _open(_write_config(tmp_path, data), qapp)
    dlg._mode_combos[0].setCurrentIndex(0)      # 切到「按模拟器选择」
    assert dlg._data["instances"][0]["adb_address"] == ""
    dlg._instance_lists[0].setCurrentRow(2)     # ○ 如愿-2 · 未启动
    assert dlg._data["instances"][0]["mumu_index"] == 2
    # 显示名空着时顺手填上，省得用户再想一个
    assert dlg._data["instances"][0]["name"] == "如愿-2"


def test_picking_does_not_overwrite_existing_display_name(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch)
    dlg = _open(_write_config(tmp_path), qapp)   # name 已是「阑珊号」
    dlg._instance_lists[0].setCurrentRow(0)
    assert dlg._data["instances"][0]["mumu_index"] == 0
    assert dlg._data["instances"][0]["name"] == "阑珊号"


def test_autofilled_name_follows_re_pick(tmp_path, qapp, monkeypatch):
    """点几行比较一下是常态：换选后显示名必须跟着换。

    真机走查抓到过——先点「15634025219」再点「如愿」，结果选中的是如愿
    （mumu_index=0）而显示名停在 15634025219，用户根本认不出自己选的是哪台。
    """
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch)
    data = _valid_config_dict()
    data["instances"][0]["mumu_index"] = None
    data["instances"][0]["adb_address"] = "127.0.0.1:16384"
    data["instances"][0]["name"] = ""
    dlg = _open(_write_config(tmp_path, data), qapp)
    dlg._mode_combos[0].setCurrentIndex(0)
    lst = dlg._instance_lists[0]
    lst.setCurrentRow(1)
    assert dlg._data["instances"][0]["name"] == "15634025219"
    lst.setCurrentRow(0)                       # 改选「如愿」
    assert dlg._data["instances"][0]["mumu_index"] == 0
    assert dlg._data["instances"][0]["name"] == "如愿"
    assert dlg._widgets[("instances", 0, "name")].text() == "如愿"


def test_autofilled_name_never_clobbers_typed_name(tmp_path, qapp, monkeypatch):
    """用户自己敲的名字，换选也不许动。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch)
    data = _valid_config_dict()
    data["instances"][0]["mumu_index"] = None
    data["instances"][0]["adb_address"] = "127.0.0.1:16384"
    data["instances"][0]["name"] = ""
    dlg = _open(_write_config(tmp_path, data), qapp)
    dlg._mode_combos[0].setCurrentIndex(0)
    lst = dlg._instance_lists[0]
    lst.setCurrentRow(0)                       # 自动填成「如愿」
    dlg._widgets[("instances", 0, "name")].setText("我的小号")
    lst.setCurrentRow(2)                       # 再换选
    assert dlg._data["instances"][0]["name"] == "我的小号"


def test_existing_mumu_index_is_preselected(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch)
    dlg = _open(_write_config(tmp_path), qapp)   # mumu_index=0
    assert dlg._instance_lists[0].currentRow() == 0


def test_scan_failure_shows_hint_and_keeps_dialog_usable(tmp_path, qapp, monkeypatch):
    """MuMu 路径不对时不能让对话框崩掉，要留一行提示让人重试。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch, error=MumuLocatorError("无法运行 MuMuManager（请检查安装路径）: x"))
    dlg = _open(_write_config(tmp_path), qapp)
    rows = _rows(dlg)
    assert len(rows) == 1 and "无法运行 MuMuManager" in rows[0]
    assert dlg._instance_lists[0].count() == 1
    assert dlg._data["instances"][0]["mumu_index"] == 0   # 原配置没被动


def test_scan_without_manager_path_does_not_run_subprocess(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    data = _valid_config_dict()
    data["app"]["mumu_manager_path"] = ""
    _stub_scan(monkeypatch, result=[])          # 真被调用就会返回空而不是报错
    dlg = _open(_write_config(tmp_path, data), qapp)
    assert "还没填 MuMuManager 路径" in _rows(dlg)[0]


def test_test_connection_explains_stopped_emulator(tmp_path, qapp, monkeypatch):
    """第二容易踩的坑：模拟器没启动。报错要说清「去 MuMu 里启动它」。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_scan(monkeypatch)
    data = _valid_config_dict()
    data["instances"][0]["mumu_index"] = 2
    dlg = _open(_write_config(tmp_path, data), qapp)

    def _boom(*a, **k):
        raise MumuNotRunningError("MuMuManager 输出中未找到 adb 端口（模拟器 2 可能没有启动）")

    monkeypatch.setattr("rok_assistant.gui.config_dialog.create_handle_source", _boom)
    dlg._test_connection(0)
    text = dlg._status_labels[0].text()
    assert "如愿-2" in text and "没有启动" in text


def test_test_connection_explains_bad_manager_path(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))

    def _boom(*a, **k):
        raise MumuLocatorError("无法运行 MuMuManager（请检查安装路径）: [WinError 2]")

    monkeypatch.setattr("rok_assistant.gui.config_dialog.create_handle_source", _boom)
    dlg._test_connection(0)
    assert "自动检测" in dlg._status_labels[0].text()


def test_test_connection_explains_timeout_without_blaming_path(
        tmp_path, qapp, monkeypatch):
    """超时要让人「等一会儿重试」，不是去改路径。"""
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))

    def _boom(*a, **k):
        raise MumuLocatorError(
            "MuMuManager 超过 10 秒没有响应（模拟器可能正忙或刚启动，稍等一会再试）")

    monkeypatch.setattr("rok_assistant.gui.config_dialog.create_handle_source", _boom)
    dlg._test_connection(0)
    text = dlg._status_labels[0].text()
    assert "没有响应" in text
    assert "自动检测" not in text and "路径" not in text


def test_validation_error_path_is_humanized(tmp_path, qapp, monkeypatch):
    """校验弹窗不能再吐 `instances / 0 / characters / 1 / march_preset`。"""
    errors = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: errors.append(a[2] if len(a) > 2 else ""))
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._data["instances"][0]["characters"][1]["march_preset"] = "abc"
    assert dlg.save() is False
    joined = "\n".join(errors)
    assert "模拟器 / 第1个 / 角色 / 第2个 / 行军预设" in joined
    assert "instances /" not in joined


def test_model_validator_error_on_parent_path_is_humanized(tmp_path, qapp, monkeypatch):
    """跨字段校验（如 member 缺填兵目标）的错误落在父路径上，也要能读懂。"""
    errors = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: errors.append(a[2] if len(a) > 2 else ""))
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._data["instances"][0]["characters"][1]["fill_target_leaders"] = []
    assert dlg.save() is False
    joined = "\n".join(errors)
    assert "整体配置: Value error" in joined
    assert "instances" not in joined


def test_autodetect_fills_both_paths(tmp_path, qapp, monkeypatch):
    """「自动检测 MuMu/adb 路径」按钮：探测结果写进两个输入框并回写 _data。"""
    dlg = ConfigDialog(_write_config(tmp_path))
    monkeypatch.setattr(
        "rok_assistant.infra.mumu.detect_mumu_paths",
        lambda: {"mumu_manager_path": r"C:\模拟器\MuMuPlayer\nx_main\MuMuManager.exe",
                 "adb_path": r"C:\模拟器\MuMuPlayer\nx_main\adb.exe"})
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    dlg._autodetect_mumu_paths()

    assert dlg._data["app"]["mumu_manager_path"].endswith("MuMuManager.exe")
    assert dlg._data["app"]["adb_path"].endswith("adb.exe")


def test_autodetect_warns_when_nothing_found(tmp_path, qapp, monkeypatch):
    """探测不到要明确告知，不能静默留空让用户以为填好了。"""
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._mumu_line.setText("")
    monkeypatch.setattr("rok_assistant.infra.mumu.detect_mumu_paths",
                        lambda: {"mumu_manager_path": "", "adb_path": ""})
    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.append(a[2] if len(a) > 2 else ""))

    dlg._autodetect_mumu_paths()

    assert warned and "手动" in warned[0]


def test_main_window_has_config_button(qapp, monkeypatch):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow()
    assert w.config_btn.text().endswith("配置")


# ---- 目标城寨等级 1–10 复选框（2026-10-04）----

def _char(levels, role="leader", **kw):
    c = {"id": "c1", "name": "H", "role": role, "target_levels": levels,
         "march_preset": 1, "march_troop_types": ["infantry"]}
    c.update(kw)
    return c


def _checked(dlg) -> list[int]:
    return sorted(lv for lv, cb in dlg.level_checks.items() if cb.isChecked())


def test_level_boxes_initialized_from_config_in_order(qapp):
    """配置里的顺序必须原样保留（不能按等级大小重排）。"""
    dlg = CharacterEditDialog(None, _char([6, 4, 5]), [])
    assert dlg._level_order == [6, 4, 5]
    assert _checked(dlg) == [4, 5, 6]
    assert "6 → 4 → 5" in dlg.level_order_label.text()
    assert dlg.get_result()["target_levels"] == [6, 4, 5]


def test_level_click_order_becomes_search_order(qapp):
    """勾选顺序即搜索顺序：先点 6 再点 4 再点 5 → [6,4,5]。"""
    dlg = CharacterEditDialog(None, _char([7]), [])
    dlg.level_checks[7].setChecked(False)
    for lv in (6, 4, 5):
        dlg.level_checks[lv].setChecked(True)
    assert dlg._level_order == [6, 4, 5]
    assert dlg.get_result()["target_levels"] == [6, 4, 5]


def test_level_boxes_cap_at_three(qapp):
    """第 4 个勾不上，且选满后未选中的框被锁住。"""
    dlg = CharacterEditDialog(None, _char([7]), [])
    dlg.level_checks[7].setChecked(False)
    for lv in (8, 6, 5, 4):
        dlg.level_checks[lv].setChecked(True)
    assert dlg._level_order == [8, 6, 5]
    assert not dlg.level_checks[4].isChecked()
    assert not dlg.level_checks[4].isEnabled()
    assert dlg.level_checks[8].isEnabled()   # 已选中的仍可取消


def test_level_uncheck_removes_and_reopens_slots(qapp):
    dlg = CharacterEditDialog(None, _char([7]), [])
    dlg.level_checks[7].setChecked(False)
    for lv in (8, 6, 5):
        dlg.level_checks[lv].setChecked(True)
    dlg.level_checks[6].setChecked(False)
    assert dlg._level_order == [8, 5]
    assert dlg.level_checks[4].isEnabled()   # 腾出名额
    dlg.level_checks[4].setChecked(True)
    assert dlg._level_order == [8, 5, 4]


def test_level_recheck_moves_to_end(qapp):
    """重勾已取消过的等级会排到最后（顺序可调的手段）。"""
    dlg = CharacterEditDialog(None, _char([7]), [])
    dlg.level_checks[7].setChecked(False)
    for lv in (6, 5, 4):
        dlg.level_checks[lv].setChecked(True)
    dlg.level_checks[5].setChecked(False)
    dlg.level_checks[5].setChecked(True)
    assert dlg._level_order == [6, 4, 5]


def test_edit_dialog_rejects_no_level_selected(qapp):
    dlg = CharacterEditDialog(None, _char([7]), [])
    dlg.name_edit.setText("X")
    dlg.level_checks[7].setChecked(False)
    err = dlg.validate()
    assert err and "至少勾选" in err


def test_table_shows_search_order_arrow(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    assert dlg._tables[0].item(0, 2).text() == "8→7→6"
