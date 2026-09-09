"""可视化配置对话框：左树右表单（spec 2026-09-09 §5）。

数据模式：对话框持有 model_dump 出来的纯 dict（self._data），各表单写回
dict，保存时 RootConfig.model_validate 整体校验，避免编辑过程中产生
半合法的 pydantic 对象。self._widgets 记录 (路径元组)->控件，用于校验
错误时定位标红。
"""
from __future__ import annotations

from pathlib import Path

import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)
from pydantic import ValidationError

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
        self._tree.clear()
        while self._stack.count():
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()

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

        self._tree.setCurrentItem(g)
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
        if double:
            w.setDecimals(2)
            w.setValue(float(value))
            w.valueChanged.connect(
                lambda v, p=path: self._data_set(p, round(v, 2)))
        else:
            w.setValue(int(value))
            w.valueChanged.connect(
                lambda v, p=path: self._data_set(p, int(v)))
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

    # ---------------- 实例页占位（Task 6 实现） ----------------
    def _make_instance_page(self, idx: int) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel(f"实例 {self._data['instances'][idx].get('name') or self._data['instances'][idx]['id']}"
                           "（实例/角色编辑在下一个任务实现）"))
        v.addStretch(1)
        return page

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
        self._path.write_text(
            yaml.safe_dump(self._data, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        self._refresh_yaml_preview()
        QMessageBox.information(self, "配置", "保存成功")
        return True

    def _show_errors(self, e: ValidationError):
        for path in self._widgets:
            self._widgets[path].setStyleSheet("")
        lines = []
        for err in e.errors():
            loc = tuple(err["loc"])
            lines.append(" / ".join(str(x) for x in loc) + f": {err['msg']}")
            w = self._widgets.get(loc)
            if w is not None:
                w.setStyleSheet(ERR_STYLE)
        QMessageBox.critical(self, "校验失败", "\n".join(lines) or str(e))
