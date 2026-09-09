"""可视化配置对话框：左树右表单（spec 2026-09-09 §5）。

数据模式：对话框持有 model_dump 出来的纯 dict（self._data），各表单写回
dict，保存时 RootConfig.model_validate 整体校验，避免编辑过程中产生
半合法的 pydantic 对象。self._widgets 记录 (路径元组)->控件，用于校验
错误时定位标红。
"""
from __future__ import annotations

from pathlib import Path
import uuid

import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from pydantic import ValidationError

from rok_assistant.core.handle_source import create_handle_source
from rok_assistant.infra.config import RootConfig, load_config

ROLE_LABELS = {"leader": "车头", "member": "成员", "either": "车头或成员"}
LABEL_ROLES = {v: k for k, v in ROLE_LABELS.items()}
TROOP_LABELS = {"infantry": "步兵", "cavalry": "骑兵", "archer": "弓兵"}

ERR_STYLE = "border: 1px solid red;"


class ConfigDialog(QDialog):
    def __init__(self, config_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("rok-assistant 配置")
        self.resize(880, 620)
        self._path = Path(config_path)
        self._data = load_config(self._path).model_dump(mode="json")
        self._widgets: dict[tuple, QWidget] = {}
        self._tables: dict[int, QTableWidget] = {}
        self._mode_combos: dict[int, QComboBox] = {}
        self._status_labels: dict[int, QLabel] = {}
        self._preview_labels: dict[int, QLabel] = {}
        self._build_ui()

    # ---------------- UI 骨架 ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        body = QHBoxLayout()
        root.addLayout(body, 1)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(190)
        self._tree.currentItemChanged.connect(self._on_tree_change)
        body.addWidget(self._tree)

        self._stack = QStackedWidget()
        body.addWidget(self._stack, 1)

        buttons = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)

        self._reload_tree()

    def _reload_tree(self):
        current = self._tree.currentItem()
        cur_key = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        self._tree.clear()
        while self._stack.count():
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()
        self._tables.clear()
        self._mode_combos.clear()
        self._status_labels.clear()
        self._preview_labels.clear()

        g = QTreeWidgetItem(["全局设置"])
        g.setData(0, Qt.ItemDataRole.UserRole, ("page", "global"))
        self._tree.addTopLevelItem(g)
        self._stack.addWidget(self._make_global_page())

        y = QTreeWidgetItem(["YAML 源码"])
        y.setData(0, Qt.ItemDataRole.UserRole, ("page", "yaml"))
        self._tree.addTopLevelItem(y)
        self._yaml_view = QPlainTextEdit()
        self._yaml_view.setReadOnly(True)
        self._stack.addWidget(self._yaml_view)

        for idx, inst in enumerate(self._data["instances"]):
            label = inst.get("name") or inst["id"]
            item = QTreeWidgetItem([f"实例  {label}"])
            item.setData(0, Qt.ItemDataRole.UserRole, ("page", idx))
            self._tree.addTopLevelItem(item)
            self._stack.addWidget(self._make_instance_page(idx))

        # 重建后恢复先前的选中项（不存在则回落到全局设置）
        target = g
        if cur_key is not None:
            for i in range(self._tree.topLevelItemCount()):
                it = self._tree.topLevelItem(i)
                if it.data(0, Qt.ItemDataRole.UserRole) == cur_key:
                    target = it
                    break
        self._tree.setCurrentItem(target)
        self._refresh_yaml_preview()

    def _on_tree_change(self, cur, _prev):
        if cur is None:
            return
        kind, key = cur.data(0, Qt.ItemDataRole.UserRole)
        if kind == "page" and isinstance(key, int):
            self._stack.setCurrentIndex(2 + key)
        elif key == "global":
            self._stack.setCurrentIndex(0)
        else:
            self._refresh_yaml_preview()
            self._stack.setCurrentIndex(1)

    # ---------------- 小部件帮手 ----------------
    def _bind(self, path: tuple, widget: QWidget) -> QWidget:
        self._widgets[path] = widget
        return widget

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _spin(self, path: tuple, value, lo, hi, double=False) -> QWidget:
        w = QDoubleSpinBox() if double else QSpinBox()
        w.setRange(lo, hi)
        original = value
        if double:
            w.setDecimals(2)
            w.setValue(float(value))
            w.valueChanged.connect(
                lambda v, p=path: self._data_set(p, round(v, 2)))
        else:
            w.setValue(int(value))
            w.valueChanged.connect(
                lambda v, p=path: self._data_set(p, int(v)))
        # setValue 越界时会被钳制并触发 valueChanged，从而把越界值静默改写进
        # _data；这里把磁盘上的原值写回，并用 tooltip 提示用户发生了调整。
        if double:
            clamped = round(float(w.value()), 2) != round(float(original), 2)
        else:
            clamped = w.value() != int(original)
        if clamped:
            self._data_set(path, original)
            w.setToolTip(f"原值 {original} 超出范围，已调整为 {w.value()}")
        return self._bind(path, w)

    def _line(self, path: tuple, value) -> QLineEdit:
        w = QLineEdit(str(value))
        w.textChanged.connect(lambda t, p=path: self._data_set(p, t))
        return self._bind(path, w)

    def _data_set(self, path: tuple, value):
        """写回 self._data；路径形如 ("app","adb_path") 或 ("instances",0,"name")。"""
        obj = self._data
        for key in path[:-1]:
            obj = obj[key]
        obj[path[-1]] = value

    # ---------------- 全局页 ----------------
    def _make_global_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        form = QFormLayout()
        app = self._data["app"]

        mumu = self._line(("app", "mumu_manager_path"), app.get("mumu_manager_path", ""))
        mumu_btn = QPushButton("浏览…")
        mumu_btn.clicked.connect(lambda: self._pick_file(mumu, "选择 MuMuManager.exe"))
        mumu_row = QHBoxLayout()
        mumu_row.addWidget(mumu, 1)
        mumu_row.addWidget(mumu_btn)
        form.addRow("MuMuManager 路径", self._wrap(mumu_row))

        adb = self._line(("app", "adb_path"), app.get("adb_path", "adb"))
        adb_btn = QPushButton("浏览…")
        adb_btn.clicked.connect(lambda: self._pick_file(adb, "选择 adb.exe"))
        adb_row = QHBoxLayout()
        adb_row.addWidget(adb, 1)
        adb_row.addWidget(adb_btn)
        form.addRow("adb 路径", self._wrap(adb_row))
        outer.addLayout(form)

        anti = self._data["app"]["anti_detection"]
        group = QGroupBox("防检测参数")
        af = QFormLayout(group)
        af.addRow("点击偏移(px)", self._spin(("app", "anti_detection", "click_offset_px"),
                                             anti["click_offset_px"], 0, 50))
        af.addRow("动作延迟下限(s)", self._spin(("app", "anti_detection", "action_delay_min"),
                                                anti["action_delay_min"], 0.0, 10.0, double=True))
        af.addRow("动作延迟上限(s)", self._spin(("app", "anti_detection", "action_delay_max"),
                                                anti["action_delay_max"], 0.0, 10.0, double=True))
        af.addRow("状态延迟下限(s)", self._spin(("app", "anti_detection", "state_delay_min"),
                                                anti["state_delay_min"], 0.0, 30.0, double=True))
        af.addRow("状态延迟上限(s)", self._spin(("app", "anti_detection", "state_delay_max"),
                                                anti["state_delay_max"], 0.0, 30.0, double=True))
        af.addRow("抖动比例", self._spin(("app", "anti_detection", "jitter_ratio"),
                                         anti["jitter_ratio"], 0.0, 1.0, double=True))
        dbg = QCheckBox("调试模式（关闭随机化）")
        dbg.setChecked(anti["debug_no_jitter"])
        dbg.toggled.connect(lambda v: self._data_set(("app", "anti_detection", "debug_no_jitter"), bool(v)))
        self._bind(("app", "anti_detection", "debug_no_jitter"), dbg)
        af.addRow(dbg)
        outer.addWidget(group)
        detect_btn = QPushButton("检测全部实例")
        detect_btn.clicked.connect(self._detect_all_instances)
        outer.addWidget(detect_btn)
        self._detect_output = QPlainTextEdit()
        self._detect_output.setReadOnly(True)
        self._detect_output.setMaximumHeight(120)
        outer.addWidget(self._detect_output)
        outer.addStretch(1)
        return page

    def _pick_file(self, line_edit: QLineEdit, title: str):
        f, _ = QFileDialog.getOpenFileName(self, title, line_edit.text(), "All files (*.*)")
        if f:
            line_edit.setText(f)

    # ---------------- YAML 预览页 ----------------
    def _refresh_yaml_preview(self):
        self._yaml_view.setPlainText(
            yaml.safe_dump(self._data, allow_unicode=True, sort_keys=False))

    # ---------------- 实例页 ----------------
    def _make_instance_page(self, idx: int) -> QWidget:
        inst = self._data["instances"][idx]
        page = QWidget()
        outer = QVBoxLayout(page)
        form = QFormLayout()

        outer.addWidget(QLabel(f"实例 ID：{inst['id']}"))
        name = self._line(("instances", idx, "name"), inst.get("name", ""))
        form.addRow("显示名", name)

        mode = QComboBox()
        mode.addItems(["MuMu 实例号", "手动 adb 地址"])
        self._mode_combos[idx] = mode
        stack = QStackedWidget()
        spin = QSpinBox()
        spin.setRange(0, 64)
        spin.setValue(inst.get("mumu_index") or 0)
        spin.valueChanged.connect(lambda v, i=idx: self._set_mumu_index(i, int(v)))
        self._bind(("instances", idx, "mumu_index"), spin)
        addr = self._line(("instances", idx, "adb_address"), inst.get("adb_address", ""))
        stack.addWidget(spin)
        stack.addWidget(addr)
        is_manual = inst.get("mumu_index") is None
        mode.setCurrentIndex(1 if is_manual else 0)
        stack.setCurrentIndex(1 if is_manual else 0)

        def _on_mode(i, i2=idx):
            inst2 = self._data["instances"][i2]
            if i == 0:
                inst2["mumu_index"] = int(spin.value())
                inst2["adb_address"] = ""
                addr.clear()
            else:
                inst2["mumu_index"] = None
                inst2["adb_address"] = addr.text()
        mode.currentIndexChanged.connect(_on_mode)
        mode.currentIndexChanged.connect(stack.setCurrentIndex)
        form.addRow("接入方式", mode)
        form.addRow("MuMu 实例号", stack)
        outer.addLayout(form)

        outer.addWidget(QLabel("角色阵容（双击行编辑）"))
        table = QTableWidget(0, 5)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setHorizontalHeaderLabels(["名字", "分工", "目标等级", "预设", "兵种 / 填兵目标"])
        self._tables[idx] = table
        for c in inst["characters"]:
            self._append_char_row(table, c)
        table.doubleClicked.connect(
            lambda _mi, i=idx, t=table: self._edit_character(i, t.currentRow()))
        outer.addWidget(table, 1)

        btns = QHBoxLayout()
        add_btn = QPushButton("＋ 添加角色")
        add_btn.clicked.connect(lambda _c, i=idx, t=table: self._edit_character(i, -1))
        del_btn = QPushButton("删除选中角色")
        del_btn.clicked.connect(lambda _c, i=idx, t=table: self._delete_character(i, t.currentRow()))
        add_inst_btn = QPushButton("＋ 添加实例")
        add_inst_btn.clicked.connect(lambda _c: self._add_instance())
        del_inst_btn = QPushButton("删除本实例")
        del_inst_btn.clicked.connect(lambda _c, i=idx: self._delete_instance(i))
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(lambda _c, i=idx: self._test_connection(i))
        btns.addWidget(test_btn)
        for b in (add_btn, del_btn, add_inst_btn, del_inst_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        outer.addLayout(btns)
        self._status_labels[idx] = QLabel("○ 未测试")
        outer.addWidget(self._status_labels[idx])
        self._preview_labels[idx] = QLabel()
        outer.addWidget(self._preview_labels[idx])
        return page

    @staticmethod
    def _append_char_row(table: QTableWidget, c: dict):
        row = table.rowCount()
        table.insertRow(row)
        fills = ", ".join(f"{f['instance']}/{f['name']}" for f in c.get("fill_target_leaders", []))
        troops = "、".join(TROOP_LABELS[t] for t in c["march_troop_types"])
        summary = troops + (f" ｜ 填: {fills}" if fills else "")
        for col, text in enumerate([c["name"], ROLE_LABELS[c["role"]],
                                    str(c["target_level"]), str(c["march_preset"]), summary]):
            table.setItem(row, col, QTableWidgetItem(text))

    def _leader_candidates(self, exclude=None) -> list[dict]:
        out = []
        for i, inst in enumerate(self._data["instances"]):
            for j, c in enumerate(inst["characters"]):
                if c["role"] in ("leader", "either") and (i, j) != exclude:
                    out.append({"instance": inst["id"], "name": c["name"]})
        return out

    def _edit_character(self, idx: int, row: int):
        inst = self._data["instances"][idx]
        existing = inst["characters"][row] if 0 <= row < len(inst["characters"]) else None
        dlg = CharacterEditDialog(self, existing, self._leader_candidates(
            exclude=(idx, row) if existing else None))
        if dlg.exec() and dlg.get_result():
            self._save_character(idx, existing, dlg.get_result())

    def _save_character(self, idx: int, existing: dict | None, result: dict):
        chars = self._data["instances"][idx]["characters"]
        if existing is not None:
            pos = next((i for i, c in enumerate(chars) if c["id"] == existing["id"]), None)
            if pos is None:
                return
            chars[pos] = result
        else:
            chars.append(result)
        # 重命名时同步所有实例中的填兵目标引用，避免悬空引用
        if existing is not None and existing["name"] != result["name"]:
            inst_id = self._data["instances"][idx]["id"]
            for inst in self._data["instances"]:
                for c in inst["characters"]:
                    for f in c.get("fill_target_leaders", []):
                        if f["instance"] == inst_id and f["name"] == existing["name"]:
                            f["name"] = result["name"]
        self._reload_tree()

    def _delete_character(self, idx: int, row: int):
        chars = self._data["instances"][idx]["characters"]
        if 0 <= row < len(chars):
            chars.pop(row)
            self._reload_tree()

    def _add_instance(self):
        used = {i["id"] for i in self._data["instances"]}
        n = 0
        while f"inst{n}" in used:
            n += 1
        self._data["instances"].append({
            "id": f"inst{n}", "name": f"实例{n}", "mumu_index": None,
            "adb_address": "", "window_title_pattern": "", "characters": []})
        self._reload_tree()

    def _delete_instance(self, idx: int):
        inst = self._data["instances"][idx]
        answer = QMessageBox.question(
            self, "删除实例",
            f"确定删除实例 {inst.get('name') or inst['id']} 及其全部角色？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._data["instances"].pop(idx)
        self._reload_tree()

    def _set_mumu_index(self, idx: int, value: int):
        self._data_set(("instances", idx, "mumu_index"), value)

    # ---------------- 连接测试 / 在线检测 ----------------
    def _test_connection(self, idx: int):
        """spec §5：查实例在线 -> adb 截一帧显示缩略图，确认连的是这台。"""
        import cv2
        inst = self._data["instances"][idx]
        try:
            handle = create_handle_source(
                mumu_index=inst.get("mumu_index"),
                mumu_manager_path=self._data["app"].get("mumu_manager_path", ""),
                adb_address=inst.get("adb_address", ""),
                adb_path=self._data["app"].get("adb_path", "adb"))
            img = handle.capture()
        except Exception as e:  # 连不上/截图失败都要给非程序员能读懂的提示
            self._status_labels[idx].setText(f"○ 连接失败：{e}")
            self._preview_labels[idx].clear()
            return
        self._status_labels[idx].setText(
            f"● 已连接，截图 {img.shape[1]}x{img.shape[0]}")
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self._preview_labels[idx].setPixmap(QPixmap.fromImage(qimg).scaled(
            320, 180, Qt.AspectRatioMode.KeepAspectRatio))

    def _detect_all_instances(self):
        """spec §5：全局页「检测全部实例」，列出各实例在线状态。"""
        from rok_assistant.infra.mumu import MumuLocator
        lines = []
        for inst in self._data["instances"]:
            if inst.get("mumu_index") is not None:
                loc = MumuLocator(self._data["app"].get("mumu_manager_path", ""),
                                  self._data["app"].get("adb_path", "adb"))
                state = "● 在线" if loc.is_running(inst["mumu_index"]) else "○ 离线/未启动"
                lines.append(f"{inst['id']} (mumu{inst['mumu_index']}): {state}")
            else:
                lines.append(f"{inst['id']}: 手动 adb 模式，用实例页「测试连接」检查")
        self._detect_output.setPlainText("\n".join(lines) or "尚无实例")

    # ---------------- 保存 ----------------
    def _on_save(self):
        if self.save():
            self.accept()

    def save(self) -> bool:
        try:
            RootConfig.model_validate(self._data)
        except ValidationError as e:
            self._show_errors(e)
            return False
        try:
            self._path.write_text(
                yaml.safe_dump(self._data, allow_unicode=True, sort_keys=False),
                encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, "保存失败", f"无法写入配置文件：{e}")
            return False
        self._refresh_yaml_preview()
        QMessageBox.information(self, "配置", "保存成功")
        return True

    def _show_errors(self, e: ValidationError):
        for path in self._widgets:
            self._widgets[path].setStyleSheet("")
        lines = ["以下字段校验未通过（详细原因为英文技术信息，可截图反馈给开发者）："]
        for err in e.errors():
            loc = tuple(err["loc"])
            lines.append(" / ".join(str(x) for x in loc) + f": {err['msg']}")
            w = self._widgets.get(loc)
            if w is not None:
                w.setStyleSheet(ERR_STYLE)
        QMessageBox.critical(self, "校验失败", "\n".join(lines) or str(e))


class CharacterEditDialog(QDialog):
    """单个角色的编辑表单（spec 2026-09-09 §5 角色编辑表单）。"""

    def __init__(self, parent, character: dict | None, candidates: list[dict]):
        super().__init__(parent)
        self.setWindowTitle("角色编辑")
        self.resize(460, 520)
        self._character = dict(character) if character else None
        self._candidates = candidates
        form = QFormLayout(self)

        self.name_edit = QLineEdit((character or {}).get("name", ""))
        form.addRow("角色名（须与游戏内一致）", self.name_edit)

        self.role_combo = QComboBox()
        for r in ("leader", "member", "either"):
            self.role_combo.addItem(ROLE_LABELS[r])
        if (character or {}).get("role"):
            self.role_combo.setCurrentText(ROLE_LABELS[character["role"]])
        form.addRow("分工", self.role_combo)

        self.level_spin = QSpinBox()
        self.level_spin.setRange(1, 10)
        self.level_spin.setValue((character or {}).get("target_level", 7))
        form.addRow("目标城寨等级", self.level_spin)

        self.preset_spin = QSpinBox()
        self.preset_spin.setRange(1, 5)
        self.preset_spin.setValue((character or {}).get("march_preset", 1))
        form.addRow("行军预设", self.preset_spin)

        troop_row = QHBoxLayout()
        self.troop_checks = {}
        for key, label in TROOP_LABELS.items():
            cb = QCheckBox(label)
            cb.setChecked(key in (character or {}).get("march_troop_types", ["infantry"]))
            self.troop_checks[key] = cb
            troop_row.addWidget(cb)
        form.addRow("兵种", ConfigDialog._wrap(troop_row))

        form.addRow(QLabel("填兵目标（成员 / 车头或成员 必选，可多选）："))
        lists = QHBoxLayout()
        self.cand_list = QListWidget()
        self.sel_list = QListWidget()
        selected = {(f["instance"], f["name"])
                    for f in (character or {}).get("fill_target_leaders", [])}
        for c in candidates:
            item = QListWidgetItem(f"{c['instance']} / {c['name']}")
            item.setData(Qt.ItemDataRole.UserRole, (c["instance"], c["name"]))
            if (c["instance"], c["name"]) in selected:
                self.sel_list.addItem(item)
            else:
                self.cand_list.addItem(item)
        lists.addWidget(self.cand_list)
        moves = QVBoxLayout()
        add_btn = QPushButton("→")
        add_btn.clicked.connect(self._move_to_selected)
        rm_btn = QPushButton("←")
        rm_btn.clicked.connect(self._move_to_candidates)
        moves.addStretch(1)
        moves.addWidget(add_btn)
        moves.addWidget(rm_btn)
        moves.addStretch(1)
        lists.addLayout(moves)
        lists.addWidget(self.sel_list)
        form.addRow(ConfigDialog._wrap(lists))

        ok = QPushButton("确定")
        ok.clicked.connect(self._on_ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        form.addRow(ConfigDialog._wrap(btns))

        self.role_combo.currentTextChanged.connect(
            lambda _t: self.sel_list.setEnabled(
                self.role_combo.currentText() != ROLE_LABELS["leader"]))
        self.sel_list.setEnabled(self.role_combo.currentText() != ROLE_LABELS["leader"])

    def _move_to_selected(self):
        for item in self.cand_list.selectedItems():
            self.cand_list.takeItem(self.cand_list.row(item))
            self.sel_list.addItem(item)

    def _move_to_candidates(self):
        for item in self.sel_list.selectedItems():
            self.sel_list.takeItem(self.sel_list.row(item))
            self.cand_list.addItem(item)

    def _selected_fills(self) -> list[dict]:
        out = []
        for i in range(self.sel_list.count()):
            inst, name = self.sel_list.item(i).data(Qt.ItemDataRole.UserRole)
            out.append({"instance": inst, "name": name})
        return out

    def validate(self) -> str | None:
        """返回错误说明；None 表示可保存。"""
        if not self.name_edit.text().strip():
            return "角色名不能为空"
        troops = [k for k, cb in self.troop_checks.items() if cb.isChecked()]
        if not troops:
            return "至少选择一个兵种"
        role = LABEL_ROLES[self.role_combo.currentText()]
        if role in ("member", "either") and not self._selected_fills():
            return f"分工为 {ROLE_LABELS[role]} 时必须选择填兵目标"
        return None

    def _on_ok(self):
        err = self.validate()
        if err:
            QMessageBox.warning(self, "角色编辑", err)
            return
        self.accept()

    def get_result(self) -> dict:
        role = LABEL_ROLES[self.role_combo.currentText()]
        return {
            "id": (self._character or {}).get("id") or f"char-{uuid.uuid4().hex[:8]}",
            "name": self.name_edit.text().strip(),
            "role": role,
            "target_level": self.level_spin.value(),
            "march_preset": self.preset_spin.value(),
            "march_troop_types": [k for k, cb in self.troop_checks.items() if cb.isChecked()],
            "fill_target_leaders": [] if role == "leader" else self._selected_fills(),
        }
