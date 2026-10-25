"""可视化配置对话框：左树右表单（spec 2026-09-09 §5）。

数据模式：对话框持有 model_dump 出来的纯 dict（self._data），各表单写回
dict，保存时 RootConfig.model_validate 整体校验，避免编辑过程中产生
半合法的 pydantic 对象。self._widgets 记录 (路径元组)->控件，用于校验
错误时定位标红。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import uuid

import yaml
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from pydantic import ValidationError

from rok_assistant.core.handle_source import create_handle_source
from rok_assistant.core.quiz.session import (
    SESSION_LABELS, SESSION_QUESTION_LIMITS, current_session,
)
from rok_assistant.infra.config import (MAX_MARCH_PRESETS, MAX_TARGET_LEVELS,
                                        MAX_TARGET_LEVEL, MIN_TARGET_LEVEL,
                                        RANGE_BOUNDARY, level_range,
                                        AppMode, IMPLEMENTED_MODES, MODE_LABELS,
                                        RAIDER_LABEL, RAIDER_TARGET, RootConfig,
                                        load_config, target_short)
from rok_assistant.infra.mumu import (
    MumuLocatorError, MumuNotRunningError, list_instances,
)
from rok_assistant.gui import theme
from rok_assistant.gui.labels import (
    LABEL_ROLES, ROLE_LABELS, TROOP_LABELS, humanize_loc,
)

# 校验失败标红：用令牌里的错误色，不用裸 `red`（design-tokens §4.2 状态色只承载语义）
ERR_STYLE = f"border: 1px solid {theme.ERROR}; border-radius:{theme.RADIUS_MD}px;"


class ConfigDialog(QDialog):
    def __init__(self, config_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("rok-assistant 配置")
        self.resize(1040, 720)
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
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        self._tree = QTreeWidget()
        self._tree.setObjectName("configTree")
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(200)
        self._tree.setFrameShape(QFrame.Shape.NoFrame)   # 描边交给 QSS 画右侧分割线
        self._tree.currentItemChanged.connect(self._on_tree_change)
        body.addWidget(self._tree)

        self._stack = QStackedWidget()
        body.addWidget(self._stack, 1)

        root.addWidget(self._footer())
        self._reload_tree()

    def _footer(self) -> QWidget:
        """底部操作栏：1px 分割线 + 右对齐的「取消」（次）/「保存」（主）。"""
        footer = QWidget()
        outer = QVBoxLayout(footer)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        line = QFrame()
        line.setObjectName("hSeparator")
        line.setFrameShape(QFrame.Shape.NoFrame)
        line.setFixedHeight(1)
        outer.addWidget(line)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(theme.SP_XL, theme.SP_MD, theme.SP_XL, theme.SP_MD)
        buttons.setSpacing(theme.SP_SM)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        theme.make_primary(save_btn)          # 本屏唯一主操作
        save_btn.clicked.connect(self._on_save)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        outer.addLayout(buttons)
        return footer

    @staticmethod
    def _scroll(widget: QWidget) -> QScrollArea:
        """把页面内容套进滚动区。

        重构前各页直接进 QStackedWidget，窗口一矮（或高 DPI 缩放）底部控件就被
        裁掉且够不着——全局页尤其明显。
        """
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(widget)
        return area

    @staticmethod
    def _padded(widget: QWidget, margin: int = theme.SP_XL) -> QWidget:
        """给裸控件套一层统一留白（YAML 预览页用）。"""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(margin, margin, margin, margin)
        lay.addWidget(widget)
        return box

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
        alive = {f"zhaiduo:{i['id']}" for i in self._data["zhaiduo"]["instances"]}
        alive |= {f"quiz:{i['id']}" for i in self._data["quiz"]["instances"]}
        self._autofilled_names = {k: v for k, v in self._autofilled_names.items()
                                  if k in alive}

        # 0=公共 1=寨多多 2=宝石 3=答题 4=YAML；实例页从 5 起
        # （先全部寨多多实例、再全部答题实例——两种实例页都在固定页之后）。
        #
        # ⚠️ 五个固定页必须先全部 addWidget 完，实例页才能开始加。
        # 否则实例页会插进固定页中间，把 gem/quiz/yaml 整体下移 N 位，
        # 而 _on_tree_change 的映射是按固定索引写的——结果是点一个进另一个，
        # 且不报错（静默串页）。树子项的 addChild 与 stack 顺序无关，可留在原处。
        self._stack.addWidget(self._scroll(self._make_global_page()))
        g = QTreeWidgetItem(["公共配置"])
        g.setData(0, Qt.ItemDataRole.UserRole, ("page", 0))
        self._tree.addTopLevelItem(g)

        self._stack.addWidget(self._scroll(self._make_zhaiduo_page()))
        z = QTreeWidgetItem(["寨多多模式"])
        z.setData(0, Qt.ItemDataRole.UserRole, ("page", 1))
        self._tree.addTopLevelItem(z)

        # 宝石仍是占位页（配置项在演进，见 PROGRESS 欠账 ②）；答题 2026-10-24
        # 起给真表单——IMPLEMENTED_MODES 里两个模式都能跑，页面不能只说指路。
        self._stack.addWidget(self._scroll(self._make_locked_page(AppMode.GEM)))
        it = QTreeWidgetItem([MODE_LABELS[AppMode.GEM]])
        it.setData(0, Qt.ItemDataRole.UserRole, ("page", 2))
        self._tree.addTopLevelItem(it)

        self._stack.addWidget(self._scroll(self._make_quiz_page()))
        q = QTreeWidgetItem([MODE_LABELS[AppMode.QUIZ]])
        q.setData(0, Qt.ItemDataRole.UserRole, ("page", 3))
        self._tree.addTopLevelItem(q)

        y = QTreeWidgetItem(["YAML 源码（高级）"])
        y.setData(0, Qt.ItemDataRole.UserRole, ("page", 4))
        self._tree.addTopLevelItem(y)
        self._yaml_view = QPlainTextEdit()
        self._yaml_view.setObjectName("yamlView")
        self._yaml_view.setReadOnly(True)
        self._stack.addWidget(self._padded(self._yaml_view))

        # 五个固定页（stack 0..4）加完，实例页才从 5 起。
        # 树子项在这一轮单独建（与 stack 顺序无关，别混进上面）。
        for idx, inst in enumerate(self._data["zhaiduo"]["instances"]):
            label = inst.get("name") or inst["id"]
            item = QTreeWidgetItem([f"模拟器  {label}"])
            item.setData(0, Qt.ItemDataRole.UserRole, ("instance", idx))
            z.addChild(item)
            self._stack.addWidget(self._scroll(self._make_instance_page(idx)))

        # 答题实例页跟在寨多多实例页后面：stack 下标 = 5 + 寨多多实例数 + idx。
        # 答题「一台模拟器一个号」，页里没有角色表格，只有那一个角色的名字。
        for idx, inst in enumerate(self._data["quiz"]["instances"]):
            label = inst.get("name") or inst["id"]
            item = QTreeWidgetItem([f"答题号  {label}"])
            item.setData(0, Qt.ItemDataRole.UserRole, ("quiz_instance", idx))
            q.addChild(item)
            self._stack.addWidget(self._scroll(self._make_quiz_instance_page(idx)))

        self._tree.expandItem(z)          # 实例默认展开，否则用户看不见它们
        # 答题实例同理：只展开寨多多时，新增的「答题号 …」会藏在折叠节点下，
        # 用户点完「＋ 添加答题模拟器」看不到任何变化（2026-10-25 反馈）。
        self._tree.expandItem(q)

        # 重建后恢复先前的选中项（不存在则回落到公共配置）。实例现在是子项，
        # 得递归扫，只扫顶层会漏掉它们。
        def _walk(item):
            yield item
            for k in range(item.childCount()):
                yield from _walk(item.child(k))

        target = g
        if cur_key is not None:
            for i in range(self._tree.topLevelItemCount()):
                for it in _walk(self._tree.topLevelItem(i)):
                    if it.data(0, Qt.ItemDataRole.UserRole) == cur_key:
                        target = it
                        break
                if target is not g:
                    break
        self._tree.setCurrentItem(target)
        self._refresh_yaml_preview()

    # YAML 源码页在 _stack 里的固定索引（见 _reload_tree 的 0..4 契约）
    _YAML_PAGE_INDEX = 4

    def _on_tree_change(self, cur, _prev):
        if cur is None:
            return
        kind, key = cur.data(0, Qt.ItemDataRole.UserRole)
        if kind == "page":
            if key == self._YAML_PAGE_INDEX:
                # 切到 YAML 页必须先刷新：_data 是内存里的当前编辑态，
                # 而 _yaml_view 只在 _reload_tree / save() 时刷新。
                # 不刷新的话，用户改完一个字段直接点 YAML 看到的是改动前的快照。
                self._refresh_yaml_preview()
            self._stack.setCurrentIndex(key)
        elif kind == "instance":
            self._stack.setCurrentIndex(5 + key)
        elif kind == "quiz_instance":
            # 答题实例页排在寨多多实例页之后（_reload_tree 的填充顺序），
            # 所以偏移要加上寨多多的实例数。
            self._stack.setCurrentIndex(
                5 + len(self._data["zhaiduo"]["instances"]) + key)

    def _page_item(self, index: int) -> QTreeWidgetItem | None:
        """按固定页索引（0 公共 / 1 寨多多 / 2 宝石 / 3 答题 / 4 YAML）
        取顶层树项。实例增删只会加子项，不改变顶层顺序。"""
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == ("page", index):
                return item
        return None

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
        # 数值字段保持紧凑：不限制的话 QFormLayout 会把它们拉到整行宽
        # （实测 582px 一根），既难读数也把表单撑出横向滚动条
        w.setMaximumWidth(180)
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
        """写回 self._data；路径形如 ("app","adb_path") 或 ("zhaiduo","instances",0,"name")。"""
        obj = self._data
        for key in path[:-1]:
            obj = obj[key]
        obj[path[-1]] = value

    # ---------------- 全局页 ----------------
    def _make_global_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page:global")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(theme.SP_XL, theme.SP_XL, theme.SP_XL, theme.SP_XL)
        outer.setSpacing(theme.SP_LG)
        form = QFormLayout()
        form.setSpacing(theme.SP_SM)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
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
        rf.setSpacing(theme.SP_SM)
        rf.addRow("最多轮数", self._spin(("app", "max_rounds"),
                                        app["max_rounds"], 1, 9999))
        rf.addRow("连续失败上限", self._spin(("app", "max_consecutive_failures"),
                                          app["max_consecutive_failures"], 1, 99))
        outer.addWidget(run)

        anti = self._data["app"]["anti_detection"]
        group = QGroupBox("防检测参数")
        af = QFormLayout(group)
        af.setSpacing(theme.SP_SM)
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

    def _make_zhaiduo_page(self) -> QWidget:
        """寨多多模式页：实例级操作（检测全部模拟器 + 结果输出）。

        「检测全部模拟器」原来挂在公共配置页，但它是实例级的——跟 app 段
        一个字段都不沾。按 spec §3.1 的两段划分搬到这一页。
        """
        page = QWidget()
        page.setObjectName("page:zhaiduo")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(theme.SP_XL, theme.SP_XL, theme.SP_XL, theme.SP_XL)
        outer.setSpacing(theme.SP_LG)

        hint = QLabel("实例（模拟器）配置见左侧「寨多多模式」下的各模拟器条目。")
        hint.setObjectName("emptyHint")
        outer.addWidget(hint)

        detect_btn = QPushButton("检测全部模拟器")
        detect_btn.clicked.connect(self._detect_all_instances)
        outer.addWidget(detect_btn)
        self._detect_output = QPlainTextEdit()
        self._detect_output.setReadOnly(True)
        self._detect_output.setMaximumHeight(120)
        outer.addWidget(self._detect_output)
        outer.addStretch(1)
        return page

    def _make_locked_page(self, mode: AppMode) -> QWidget:
        """还没有表单的模式：只读页，告诉用户去 config.yaml 哪一段改。

        2026-10-24 起只剩宝石模式走这里（IMPLEMENTED_MODES 里已能跑，页面就
        不能再说「尚未开放」——那会让用户以为整个模式还不可用；但它的配置项
        还在演进，表单维护成本高于直接改 YAML，所以指路而不是给表单）。
        答题模式同日有了真表单（_make_quiz_page）。
        """
        box = QWidget()
        box.setObjectName(f"page:{mode.value}")
        lay = QVBoxLayout(box)
        lay.addStretch(1)
        if mode in IMPLEMENTED_MODES:
            text = (f"{MODE_LABELS[mode]}的实例在 config.yaml 的 "
                    f"{mode.value}: 段里配置。\n"
                    f"本页暂不提供表单，可在「YAML 源码（高级）」里直接改。")
        else:
            text = "该模式尚未开放，暂无配置项"
        msg = QLabel(text)
        msg.setObjectName("emptyHint")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)                  # 两行文案不换行会被裁成一行
        lay.addWidget(msg)
        lay.addStretch(1)
        return box

    # ---------------- 答题模式页 ----------------
    _WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

    def _session_hint(self) -> QLabel:
        """「今日场次 · 固定题量」提示。

        场次按星期几绑定、题量按场次固定（用户 2026-10-24 拍板：
        不按 OCR 识别、题量不进配置），所以这里只做展示，没有输入控件。
        """
        session = current_session()
        cap = SESSION_QUESTION_LIMITS[session]
        cap_text = f"固定 {cap} 题" if cap is not None else "不限题量"
        hint = QLabel(
            f"今日（{self._WEEKDAY_CN[date.today().weekday()]}）场次："
            f"{SESSION_LABELS[session]} · {cap_text}。题量按场次固定，不需配置"
            f"（日常答题不限、初试 10 题、终试 20 题）。")
        hint.setObjectName("sessionHint")
        hint.setWordWrap(True)
        return hint

    def _one_round_hint(self) -> QLabel:
        """「一天一轮」提示。

        轮次/冷却配置已移除（用户 2026-10-25 拍板：答题一天只能答一次，
        无法重复答）——答满本轮即自动收工，没有可配的旋钮。
        """
        hint = QLabel("答题一天一轮：答满本轮即自动收工"
                      "（活动一天只能答一次，无法重复作答）")
        hint.setObjectName("oneRoundHint")
        hint.setWordWrap(True)
        return hint

    def _make_quiz_page(self) -> QWidget:
        """答题模式配置页：作答策略表单（模拟器实例是左侧子项）。

        覆盖 QuizConfig 除 instances 外的全部字段（spec §5）：
        运行（自动点击）、识别与判定（模糊阈值/绿色判定/重认）、
        入口点击落点、大模型兜底。轮次/冷却没有配置（一天只能答一次，
        用户 2026-10-25 拍板移除）。instances 按寨多多的先例做成树子项
        （「答题号 <名字>」），一台一页。
        """
        page = QWidget()
        page.setObjectName("page:quiz")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(theme.SP_XL, theme.SP_XL, theme.SP_XL, theme.SP_XL)
        outer.setSpacing(theme.SP_LG)
        q = self._data["quiz"]

        hint = QLabel("答题模拟器（一台一个号）在左侧「答题模式」下添加；"
                      "本页配置作答策略。")
        hint.setObjectName("emptyHint")
        outer.addWidget(hint)

        # ---- 运行 ----
        run = QGroupBox("运行")
        rf = QFormLayout(run)
        rf.setSpacing(theme.SP_SM)
        rf.addRow(self._session_hint())
        rf.addRow(self._one_round_hint())
        auto = QCheckBox("自动点击选项")
        auto.setChecked(bool(q["auto_click"]))
        auto.setToolTip("取消 = 只认题、只把推荐答案写进日志，不点。"
                        "第一次真机验证建议先这样对一遍答案。")
        auto.toggled.connect(lambda v: self._data_set(("quiz", "auto_click"), bool(v)))
        self._bind(("quiz", "auto_click"), auto)
        rf.addRow(auto)
        outer.addWidget(run)

        # ---- 识别与判定 ----
        rec = QGroupBox("识别与判定")
        rc = QFormLayout(rec)
        rc.setSpacing(theme.SP_SM)
        fuzz = self._spin(("quiz", "fuzzy_threshold"), q["fuzzy_threshold"],
                          0.0, 1.0, double=True)
        fuzz.setToolTip("题库模糊匹配的严格程度：题目差一两个字时仍能认出来。"
                        "调高 = 只认非常像的；调低 = 更容易命中但可能答错。")
        rc.addRow("题库模糊匹配阈值", fuzz)
        delay = self._spin(("quiz", "verify_delay"), q["verify_delay"],
                           0.0, 60.0, double=True)
        delay.setToolTip("点完选项后等多久再截图看绿色高亮。"
                         "日志里总学不到新题时，把它调大一点。")
        rc.addRow("绿色判定等待(秒)", delay)
        green = self._spin(("quiz", "min_green_ratio"), q["min_green_ratio"],
                           0.0, 1.0, double=True)
        green.setToolTip("选项区域里绿色像素占比达到多少算「正确答案」。"
                         "实测正确选项在 0.97 以上。")
        rc.addRow("绿色像素占比阈值", green)
        retries = self._spin(("quiz", "parse_retries"), q["parse_retries"], 1, 10)
        retries.setToolTip("题干或四个选项没认全时，原地重认几次再放弃本轮。")
        rc.addRow("读题重试次数", retries)
        outer.addWidget(rec)

        # ---- 入口点击落点 ----
        taps = QGroupBox("入口点击（从地图进答题界面）")
        tv = QVBoxLayout(taps)
        tv.setSpacing(theme.SP_SM)
        self._entry_table = QTableWidget(0, 2)
        self._entry_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._entry_table.setShowGrid(False)
        self._entry_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._entry_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._entry_table.verticalHeader().setVisible(False)
        self._entry_table.verticalHeader().setDefaultSectionSize(36)
        self._entry_table.setHorizontalHeaderLabels(["X 坐标", "Y 坐标"])
        header = self._entry_table.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(True)
        self._entry_table.setMaximumHeight(4 * 36 + 24)
        tv.addWidget(self._entry_table)
        tap_btns = QHBoxLayout()
        tap_btns.setSpacing(theme.SP_SM)
        add_tap = QPushButton("＋ 添加落点")
        theme.make_dashed(add_tap)
        add_tap.clicked.connect(self._add_entry_tap)
        del_tap = QPushButton("删除选中落点")
        theme.make_danger(del_tap)
        del_tap.clicked.connect(self._delete_entry_tap)
        tap_btns.addWidget(add_tap)
        tap_btns.addWidget(del_tap)
        tap_btns.addStretch(1)
        tv.addLayout(tap_btns)
        tap_hint = QLabel("留空 = 只靠屏幕文字（「进入 / 习题演练 / 活动」）找入口。"
                          "走不通时用 tools/quiz_entry_probe.py 在真机上探一次，"
                          "把打印的坐标填进来。")
        tap_hint.setObjectName("emptyHint")
        tap_hint.setWordWrap(True)
        tv.addWidget(tap_hint)
        outer.addWidget(taps)
        self._refresh_entry_taps_table()

        # ---- 大模型兜底 ----
        llm = QGroupBox("大模型兜底（题库未命中时才用）")
        lf = QFormLayout(llm)
        lf.setSpacing(theme.SP_SM)
        llm_on = QCheckBox("启用大模型")
        llm_on.setChecked(bool(q["llm"]["enabled"]))
        llm_on.setToolTip("关掉 = 纯题库，未命中就随机选，不发任何网络请求。")
        llm_on.toggled.connect(
            lambda v: self._data_set(("quiz", "llm", "enabled"), bool(v)))
        self._bind(("quiz", "llm", "enabled"), llm_on)
        lf.addRow(llm_on)
        lf.addRow("API 地址", self._line(("quiz", "llm", "base_url"),
                                        q["llm"]["base_url"]))
        lf.addRow("模型", self._line(("quiz", "llm", "model"), q["llm"]["model"]))
        key = self._line(("quiz", "llm", "api_key"), q["llm"]["api_key"])
        key.setToolTip("留空 = 不调用大模型。密钥明文写在 config.yaml 里，"
                       "别把那个文件发给别人。")
        lf.addRow("API Key", key)
        lf.addRow("超时(秒)", self._spin(("quiz", "llm", "timeout_s"),
                                        q["llm"]["timeout_s"], 0.1, 120.0,
                                        double=True))
        outer.addWidget(llm)

        # ---- 答题模拟器（实例入口）----
        inst_box = QGroupBox("答题模拟器")
        iv = QVBoxLayout(inst_box)
        iv.setSpacing(theme.SP_SM)
        inst_hint = QLabel("一台模拟器一个答题号，角色名须与游戏内显示名一致。"
                           "点左侧「答题模式」下的条目进入配置；"
                           "还没有答题号时点下面按钮添加。")
        inst_hint.setObjectName("emptyHint")
        inst_hint.setWordWrap(True)
        iv.addWidget(inst_hint)
        add_inst = QPushButton("＋ 添加答题模拟器")
        theme.make_dashed(add_inst)
        add_inst.clicked.connect(self._add_quiz_instance)
        iv.addWidget(add_inst)
        outer.addWidget(inst_box)

        outer.addStretch(1)
        return page

    # ---- 入口点击落点（entry_taps）小编辑器 ----
    def _refresh_entry_taps_table(self):
        """按 self._data["quiz"]["entry_taps"] 重建落点表。

        每格一个 QSpinBox（坐标不该让人手打数字——1920×1080 上打错一位
        就点到了别的 UI 上）。行序即点击顺序，与 config 段语义一致。
        """
        taps = self._data["quiz"]["entry_taps"]
        self._entry_table.setRowCount(len(taps))
        width = int(self._data["app"].get("screen_width", 1920))
        height = int(self._data["app"].get("screen_height", 1080))
        for row, tap in enumerate(taps):
            for col, value, limit in ((0, tap[0], width), (1, tap[1], height)):
                spin = QSpinBox()
                spin.setRange(0, limit)
                spin.setMaximumWidth(140)
                spin.setValue(int(value))
                # valueChanged 在 setValue 时也会触发，写回去的是同一个值，
                # 幂等；行号在建表时捕获，删行重建后自然重新对齐。
                spin.valueChanged.connect(
                    lambda v, r=row, c=col: self._on_entry_tap_changed(r, c, int(v)))
                self._entry_table.setCellWidget(row, col, spin)

    def _on_entry_tap_changed(self, row: int, col: int, value: int):
        taps = self._data["quiz"]["entry_taps"]
        if 0 <= row < len(taps):
            tap = list(taps[row])
            tap[col] = value
            taps[row] = tap

    def _add_entry_tap(self):
        self._data["quiz"]["entry_taps"].append([0, 0])
        self._refresh_entry_taps_table()

    def _delete_entry_tap(self):
        row = self._entry_table.currentRow()
        taps = self._data["quiz"]["entry_taps"]
        if 0 <= row < len(taps):
            taps.pop(row)
            self._refresh_entry_taps_table()

    def _make_quiz_instance_page(self, idx: int) -> QWidget:
        """答题模式的一个模拟器页：接入方式 + 那一个角色的名字。

        与寨多多实例页同构（同一套扫描/挑选/测试连接机器），差异只有：
        没有角色表格（一台恰好一个号），角色名直接摆在表单里。
        """
        inst = self._data["quiz"]["instances"][idx]
        ref = ("quiz", idx)
        page = QWidget()
        page.setObjectName(f"page:quiz_instance:{idx}")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(theme.SP_XL, theme.SP_XL, theme.SP_XL, theme.SP_XL)
        outer.setSpacing(theme.SP_LG)
        form = QFormLayout()
        form.setSpacing(theme.SP_SM)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)

        outer.addWidget(QLabel(f"模拟器 ID：{inst['id']}"))
        name = self._line(("quiz", "instances", idx, "name"), inst.get("name", ""))
        form.addRow("显示名", name)

        mode = QComboBox()
        mode.setMaximumWidth(220)
        mode.addItems(["按模拟器选择", "手动填 adb 地址"])
        self._mode_combos[ref] = mode
        stack = QStackedWidget()

        picker = QWidget()
        pv = QVBoxLayout(picker)
        pv.setContentsMargins(0, 0, 0, 0)
        lst = QListWidget()
        lst.setMaximumHeight(110)
        lst.itemSelectionChanged.connect(lambda r=ref: self._on_instance_pick(r))
        self._instance_lists[ref] = lst
        self._bind(("quiz", "instances", idx, "mumu_index"), lst)
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

        addr = self._line(("quiz", "instances", idx, "adb_address"),
                          inst.get("adb_address", ""))
        stack.addWidget(addr)

        is_manual = inst.get("mumu_index") is None
        mode.setCurrentIndex(1 if is_manual else 0)
        stack.setCurrentIndex(1 if is_manual else 0)
        self._wire_access_mode(mode, stack, addr, ref)
        form.addRow("接入方式", mode)
        form.addRow("选择模拟器", stack)

        # 一台恰好一个角色（NoRoleInstanceConfig._one_character 保证加载时
        # 就在）；角色名是匹配游戏内账号的唯一凭据，直接摆进表单。
        char = inst["characters"][0]
        char_name = self._line(("quiz", "instances", idx, "characters", 0, "name"),
                               char.get("name", ""))
        char_name.setToolTip("必须和游戏内的显示名一致，程序按这个名字认账号。")
        form.addRow("角色名", char_name)
        outer.addLayout(form)
        self._fill_instance_list(ref)

        btns = QHBoxLayout()
        btns.setSpacing(theme.SP_SM)
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(lambda _c, r=ref: self._test_connection(r))
        del_btn = QPushButton("删除本答题模拟器")
        theme.make_danger(del_btn)
        del_btn.clicked.connect(lambda _c, i=idx: self._delete_quiz_instance(i))
        btns.addWidget(test_btn)
        btns.addWidget(del_btn)
        btns.addStretch(1)
        outer.addLayout(btns)
        self._status_labels[ref] = QLabel()
        outer.addWidget(self._status_labels[ref])
        self._set_inst_status(ref, "○ 未测试")
        self._preview_labels[ref] = QLabel()
        outer.addWidget(self._preview_labels[ref])
        return page

    def _add_quiz_instance(self):
        """添加一台答题模拟器（一台一个号，角色当场建好）。

        id 前缀与首启模板/寨多多同构（mumuN）——答题与寨多多的实例 id 是
        **两个独立命名空间**（各自校验唯一），所以允许重名。
        """
        used = {i["id"] for i in self._data["quiz"]["instances"]}
        n = 0
        while f"mumu{n}" in used:
            n += 1
        used_ids = {c["id"] for i in self._data["quiz"]["instances"]
                    for c in i["characters"]}
        k = 1
        while f"q{k}" in used_ids:
            k += 1
        self._data["quiz"]["instances"].append({
            "id": f"mumu{n}", "name": f"模拟器{n}", "mumu_index": None,
            "adb_address": "", "window_title_pattern": "",
            "characters": [{"id": f"q{k}", "name": "答题号"}]})
        self._reload_tree()
        # 添加完直接落到新实例页：打开对话框时已扫过模拟器，列表就在这一页，
        # 点一台就配完了。停在作答策略页等用户自己去左侧找条目，就是
        # 「点了没反应、加不了模拟器」的观感（2026-10-25 用户反馈）。
        quiz_item = self._page_item(3)
        if quiz_item is not None and quiz_item.childCount():
            self._tree.setCurrentItem(quiz_item.child(quiz_item.childCount() - 1))

    def _delete_quiz_instance(self, idx: int):
        inst = self._data["quiz"]["instances"][idx]
        answer = QMessageBox.question(
            self, "删除答题模拟器",
            f"确定删除答题模拟器 {inst.get('name') or inst['id']}？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._data["quiz"]["instances"].pop(idx)
        self._reload_tree()

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
        inst = self._data["zhaiduo"]["instances"][idx]
        page = QWidget()
        page.setObjectName(f"page:instance:{idx}")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(theme.SP_XL, theme.SP_XL, theme.SP_XL, theme.SP_XL)
        outer.setSpacing(theme.SP_LG)
        form = QFormLayout()
        form.setSpacing(theme.SP_SM)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)

        outer.addWidget(QLabel(f"模拟器 ID：{inst['id']}"))
        name = self._line(("zhaiduo", "instances", idx, "name"), inst.get("name", ""))
        form.addRow("显示名", name)

        mode = QComboBox()
        mode.setMaximumWidth(220)
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
        self._bind(("zhaiduo", "instances", idx, "mumu_index"), lst)
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
        addr = self._line(("zhaiduo", "instances", idx, "adb_address"), inst.get("adb_address", ""))
        stack.addWidget(addr)

        is_manual = inst.get("mumu_index") is None
        mode.setCurrentIndex(1 if is_manual else 0)
        stack.setCurrentIndex(1 if is_manual else 0)

        self._wire_access_mode(mode, stack, addr, idx)
        form.addRow("接入方式", mode)
        form.addRow("选择模拟器", stack)
        outer.addLayout(form)
        self._fill_instance_list(idx)

        outer.addWidget(QLabel("角色阵容（双击行编辑）"))
        table = QTableWidget(0, 5)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # 关网格线、去行号列：表头底色 + 行分隔线分区，比满屏网格干净（design-tokens §7）
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(36)
        table.setHorizontalHeaderLabels(["名字", "分工", "目标等级", "预设", "兵种 / 填兵目标"])
        header = table.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(True)
        self._tables[idx] = table
        for c in inst["characters"]:
            self._append_char_row(table, c)
        table.doubleClicked.connect(
            lambda _mi, i=idx, t=table: self._edit_character(i, t.currentRow()))
        outer.addWidget(table, 1)

        btns = QHBoxLayout()
        btns.setSpacing(theme.SP_SM)
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(lambda _c, i=idx: self._test_connection(i))
        add_btn = QPushButton("＋ 添加角色")
        theme.make_dashed(add_btn)
        add_btn.clicked.connect(lambda _c, i=idx, t=table: self._edit_character(i, -1))
        del_btn = QPushButton("删除选中角色")
        theme.make_danger(del_btn)
        del_btn.clicked.connect(lambda _c, i=idx, t=table: self._delete_character(i, t.currentRow()))
        add_inst_btn = QPushButton("＋ 添加模拟器")
        theme.make_dashed(add_inst_btn)
        add_inst_btn.clicked.connect(lambda _c: self._add_instance())
        del_inst_btn = QPushButton("删除本模拟器")
        theme.make_danger(del_inst_btn)
        del_inst_btn.clicked.connect(lambda _c, i=idx: self._delete_instance(i))
        btns.addWidget(test_btn)
        for b in (add_btn, del_btn, add_inst_btn, del_inst_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        outer.addLayout(btns)
        self._status_labels[idx] = QLabel()
        outer.addWidget(self._status_labels[idx])
        self._set_inst_status(idx, "○ 未测试")
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
        # 哨兵值 0 要写成人话，别在表格里摊出一个「0 级」；普通等级仍保持
        # 既有的紧凑写法（8→7→6），不加「级」字
        levels = "→".join(target_short(v) for v in c["target_levels"])
        for col, text in enumerate([c["name"], ROLE_LABELS[c["role"]],
                                    levels, preset_text, summary]):
            table.setItem(row, col, QTableWidgetItem(text))

    def _leader_candidates(self, exclude=None) -> list[dict]:
        out = []
        for i, inst in enumerate(self._data["zhaiduo"]["instances"]):
            for j, c in enumerate(inst["characters"]):
                if c["role"] in ("leader", "either") and (i, j) != exclude:
                    out.append({"instance": inst["id"], "name": c["name"]})
        return out

    def _edit_character(self, idx: int, row: int):
        inst = self._data["zhaiduo"]["instances"][idx]
        existing = inst["characters"][row] if 0 <= row < len(inst["characters"]) else None
        dlg = CharacterEditDialog(self, existing, self._leader_candidates(
            exclude=(idx, row) if existing else None))
        if dlg.exec() and dlg.get_result():
            self._save_character(idx, existing, dlg.get_result())

    def _save_character(self, idx: int, existing: dict | None, result: dict):
        chars = self._data["zhaiduo"]["instances"][idx]["characters"]
        if existing is not None:
            pos = next((i for i, c in enumerate(chars) if c["id"] == existing["id"]), None)
            if pos is None:
                return
            chars[pos] = result
        else:
            chars.append(result)
        # 重命名时同步所有实例中的填兵目标引用，避免悬空引用
        if existing is not None and existing["name"] != result["name"]:
            inst_id = self._data["zhaiduo"]["instances"][idx]["id"]
            for inst in self._data["zhaiduo"]["instances"]:
                for c in inst["characters"]:
                    for f in c.get("fill_target_leaders", []):
                        if f["instance"] == inst_id and f["name"] == existing["name"]:
                            f["name"] = result["name"]
        self._reload_tree()

    def _delete_character(self, idx: int, row: int):
        chars = self._data["zhaiduo"]["instances"][idx]["characters"]
        if 0 <= row < len(chars):
            chars.pop(row)
            self._reload_tree()

    def _add_instance(self):
        used = {i["id"] for i in self._data["zhaiduo"]["instances"]}
        n = 0
        # 与首启模板（config.example.yaml）用同一套前缀，免得用户在界面上
        # 看到模板里叫 mumu0、自己新加的却叫 inst1，以为是什么不同的东西。
        while f"mumu{n}" in used:
            n += 1
        self._data["zhaiduo"]["instances"].append({
            "id": f"mumu{n}", "name": f"模拟器{n}", "mumu_index": None,
            "adb_address": "", "window_title_pattern": "", "characters": []})
        self._reload_tree()

    def _delete_instance(self, idx: int):
        inst = self._data["zhaiduo"]["instances"][idx]
        answer = QMessageBox.question(
            self, "删除模拟器",
            f"确定删除模拟器 {inst.get('name') or inst['id']} 及其全部角色？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._data["zhaiduo"]["instances"].pop(idx)
        self._reload_tree()

    # ---- 扫描模拟器 / 按名字选中 ----

    # 实例引用（ref）有两种形态：int = 寨多多实例下标；("quiz", idx) = 答题
    # 实例下标。两种模式的实例页共用下面同一套机器（扫描列表 / 按名字选中 /
    # 测试连接 / 接入方式接线），差别只是数据落在哪一段。用 ref 而不是把两套
    # 逻辑各写一份——寨多多页踩过的坑（自动填名不覆盖用户输入、切模式清地址）
    # 答题页必须一模一样地继承，复制必然漂移。
    @staticmethod
    def _is_quiz_ref(ref) -> bool:
        return isinstance(ref, tuple)

    def _instance_at(self, ref) -> dict:
        if self._is_quiz_ref(ref):
            return self._data["quiz"]["instances"][ref[1]]
        return self._data["zhaiduo"]["instances"][ref]

    def _inst_field_path(self, ref, field: str) -> tuple:
        if self._is_quiz_ref(ref):
            return ("quiz", "instances", ref[1], field)
        return ("zhaiduo", "instances", ref, field)

    def _autofill_key(self, ref, inst_id: str) -> str:
        """自动填名的记账键。**必须带模式前缀**：两个模式的实例 id 是独立
        命名空间（都允许 mumu0），不带前缀会互相覆盖对方「这名是自动填的」
        记录，表现为换选时用户自己敲的名字被冲掉。"""
        mode = "quiz" if self._is_quiz_ref(ref) else "zhaiduo"
        return f"{mode}:{inst_id}"

    def _wire_access_mode(self, combo: QComboBox, stack: QStackedWidget,
                          addr: QLineEdit, ref):
        """接入方式下拉的公共接线：按模拟器选 / 手动填 adb 地址，二选一。

        切到「按模拟器选择」要清掉手填的地址（没选中任何模拟器时
        mumu_index 保持 None）；切到手动则清 mumu_index、地址跟输入框走。
        """
        def _on(i):
            inst = self._instance_at(ref)
            if i == 0:
                inst["adb_address"] = ""
                addr.clear()
                self._on_instance_pick(ref)   # 列表没选中就保持 mumu_index=None
            else:
                inst["mumu_index"] = None
                inst["adb_address"] = addr.text()
        combo.currentIndexChanged.connect(_on)
        combo.currentIndexChanged.connect(stack.setCurrentIndex)

    def _rescan(self):
        """跑一次 MuMuManager 列出所有模拟器，填进各模拟器页的列表。

        打开对话框时自动调一次（实机 255ms），结果缓存在 self._scanned，
        所有模拟器页共用——不该每切一页就重扫一遍。
        """
        manager = self._data["app"].get("mumu_manager_path", "")
        self._scan_error = None
        if not manager:
            self._scanned = None
            self._scan_error = "还没填 MuMuManager 路径，请先到「公共配置」自动检测或手动指定"
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

    def _fill_instance_list(self, ref):
        """把缓存里的扫描结果渲染成列表行；失败时显示一行提示让人重试。"""
        lst = self._instance_lists.get(ref)
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
            wanted = self._instance_at(ref).get("mumu_index")
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

    def _on_instance_pick(self, ref):
        """列表选中某台模拟器 → 记下它的编号（按名字选，不再手填数字）。"""
        lst = self._instance_lists.get(ref)
        if lst is None:
            return
        item = lst.currentItem()
        if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        self._data_set(self._inst_field_path(ref, "mumu_index"),
                       int(item.data(Qt.ItemDataRole.UserRole)))
        # 显示名留空时顺手填上模拟器名字，省得用户再想一个。
        # 只在「空着」或「还是我们上次填的那个」时才动它：用户点几行比较一下
        # 是常态，若不跟着换，最后会留下「选的是如愿、名字却是 15634025219」；
        # 而用户自己敲的名字则绝不覆盖。
        inst = self._instance_at(ref)
        name = (inst.get("name") or "").strip()
        key = self._autofill_key(ref, inst["id"])
        if not name or name == self._autofilled_names.get(key):
            picked = self._instance_name(inst["mumu_index"])
            if picked:
                inst["name"] = picked
                self._autofilled_names[key] = picked
                w = self._widgets.get(self._inst_field_path(ref, "name"))
                if isinstance(w, QLineEdit):
                    w.setText(picked)

    def _instance_name(self, index) -> str:
        for e in (self._scanned or []):
            if e["index"] == index:
                return e["name"]
        return ""

    # ---------------- 连接测试 / 在线检测 ----------------
    def _set_inst_status(self, idx: int, text: str) -> None:
        """写连接状态并按语义上色（● 走成功/进行色，○ 走中性/警告）。

        **文案一字不改**——测试按子串断言「如愿-2」「没有启动」「自动检测」
        「没有响应」「连接失败」「未配置」等，这里只加颜色。
        """
        label = self._status_labels.get(idx)
        if label is None:
            return
        label.setText(text)
        if text.startswith("●"):
            kind = "info" if "测试中" in text else "success"
        elif text.startswith("○") and "未配置" in text:
            kind = "warning"
        else:
            kind = "default"
        label.setStyleSheet(f"color:{theme.TAG_FG[kind]};")

    def _test_connection(self, ref):
        """spec §5：查模拟器在线 -> adb 截一帧显示缩略图，确认连的是这台。"""
        import cv2
        inst = self._instance_at(ref)
        if inst.get("mumu_index") is None and not inst.get("adb_address"):
            self._set_inst_status(
                ref, "○ 未配置：请先选一台模拟器，或手动填 adb 地址")
            return
        self._set_inst_status(ref, "● 测试中…")
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
            self._set_inst_status(ref, f"○ {self._explain_connect_error(inst, e)}")
            self._preview_labels[ref].clear()
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._set_inst_status(
            ref, f"● 已连接，截图 {img.shape[1]}x{img.shape[0]}")
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self._preview_labels[ref].setPixmap(QPixmap.fromImage(qimg).scaled(
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
            return ("找不到 MuMuManager，请到「公共配置」点「自动检测 MuMu/adb 路径」，"
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
        """spec §5：寨多多模式页「检测全部模拟器」，列出各模拟器在线状态。

        一次 `info -v all` 拿全，不再逐台 `is_running`（N 台省 N 次子进程）。
        输出用模拟器的**名字**，不再暴露 `inst0 (mumu2)` 这种内部 id。
        """
        self._rescan()          # 顺便刷新各页的列表，保证和这里的结论一致
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lines = []
            for inst in self._data["zhaiduo"]["instances"]:
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
                # ("zhaiduo", "instances", 0) 或 ()），其下所有控件都要标红
                if path[:len(loc)] == loc:
                    self._widgets[path].setStyleSheet(ERR_STYLE)
        QMessageBox.critical(self, "校验失败", "\n".join(lines) or str(e))


class CharacterEditDialog(QDialog):
    """单个角色的编辑表单（spec 2026-09-09 §5 角色编辑表单）。"""

    def __init__(self, parent, character: dict | None, candidates: list[dict]):
        super().__init__(parent)
        self.setWindowTitle("角色编辑")
        # 宽度留够：表单自然最小宽 ~562px，窄一点就会挤出横向滚动条
        self.resize(600, 700)
        self._character = dict(character) if character else None
        self._candidates = candidates

        # 表单进滚动区：目标等级 / 行军预设 / 填兵目标三块加起来很高，
        # 固定窗口下小屏会够不着底部的「确定」。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(theme.SP_XL, theme.SP_XL, theme.SP_XL, theme.SP_XL)
        form.setSpacing(theme.SP_MD)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignTop)
        outer.addWidget(ConfigDialog._scroll(content), 1)

        self.name_edit = QLineEdit((character or {}).get("name", ""))
        form.addRow("角色名（须与游戏内一致）", self.name_edit)

        self.role_combo = QComboBox()
        self.role_combo.setMaximumWidth(220)
        for r in ("leader", "member", "either"):
            self.role_combo.addItem(ROLE_LABELS[r])
        if (character or {}).get("role"):
            self.role_combo.setCurrentText(ROLE_LABELS[character["role"]])
        form.addRow("分工", self.role_combo)

        # 目标城寨等级（2026-10-04 用户要求）：1–15 复选框，最多勾 3 个。
        # 勾选**顺序即搜索顺序**（用户明确要求完全自由，例如 6→4→5），
        # 而复选框本身表达不了顺序，故下面挂一个标签实时显示结果；用户
        # 想调整顺序就取消重勾（新勾的排到最后）。
        #
        # 2026-10-11 新增「劫掠者寨子」（RAIDER_TARGET）：与等级**并列**
        # 但互斥——它是不分等级的特殊寨子，选了它就等于换了一类搜索目标，
        # 再叠等级没有意义（config 层的 _check_levels 也这么判）。互斥在
        # 这里做成「勾一个自动清空/禁用另一组」，比弹窗提示轻，且状态永远
        # 合法——与 _on_level_toggle 超上限时撤销勾选同一套做法。
        #
        # 2026-10-13 扩到 1–15：1–10 与 11–15 是**两个互斥区间**（区间由
        # 账号所在大地图决定，程序不需要切换），所以第 2 行留白放一条分割线，
        # 11–15 落到第 3 行；区间互斥与劫掠者互斥同法处理。
        self._level_order: list[int] = list((character or {}).get("target_levels", [7]))
        self.level_checks: dict[int, QCheckBox] = {}
        level_grid = QGridLayout()
        level_grid.setContentsMargins(0, 0, 0, 0)
        for i, lv in enumerate(range(MIN_TARGET_LEVEL, MAX_TARGET_LEVEL + 1)):
            cb = QCheckBox(str(lv))
            cb.setChecked(lv in self._level_order)
            self.level_checks[lv] = cb
            row = i // 5 if lv <= RANGE_BOUNDARY else i // 5 + 1   # 第 2 行留给区间分割线
            level_grid.addWidget(cb, row, i % 5)
        range_sep = QFrame()
        range_sep.setObjectName("hSeparator")
        range_sep.setFrameShape(QFrame.Shape.NoFrame)
        range_sep.setFixedHeight(1)
        level_grid.addWidget(range_sep, 2, 0, 1, 5)
        self.raider_check = QCheckBox(f"{RAIDER_LABEL}（不分等级）")
        self.raider_check.setChecked(RAIDER_TARGET in self._level_order)
        level_grid.addWidget(self.raider_check, 4, 0, 1, 5)
        # 信号在 setChecked 之后再接：否则初始化会把 _level_order 重排成
        # 勾选回调的顺序（配置里存的顺序就丢了）
        for lv, cb in self.level_checks.items():
            cb.toggled.connect(lambda on, v=lv: self._on_level_toggle(v, on))
        self.raider_check.toggled.connect(self._on_raider_toggle)
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
        self.cand_list.setMinimumHeight(160)
        self.sel_list.setMinimumHeight(160)
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

        outer.addWidget(self._footer())

        self.role_combo.currentTextChanged.connect(
            lambda _t: self.sel_list.setEnabled(
                self.role_combo.currentText() != ROLE_LABELS["leader"]))
        self.sel_list.setEnabled(self.role_combo.currentText() != ROLE_LABELS["leader"])

    def _footer(self) -> QWidget:
        """底部操作栏：1px 分割线 + 右对齐的「取消」（次）/「确定」（主）。"""
        footer = QWidget()
        lay = QVBoxLayout(footer)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        line = QFrame()
        line.setObjectName("hSeparator")
        line.setFrameShape(QFrame.Shape.NoFrame)
        line.setFixedHeight(1)
        lay.addWidget(line)

        row = QHBoxLayout()
        row.setContentsMargins(theme.SP_XL, theme.SP_MD, theme.SP_XL, theme.SP_MD)
        row.setSpacing(theme.SP_SM)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("确定")
        theme.make_primary(ok)
        ok.clicked.connect(self._on_ok)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        return footer

    def _on_level_toggle(self, level: int, checked: bool) -> None:
        if checked:
            if level in self._level_order:
                return
            low = level_range(level)[0]
            cross = [o for o, cb in self.level_checks.items()
                     if o != level and level_range(o)[0] != low and cb.isChecked()]
            if cross:
                # 换区间 = 换了一整组目标：先把另一区间清空。它们本来也不可能
                # 同时生效（面板同一时刻只停在一个区间上，config 层也这么判），
                # 与其让用户先手动取消再勾，不如直接换过去。
                for o in cross:
                    cb = self.level_checks[o]
                    cb.blockSignals(True)      # 清空不应触发本回调
                    cb.setChecked(False)
                    cb.blockSignals(False)
                    self._level_order.remove(o)
            elif len(self._level_order) >= MAX_TARGET_LEVELS:
                # 超上限：撤销这次勾选。比弹窗打断轻，且状态立刻回到合法
                self.level_checks[level].setChecked(False)
                return
            if self.raider_check.isChecked():
                # 勾了等级 → 劫掠者寨子自动让位（互斥的另一半）
                self.raider_check.setChecked(False)
            self._level_order.append(level)
        elif level in self._level_order:
            self._level_order.remove(level)
        self._refresh_level_order()

    def _on_raider_toggle(self, checked: bool) -> None:
        """劫掠者寨子只能单选：勾上就清空并禁用 1–15 级。"""
        if checked:
            self._level_order = [RAIDER_TARGET]
            for cb in self.level_checks.values():
                cb.blockSignals(True)     # 清空不应触发 _on_level_toggle
                cb.setChecked(False)
                cb.blockSignals(False)
        elif RAIDER_TARGET in self._level_order:
            self._level_order = []        # 取消勾选 → 回到「至少要选一个」
        self._refresh_level_order()

    def _refresh_level_order(self) -> None:
        """把当前顺序写到标签上，并锁住「已选满 3 个时未选中的框」。

        顺序是隐性状态（只存在于点击先后里），不显式显示的话用户无法
        确认 6→4→5 有没有生效。

        锁定**只作用于当前区间**：另一区间（1–10 与 11–15 互斥）的未选框
        保持可点——点它就是换区间，锁掉等于不让人换。
        """
        raider = RAIDER_TARGET in self._level_order
        if raider:
            self.level_order_label.setText(
                f"搜索目标：{RAIDER_LABEL}（不分等级，只能单选）")
        elif self._level_order:
            self.level_order_label.setText(
                "搜索顺序：" + " → ".join(str(v) for v in self._level_order))
        else:
            self.level_order_label.setText("搜索顺序：（至少勾一个等级）")
        full = len(self._level_order) >= MAX_TARGET_LEVELS
        # 选满 3 个时只锁**同区间**的未选框：另一区间的框要留着能点——
        # 点它就是换区间（_on_level_toggle 会清空本区间），锁掉等于不让人换。
        cur_low = level_range(self._level_order[0])[0] if self._level_order else None
        for lv, cb in self.level_checks.items():
            same_range = cur_low is None or level_range(lv)[0] == cur_low
            cb.setEnabled(
                not raider and (cb.isChecked() or not (full and same_range)))
        # 勾了等级就锁住劫掠者寨子，反向同理；两边都空时都可点
        self.raider_check.setEnabled(raider or not self._level_order)

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
