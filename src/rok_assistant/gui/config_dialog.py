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
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from pydantic import ValidationError

from rok_assistant.core.handle_source import create_handle_source
from rok_assistant.infra.config import (MAX_MARCH_PRESETS, MAX_TARGET_LEVELS,
                                        RootConfig, load_config)
from rok_assistant.infra.mumu import (
    MumuLocatorError, MumuNotRunningError, list_instances,
)
from rok_assistant.gui.labels import (
    LABEL_ROLES, ROLE_LABELS, TROOP_LABELS, humanize_loc,
)

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
        self._instance_lists: dict[int, QListWidget] = {}
        # 记下「这个显示名是我们自动填的」，按实例 id（不是下标——增删会移位）。
        # 用户点几行看看再定下来是常态，只有认得出哪个名字是我们写的，
        # 才能在换选时改掉它，同时绝不覆盖用户自己输入的名字。
        self._autofilled_names: dict[str, str] = {}
        # 扫描结果按对话框缓存（实机 info -v all 约 255ms，不该每次切页都扫）。
        # None = 还没扫过；[] = 扫过但一个模拟器都没有。
        self._scanned: list[dict] | None = None
        self._scan_error: str | None = None
        self._build_ui()
        # 打开就扫一次：用户一进来就该看见自己的「如愿」，而不是先猜该点哪个按钮。
        # 用 singleShot 排到事件循环下一拍，让窗口先画出来——扫描是同步调用
        # 外部程序（实机 255ms，超时上限 6s），在构造函数里等会让对话框迟迟
        # 不出现，用户会以为程序没反应。
        QTimer.singleShot(0, self._rescan)

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
        self._instance_lists.clear()
        # 删掉已不存在的实例的记录，别让它在增删几次后越积越多
        alive = {i["id"] for i in self._data["instances"]}
        self._autofilled_names = {k: v for k, v in self._autofilled_names.items()
                                  if k in alive}

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
            item = QTreeWidgetItem([f"模拟器  {label}"])
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

        # 首启探测没命中时的手动重试（装了 MuMu 但装在非常规目录、
        # 或者先装了模拟器后解压绿色包）。探测逻辑与首启同一份实现。
        self._mumu_line, self._adb_line = mumu, adb
        autodetect_btn = QPushButton("自动检测 MuMu/adb 路径")
        autodetect_btn.clicked.connect(self._autodetect_mumu_paths)
        form.addRow("", autodetect_btn)
        outer.addLayout(form)

        # 运行参数：max_rounds / max_consecutive_failures 早就在配置模型里
        # （infra/config.py），但界面上一直没暴露，只能手改 yaml。
        run = QGroupBox("运行")
        rf = QFormLayout(run)
        rf.addRow("最多轮数", self._spin(("app", "max_rounds"),
                                        app["max_rounds"], 1, 9999))
        rf.addRow("连续失败上限", self._spin(("app", "max_consecutive_failures"),
                                          app["max_consecutive_failures"], 1, 99))
        outer.addWidget(run)

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
        detect_btn = QPushButton("检测全部模拟器")
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

    # ---------------- 模拟器页 ----------------
    def _make_instance_page(self, idx: int) -> QWidget:
        inst = self._data["instances"][idx]
        page = QWidget()
        outer = QVBoxLayout(page)
        form = QFormLayout()

        outer.addWidget(QLabel(f"模拟器 ID：{inst['id']}"))
        name = self._line(("instances", idx, "name"), inst.get("name", ""))
        form.addRow("显示名", name)

        mode = QComboBox()
        mode.addItems(["按模拟器选择", "手动填 adb 地址"])
        self._mode_combos[idx] = mode
        stack = QStackedWidget()

        # --- 方式一：从扫描结果里按 MuMu 里的名字选 ---
        # 为什么不再让人填编号：MuMu 自己的界面只显示名字（「如愿」「如愿-2」），
        # 从不显示 0/1/2，让人填「实例号」等于让人猜（2026-10-05 用户反馈）。
        picker = QWidget()
        pv = QVBoxLayout(picker)
        pv.setContentsMargins(0, 0, 0, 0)
        lst = QListWidget()
        lst.setMaximumHeight(110)
        lst.itemSelectionChanged.connect(lambda i=idx: self._on_instance_pick(i))
        self._instance_lists[idx] = lst
        self._bind(("instances", idx, "mumu_index"), lst)
        pv.addWidget(lst)
        scan_row = QHBoxLayout()
        scan_btn = QPushButton("扫描模拟器")
        scan_btn.clicked.connect(self._rescan)
        scan_hint = QLabel("（先启动模拟器，再点扫描）")
        scan_row.addWidget(scan_btn)
        scan_row.addWidget(scan_hint)
        scan_row.addStretch(1)
        pv.addLayout(scan_row)
        stack.addWidget(picker)

        # --- 方式二：直接填 adb 地址（非 MuMu 的模拟器走这里） ---
        addr = self._line(("instances", idx, "adb_address"), inst.get("adb_address", ""))
        stack.addWidget(addr)

        is_manual = inst.get("mumu_index") is None
        mode.setCurrentIndex(1 if is_manual else 0)
        stack.setCurrentIndex(1 if is_manual else 0)

        def _on_mode(i, i2=idx):
            inst2 = self._data["instances"][i2]
            if i == 0:
                inst2["adb_address"] = ""
                addr.clear()
                self._on_instance_pick(i2)   # 列表没选中就保持 mumu_index=None
            else:
                inst2["mumu_index"] = None
                inst2["adb_address"] = addr.text()
        mode.currentIndexChanged.connect(_on_mode)
        mode.currentIndexChanged.connect(stack.setCurrentIndex)
        form.addRow("接入方式", mode)
        form.addRow("选择模拟器", stack)
        outer.addLayout(form)
        self._fill_instance_list(idx)

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
        add_inst_btn = QPushButton("＋ 添加模拟器")
        add_inst_btn.clicked.connect(lambda _c: self._add_instance())
        del_inst_btn = QPushButton("删除本模拟器")
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
        # 新字段优先，没有就用旧字段合成一条（与 config 层的迁移同口径）。
        # 全部用 .get()：GUI 保存后写的是 march_presets，此时旧键不存在，
        # 直接下标会 KeyError
        presets = c.get("march_presets") or []
        if not presets and c.get("march_preset"):
            presets = [{"preset": c["march_preset"],
                        "troops": c.get("march_troop_types", [])}]
        preset_text = "→".join(
            f"{p['preset']}（{'/'.join(TROOP_LABELS[t] for t in p['troops'])}）"
            for p in presets) or "—"
        summary = f"填: {fills}" if fills else ""
        levels = "→".join(str(v) for v in c["target_levels"])
        for col, text in enumerate([c["name"], ROLE_LABELS[c["role"]],
                                    levels, preset_text, summary]):
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
        # 与首启模板（config.example.yaml）用同一套前缀，免得用户在界面上
        # 看到模板里叫 mumu0、自己新加的却叫 inst1，以为是什么不同的东西。
        while f"mumu{n}" in used:
            n += 1
        self._data["instances"].append({
            "id": f"mumu{n}", "name": f"模拟器{n}", "mumu_index": None,
            "adb_address": "", "window_title_pattern": "", "characters": []})
        self._reload_tree()

    def _delete_instance(self, idx: int):
        inst = self._data["instances"][idx]
        answer = QMessageBox.question(
            self, "删除模拟器",
            f"确定删除模拟器 {inst.get('name') or inst['id']} 及其全部角色？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._data["instances"].pop(idx)
        self._reload_tree()

    # ---- 扫描模拟器 / 按名字选中 ----

    def _rescan(self):
        """跑一次 MuMuManager 列出所有模拟器，填进各模拟器页的列表。

        打开对话框时自动调一次（实机 255ms），结果缓存在 self._scanned，
        所有模拟器页共用——不该每切一页就重扫一遍。
        """
        manager = self._data["app"].get("mumu_manager_path", "")
        self._scan_error = None
        if not manager:
            self._scanned = None
            self._scan_error = "还没填 MuMuManager 路径，请先到「全局设置」自动检测或手动指定"
        else:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._scanned = list_instances(manager)
            except MumuLocatorError as e:
                self._scanned = None
                self._scan_error = str(e)
            finally:
                QApplication.restoreOverrideCursor()
        for idx in list(self._instance_lists):
            self._fill_instance_list(idx)

    def _fill_instance_list(self, idx: int):
        """把缓存里的扫描结果渲染成列表行；失败时显示一行提示让人重试。"""
        lst = self._instance_lists.get(idx)
        if lst is None:
            return
        lst.blockSignals(True)     # 重建期间别触发 itemSelectionChanged
        try:
            lst.clear()
            if self._scanned is None:
                hint = self._scan_error or "还没扫描，点「扫描模拟器」试试"
                item = QListWidgetItem(f"（{hint}）")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                lst.addItem(item)
                return
            if not self._scanned:
                item = QListWidgetItem("（MuMu 里还没有任何模拟器）")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                lst.addItem(item)
                return
            wanted = self._data["instances"][idx].get("mumu_index")
            for e in self._scanned:
                mark = "●" if e["running"] else "○"
                state = "运行中" if e["running"] else "未启动"
                item = QListWidgetItem(f"{mark} {e['name']} · {state}")
                item.setData(Qt.ItemDataRole.UserRole, e["index"])
                if not e["running"]:
                    # 置灰但仍可选中：用户可能想先配好、等会儿再启动
                    item.setForeground(Qt.GlobalColor.gray)
                lst.addItem(item)
                if wanted == e["index"]:
                    lst.setCurrentItem(item)
        finally:
            lst.blockSignals(False)

    def _on_instance_pick(self, idx: int):
        """列表选中某台模拟器 → 记下它的编号（按名字选，不再手填数字）。"""
        lst = self._instance_lists.get(idx)
        if lst is None:
            return
        item = lst.currentItem()
        if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        self._data_set(("instances", idx, "mumu_index"),
                       int(item.data(Qt.ItemDataRole.UserRole)))
        # 显示名留空时顺手填上模拟器名字，省得用户再想一个。
        # 只在「空着」或「还是我们上次填的那个」时才动它：用户点几行比较一下
        # 是常态，若不跟着换，最后会留下「选的是如愿、名字却是 15634025219」；
        # 而用户自己敲的名字则绝不覆盖。
        inst = self._data["instances"][idx]
        name = (inst.get("name") or "").strip()
        if not name or name == self._autofilled_names.get(inst["id"]):
            picked = self._instance_name(inst["mumu_index"])
            if picked:
                inst["name"] = picked
                self._autofilled_names[inst["id"]] = picked
                w = self._widgets.get(("instances", idx, "name"))
                if isinstance(w, QLineEdit):
                    w.setText(picked)

    def _instance_name(self, index) -> str:
        for e in (self._scanned or []):
            if e["index"] == index:
                return e["name"]
        return ""

    # ---------------- 连接测试 / 在线检测 ----------------
    def _test_connection(self, idx: int):
        """spec §5：查模拟器在线 -> adb 截一帧显示缩略图，确认连的是这台。"""
        import cv2
        inst = self._data["instances"][idx]
        if inst.get("mumu_index") is None and not inst.get("adb_address"):
            self._status_labels[idx].setText(
                "○ 未配置：请先选一台模拟器，或手动填 adb 地址")
            return
        self._status_labels[idx].setText("● 测试中…")
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            handle = create_handle_source(
                mumu_index=inst.get("mumu_index"),
                mumu_manager_path=self._data["app"].get("mumu_manager_path", ""),
                adb_address=inst.get("adb_address", ""),
                adb_path=self._data["app"].get("adb_path", "adb"))
            img = handle.capture()
        except Exception as e:  # 连不上/截图失败都要给非程序员能读懂的提示
            self._status_labels[idx].setText(f"○ {self._explain_connect_error(inst, e)}")
            self._preview_labels[idx].clear()
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._status_labels[idx].setText(
            f"● 已连接，截图 {img.shape[1]}x{img.shape[0]}")
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self._preview_labels[idx].setPixmap(QPixmap.fromImage(qimg).scaled(
            320, 180, Qt.AspectRatioMode.KeepAspectRatio))

    def _explain_connect_error(self, inst: dict, e: Exception) -> str:
        """把底层异常翻成「下一步该做什么」。

        新用户最容易踩的两个坑：模拟器没启动（MuMu 界面里它只是没点开）、
        以及 MuMu 路径没探测到。其余原样带出，并附上 stderr 最后一行。
        """
        index = inst.get("mumu_index")
        if isinstance(e, MumuNotRunningError) or (
                isinstance(e, MumuLocatorError) and "adb 端口" in str(e)):
            name = self._instance_name(index) or f"编号 {index}"
            return f"模拟器「{name}」没有启动，请先在 MuMu 里启动它，再点「测试连接」"
        if isinstance(e, MumuLocatorError) and "无法运行 MuMuManager" in str(e):
            return ("找不到 MuMuManager，请到「全局设置」点「自动检测 MuMu/adb 路径」，"
                    "或手动指定 MuMuManager.exe 和 adb.exe")
        if isinstance(e, MumuLocatorError) and "没有响应" in str(e):
            # 超时不是配置问题，别让人去改路径（2026-10-05 有用户被误导过）
            return ("MuMu 没有响应（模拟器可能正忙或刚启动）。等十几秒再点一次"
                    "「测试连接」；一直如此就重启 MuMu 和本程序")
        msg = f"连接失败：{e}"
        stderr = getattr(e, "stderr", None)
        if stderr:  # CalledProcessError 等会带 stderr，取最后一行帮助定位
            lines = [ln for ln in stderr.decode(errors="replace").splitlines()
                     if ln.strip()]
            if lines:
                msg += f"\n{lines[-1]}"
        return msg

    def _autodetect_mumu_paths(self):
        """扫常见安装位置填 MuMuManager/adb 路径。

        复用 infra.mumu.detect_mumu_paths（与首启生成 config.yaml 时同一份
        实现），探测不到就明确告知，不静默留空。会**覆盖**已有值——这是用户
        主动点的按钮，意图就是重新探一次。
        """
        from rok_assistant.infra.mumu import detect_mumu_paths
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            found = detect_mumu_paths()
        finally:
            QApplication.restoreOverrideCursor()

        filled = []
        for key, widget in (("mumu_manager_path", self._mumu_line),
                            ("adb_path", self._adb_line)):
            value = found.get(key)
            if value:
                widget.setText(value)   # textChanged 负责写回 self._data
                filled.append(f"{key} = {value}")
        if filled:
            QMessageBox.information(self, "自动检测", "已填入：\n" + "\n".join(filled))
        else:
            QMessageBox.warning(
                self, "自动检测",
                "没找到 MuMu 安装位置。请手动指定 MuMu 安装目录下的\n"
                "MuMuManager.exe 和 adb.exe（点「浏览…」选择）。")

    def _detect_all_instances(self):
        """spec §5：全局页「检测全部模拟器」，列出各模拟器在线状态。

        一次 `info -v all` 拿全，不再逐台 `is_running`（N 台省 N 次子进程）。
        输出用模拟器的**名字**，不再暴露 `inst0 (mumu2)` 这种内部 id。
        """
        self._rescan()          # 顺便刷新各页的列表，保证和这里的结论一致
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lines = []
            for inst in self._data["instances"]:
                index = inst.get("mumu_index")
                shown = inst.get("name") or inst["id"]
                if index is None:
                    lines.append(f"{shown}：手动 adb 模式，用模拟器页「测试连接」检查")
                    continue
                info = next((e for e in (self._scanned or []) if e["index"] == index), None)
                if info is None:
                    lines.append(f"{shown}：在 MuMu 里没找到编号 {index} 的模拟器")
                else:
                    state = "● 运行中" if info["running"] else "○ 未启动"
                    lines.append(f"模拟器 {index} · {info['name']}：{state}")
            if self._scan_error:
                lines.append(f"（扫描失败：{self._scan_error}）")
        finally:
            QApplication.restoreOverrideCursor()
        self._detect_output.setPlainText("\n".join(lines) or "尚无模拟器")

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
        lines = ["以下字段校验未通过（个别技术性原因为英文，可截图反馈给开发者）："]
        for err in e.errors():
            loc = tuple(err["loc"])
            # loc 为空 = 跨字段校验，落到整个配置上；不写「整体配置」的话
            # 这行会以冒号开头，看着像程序出了 bug
            lines.append((humanize_loc(loc) or "整体配置") + f": {err['msg']}")
            if not loc:
                continue  # 根级错误无对应控件
            for path in self._widgets:
                # 前缀匹配：model-validator 的错误落在父路径上（如
                # ("instances", 0) 或 ()），其下所有控件都要标红
                if path[:len(loc)] == loc:
                    self._widgets[path].setStyleSheet(ERR_STYLE)
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

        # 目标城寨等级（2026-10-04 用户要求）：1–10 复选框，最多勾 3 个。
        # 勾选**顺序即搜索顺序**（用户明确要求完全自由，例如 6→4→5），
        # 而复选框本身表达不了顺序，故下面挂一个标签实时显示结果；用户
        # 想调整顺序就取消重勾（新勾的排到最后）。
        self._level_order: list[int] = list((character or {}).get("target_levels", [7]))
        self.level_checks: dict[int, QCheckBox] = {}
        level_grid = QGridLayout()
        level_grid.setContentsMargins(0, 0, 0, 0)
        for i, lv in enumerate(range(1, 11)):
            cb = QCheckBox(str(lv))
            cb.setChecked(lv in self._level_order)
            self.level_checks[lv] = cb
            level_grid.addWidget(cb, i // 5, i % 5)
        # 信号在 setChecked 之后再接：否则初始化会把 _level_order 重排成
        # 勾选回调的顺序（配置里存的顺序就丢了）
        for lv, cb in self.level_checks.items():
            cb.toggled.connect(lambda on, v=lv: self._on_level_toggle(v, on))
        self.level_order_label = QLabel()
        level_box = QVBoxLayout()
        level_box.setContentsMargins(0, 0, 0, 0)
        level_box.addLayout(level_grid)
        level_box.addWidget(self.level_order_label)
        form.addRow(f"目标城寨等级（≤{MAX_TARGET_LEVELS}）",
                    ConfigDialog._wrap(level_box))
        self._refresh_level_order()

        # 行军预设（2026-10-09）：3 行固定编辑器，行序即优先级；第 2/3 行
        # 留空 = 不启用。每行 = [预设 ▾][□步兵 □骑兵 □弓兵] —— 兵种用复选
        # 而不是单选下拉：一个预设允许同时点多个兵种（_form_troop 逐个点
        # troop_*），单选会丢掉这个能力。
        self.preset_rows: list[tuple[QComboBox, dict]] = []
        preset_box = QVBoxLayout()
        preset_box.setContentsMargins(0, 0, 0, 0)
        for _ in range(MAX_MARCH_PRESETS):
            row = QHBoxLayout()
            pcombo = QComboBox()
            pcombo.addItem("（不启用）", None)
            for n in range(1, 6):
                pcombo.addItem(f"预设 {n}", n)
            row.addWidget(pcombo)
            checks = {}
            for key, label in TROOP_LABELS.items():
                cb = QCheckBox(label)
                checks[key] = cb
                row.addWidget(cb)
            preset_box.addLayout(row)
            self.preset_rows.append((pcombo, checks))
        form.addRow(f"行军预设（按顺序，最多 {MAX_MARCH_PRESETS} 行）",
                    ConfigDialog._wrap(preset_box))

        # 载入：新字段优先，没有就用旧字段合成一行（与 config 层的迁移同口径）
        presets = (character or {}).get("march_presets") or []
        if not presets and (character or {}).get("march_preset"):
            presets = [{"preset": (character or {})["march_preset"],
                        "troops": (character or {}).get("march_troop_types", [])}]
        for i, (pcombo, checks) in enumerate(self.preset_rows):
            if i >= len(presets):
                continue
            p = presets[i]
            idx = pcombo.findData(p.get("preset"))
            if idx >= 0:
                pcombo.setCurrentIndex(idx)
            for t in p.get("troops", []):
                if t in checks:
                    checks[t].setChecked(True)

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

    def _on_level_toggle(self, level: int, checked: bool) -> None:
        if checked:
            if level in self._level_order:
                return
            if len(self._level_order) >= MAX_TARGET_LEVELS:
                # 超上限：撤销这次勾选。比弹窗打断轻，且状态立刻回到合法
                self.level_checks[level].setChecked(False)
                return
            self._level_order.append(level)
        elif level in self._level_order:
            self._level_order.remove(level)
        self._refresh_level_order()

    def _refresh_level_order(self) -> None:
        """把当前顺序写到标签上，并锁住「已选满 3 个时未选中的框」。

        顺序是隐性状态（只存在于点击先后里），不显式显示的话用户无法
        确认 6→4→5 有没有生效。
        """
        if self._level_order:
            self.level_order_label.setText(
                "搜索顺序：" + " → ".join(str(v) for v in self._level_order))
        else:
            self.level_order_label.setText("搜索顺序：（至少勾一个等级）")
        full = len(self._level_order) >= MAX_TARGET_LEVELS
        for lv, cb in self.level_checks.items():
            cb.setEnabled(cb.isChecked() or not full)

    def _move_to_selected(self):
        for item in self.cand_list.selectedItems():
            self.cand_list.takeItem(self.cand_list.row(item))
            self.sel_list.addItem(item)

    def _move_to_candidates(self):
        for item in self.sel_list.selectedItems():
            self.sel_list.takeItem(self.sel_list.row(item))
            self.cand_list.addItem(item)

    def _read_march_presets(self) -> list[dict]:
        """读 3 行编辑器 → [{"preset": n, "troops": [...]}, ...]。

        预设选「（不启用）」的行跳过；行序就是返回顺序，也就是优先级。
        """
        out = []
        for pcombo, checks in self.preset_rows:
            preset = pcombo.currentData()
            if preset is None:
                continue
            out.append({"preset": preset,
                        "troops": [k for k, cb in checks.items() if cb.isChecked()]})
        return out

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
        if not self._level_order:
            return f"至少勾选一个目标城寨等级（最多 {MAX_TARGET_LEVELS} 个）"
        presets = self._read_march_presets()
        if not presets:
            return "至少配置一行行军预设"
        for p in presets:
            if not p["troops"]:
                return f"预设 {p['preset']} 没有选兵种"
        slots = [p["preset"] for p in presets]
        if len(set(slots)) != len(slots):
            return f"预设号重复：{slots}"
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
            "target_levels": list(self._level_order),
            "march_presets": self._read_march_presets(),
            "fill_target_leaders": [] if role == "leader" else self._selected_fills(),
        }
