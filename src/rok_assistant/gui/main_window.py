from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QListWidget, QListWidgetItem, QStackedWidget,
    QStatusBar, QMessageBox
)
from PyQt6.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal, pyqtSlot

from . import theme
from .character_card import CharacterCard
from .controller import GuiController
from .flow_layout import clear_layout
from .license_dialog import LicenseDialog
from .log_handler import QtLogHandler
from .mode_page import ModePage
from ..infra.app_paths import config_path, ensure_user_files, user_dir
from ..infra.config import AppMode, MODE_LABELS
from ..infra.licensing import guard
from ..infra.logger import get_logger

logger = get_logger(__name__)

_WARN_DAYS = 7
_NOTICE_FILE = ".roklicense-notice"
_WINDOW_TITLE = "RoK 助手"


def warn_key(status) -> str:
    """提醒的「已读」标记值。

    带**到期日**：用户又买了天数（到期日变了）就重新提醒一次——否则
    「不再提醒」之后再也收不到提醒，买完才发现快到期。
    """
    return f"{status.kind}:{status.expiry}"


def should_warn(status, marker_text: str | None) -> bool:
    """到期前 7 天提醒一次（spec §8.1）。纯函数，便于单测。"""
    if status.kind not in ("trial", "licensed"):
        return False
    if status.days_left is None or status.days_left > _WARN_DAYS:
        return False
    return (marker_text or "").strip() != warn_key(status)


def _maybe_warn_expiring(parent):
    """启动时的一次性到期提醒。

    **只在 `main()` 里调，绝不能放进 `MainWindow.__init__`**：那样 400+ 条
    测试每条都会弹一次模态框，测试直接挂死。
    """
    try:
        status = guard.current_guard().status()
    except Exception:                          # noqa: BLE001
        return
    marker = user_dir() / _NOTICE_FILE
    try:
        text = marker.read_text(encoding="utf-8")
    except OSError:
        text = None
    if not should_warn(status, text):
        return
    box = QMessageBox(parent)
    box.setWindowTitle("授权即将到期")
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(f"{status.label()}，到期后将无法启动任务。")
    box.addButton("知道了", QMessageBox.ButtonRole.AcceptRole)
    never = box.addButton("不再提醒", QMessageBox.ButtonRole.DestructiveRole)
    box.exec()
    if box.clickedButton() is never:
        try:
            marker.write_text(warn_key(status), encoding="utf-8")
        except OSError:
            logger.warning("写入到期提醒标记失败：%s", marker)


class _BgTask(QObject):
    """把一次调用挪到后台线程，返回值经信号回主线程。

    `run` 里兜住异常：这是线程入口，异常逃出去没人接，线程直接静默死掉，
    界面永远停在「启动中…」。
    """

    done = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    @pyqtSlot()
    def run(self):
        try:
            result = self._fn()
        except Exception:                      # noqa: BLE001 - 见类注释
            logger.exception("后台任务异常")
            result = None
        self.done.emit(result)


class MainWindow(QMainWindow):
    # 四个相位是**唯一的界面状态源**：按钮可否点击、文案、状态栏全从它推导
    # （spec §5.4）。启动/停止要在后台线程上跑几秒，中间态必须存在，否则
    # 用户点完那几秒里界面既不显示「在启动」也点不了停止，看着像卡死。
    IDLE, STARTING, RUNNING, STOPPING = "idle", "starting", "running", "stopping"

    def __init__(self, controller: GuiController | None = None):
        super().__init__()
        self.setWindowTitle(_WINDOW_TITLE)
        self.resize(1280, 820)
        self._controller = controller if controller is not None \
            else GuiController(config_path=config_path())
        # 每个模式各一本卡册：两个模式的角色 id 可能撞车（都叫 c0），
        # 合成一本扁平字典会互相覆盖。
        self._cards_by_mode: dict[AppMode, dict[str, CharacterCard]] = {
            m: {} for m in AppMode}
        self._card_mode = AppMode.ZHAIDUO     # `_cards` 当前指向哪个模式
        self._pages: dict[AppMode, ModePage] = {}
        self._phase = self.IDLE
        self._run_mode: AppMode | None = None      # 相位所属的模式（空闲时 None）
        # 后台线程与任务的 Python 引用：只交给 Qt 父子关系的话，_run_async
        # 返回后局部变量出作用域，Python 侧包装被回收 → 线程跑到一半对象没了
        self._bg: list = []
        # 上一次画到卡片上的帧字节：同一帧不重画（见 _on_refresh）
        self._last_thumb: dict[str, bytes] = {}
        # 当前显示模式（文字/图文）。初值先按默认，真值等配置读进来再取——
        # `card_view()` 读的是内存配置，而首次 load_config() 要到下面
        # `_rebuild_cards()` 里才发生。
        self._view_mode = "image"
        self._build_ui()
        # 先接控制器信号再接卡：_rebuild_cards() 内部会经 controller.characters()
        # 触发首次 load_config()，失败时 error_occurred 要有人听（否则升级用户
        # 首次打开只看到空态，看不到那句可操作的报错）。
        self._connect_controller()
        self._rebuild_cards()
        self._apply_view_mode(self._controller.card_view())
        self._install_log_handler()
        self._setup_refresh_timer()

    # ---------------- UI 骨架 ----------------
    # 三段式：应用头 / 主体（左导航 + 模式页栈）/ 状态栏。分区靠 1px 弱分割线 + 留白，
    # 不用色块（design-tokens §4.1「留白承担分区职责，分割线代替色块」）。
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_body(), 1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")
        self._refresh_license_label()
        self._sync_ui_state()

    def _build_header(self) -> QWidget:
        """应用头：产品名 + 副标题（左），授权状态标签 + 激活入口（右）。"""
        header = QFrame()
        header.setObjectName("appHeader")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(theme.SP_XL, theme.SP_LG, theme.SP_XL, theme.SP_LG)
        lay.setSpacing(theme.SP_MD)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        title = QLabel("RoK 助手")
        title.setObjectName("appTitle")
        subtitle = QLabel("多模拟器集结与填兵自动化")
        subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        lay.addLayout(titles)
        lay.addStretch(1)                     # 授权区推到右边

        self.refresh_btn = QPushButton("刷新配置")
        self.refresh_btn.clicked.connect(self._on_refresh_config)
        self.config_btn = QPushButton("⚙ 配置")
        self.config_btn.clicked.connect(self._open_config)
        lay.addWidget(self.refresh_btn)
        lay.addWidget(self.config_btn)
        lay.addWidget(self._v_separator())
        self.license_label = QLabel("")
        self.license_label.setStyleSheet(theme.tag_style("default"))
        lay.addWidget(self.license_label)
        self.activate_btn = QPushButton("激活")
        self.activate_btn.clicked.connect(self._open_license_dialog)
        lay.addWidget(self.activate_btn)
        return header

    @staticmethod
    def _v_separator() -> QFrame:
        sep = QFrame()
        sep.setObjectName("vSeparator")
        sep.setFrameShape(QFrame.Shape.NoFrame)   # 线由 QSS 的背景色画，不叠两层
        sep.setFixedWidth(1)
        return sep

    def _build_body(self) -> QWidget:
        """左侧模式导航 + 右侧模式页栈（spec §5.3）。"""
        body = QWidget()
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.mode_nav = QListWidget()
        self.mode_nav.setObjectName("modeNav")
        self.mode_nav.setFixedWidth(160)
        for mode in AppMode:
            item = QListWidgetItem(MODE_LABELS[mode])
            item.setData(Qt.ItemDataRole.UserRole, mode)
            self.mode_nav.addItem(item)
        self.mode_nav.setCurrentRow(0)   # 固定开在寨多多（QListWidget 默认不选中任何行）
        self.mode_nav.currentRowChanged.connect(self._on_mode_changed)
        lay.addWidget(self.mode_nav)

        self.mode_stack = QStackedWidget()
        for mode in AppMode:
            page = ModePage(mode)
            # lambda 默认参数捕获 mode：否则所有页面共用循环结束时的那个值
            page.start_btn.clicked.connect(lambda _=False, m=mode: self._on_start(m))
            page.stop_btn.clicked.connect(self._on_stop)
            page.view_mode_changed.connect(self._on_view_mode_changed)
            self._pages[mode] = page
            self.mode_stack.addWidget(page)
        lay.addWidget(self.mode_stack, 1)
        return body

    def _on_mode_changed(self, row: int):
        if row < 0:
            return
        self.mode_stack.setCurrentIndex(row)
        # 防御性判空：`_build_body` 里 `setCurrentRow(0)` 排在
        # `currentRowChanged.connect` 之前，所以它**不会**触发本槽；真正
        # 会被触发的路径都在 `_pages` 装配完之后。判空成本为零，留着比
        # 假设「一定装配完了」安全。
        if not self._pages:
            return
        mode = self._current_nav_mode()
        # `_cards` 别名跟着选中页走——**不管这次建不建卡**。
        self._card_mode = mode
        # 切到哪个模式就**按需**建哪个模式的卡：已有卡就不重建。
        # 每次切页都重建会把那张卡的日志清掉（`_rebuild_cards` 造的是全新
        # CharacterCard，日志控件是空的）——跑完一轮切去看别的模式再切回来，
        # 日志就没了。真正需要重建的时机由调用方显式负责：`_on_start`
        # （开跑前重置）与 `_on_refresh_config`（用户点刷新）。
        if not self._cards_by_mode[mode]:
            self._rebuild_cards(mode)

    # ---------------- 显示模式（文字 / 图文） ----------------
    def _apply_view_mode(self, mode: str) -> None:
        """全局生效：所有模式页 + 所有卡片。

        开关只挂在寨多多页头上，但它换的是整个界面的取景方式——三个页面
        共用一个模式，来回切模式不该看到两种版式。
        """
        self._view_mode = mode
        for page in self._pages.values():
            page.set_view_mode(mode)
        for cards in self._cards_by_mode.values():
            for card in cards.values():
                card.set_view_mode(mode)

    def _on_view_mode_changed(self, mode: str) -> None:
        self._apply_view_mode(mode)
        label = "文字模式" if mode == "text" else "图文模式"
        # 写盘失败不拦切换：为了一个观感开关把界面卡住比不保存糟得多，
        # 但得说清楚「这次生效了、下次开窗不记得」。
        if self._controller.set_card_view(mode):
            self.statusBar().showMessage(f"已切到{label}")
        else:
            self.statusBar().showMessage(
                f"已切到{label}；本次生效，但未能写入 config.yaml")

    def _connect_controller(self):
        # worker 线程经信号跨线程送达（Qt 自动排队），槽内访问控件是主线程安全的
        self._controller.status_changed.connect(self._on_status_changed)
        self._controller.error_occurred.connect(self._on_error)
        self._controller.run_finished.connect(self._on_run_finished)

    def _install_log_handler(self):
        """挂到 root logger，把日志行投给对应卡片。

        无头驱动（`_run_goal.py`）不构造 MainWindow，完全走不到这条路径。
        先把同类型的旧 handler 摘掉：`test_gui_smoke.py` 每条用例都新建一个
        MainWindow，否则 handler 会随测试条数线性累积（预检裁定 8）。
        """
        root = logging.getLogger()
        for old in [h for h in root.handlers if isinstance(h, QtLogHandler)]:
            root.removeHandler(old)
        self._log_handler = QtLogHandler()
        self._log_handler.record_emitted.connect(self._on_log_line)
        root.addHandler(self._log_handler)
        # handler 的存活期绑到窗口：窗口 C++ 销毁时立刻把它从 root logger
        # 摘掉。否则 root 上会残留一个「Python 包装还在、C++ 已删」的死
        # handler，之后任何 logger.* 调用都会在 emit 里抛 RuntimeError
        # （2026-10-06 评审 Important）。
        #
        # 用 lambda 捕获 handler、不连 self 的绑定方法：PyQt 在 `destroyed`
        # 发射时已把接收者 self 判为销毁中，绑定方法不会被调用（实测只有
        # lambda/普通可调用会触发）；removeHandler 只动 Python 列表，
        # 不碰已销毁的 C++ 对象。
        handler = self._log_handler
        self.destroyed.connect(lambda *_: root.removeHandler(handler))

    @property
    def _cards(self) -> dict[str, CharacterCard]:
        """当前选中模式的卡册。

        **是属性不是字段**：既有的一批断言按扁平 char_id 键用它
        （`set(w._cards) == {...}`、`w._cards["boss"]`），改成
        `dict[AppMode, dict]` 就得改那些测试。路由日志/状态请用
        `_find_card()`，别直接读它。
        """
        return self._cards_by_mode[self._card_mode]

    def _find_card(self, char_id: str) -> CharacterCard | None:
        """按 char_id 跨模式找卡片。

        先查运行中的模式，再按 AppMode 声明顺序兜底：两个模式的角色 id
        可能撞车，撞了的时候日志该进**正在跑**那一本（`_card_mode` 是
        「当前在看哪页」，与「谁在跑」不是一回事——用户停完任务切到别的
        模式看配置，那次运行的收尾日志仍该落到它自己的卡上）。
        """
        order = [self._run_mode] if self._run_mode else []
        order += [m for m in AppMode if m != self._run_mode]
        for mode in order:
            card = self._cards_by_mode[mode].get(char_id)
            if card is not None:
                return card
        return None

    def _on_log_line(self, char_id: str, text: str):
        if not char_id:
            self.statusBar().showMessage(text)
            return
        card = self._find_card(char_id)
        if card is not None:
            card.append_log(text)

    # ---------------- 角色卡片 ----------------
    def _rebuild_cards(self, mode: AppMode | None = None):
        """重建 `mode`（默认当前选中页）的卡片。

        只动这一个模式：清掉别的模式的卡会让「切过去看一眼再切回来」变成
        空白，而两边的卡本来就各自挂在各自的 `ModePage.card_layout` 上。
        """
        if mode is None:
            mode = self._current_nav_mode()
        page = self._pages[mode]
        self._card_mode = mode
        clear_layout(page.card_layout)
        self._cards_by_mode[mode].clear()
        self._last_thumb.clear()     # 旧帧的字节没有意义了，别让它挡住新卡首帧
        for info in self._controller.characters(mode):
            card = CharacterCard(info["char_name"], info["role"])
            card.set_view_mode(self._view_mode)
            self._cards_by_mode[mode][info["char_id"]] = card
            page.card_layout.addWidget(card)
        self._sync_ui_state()
        if not self._cards_by_mode[mode]:
            self.statusBar().showMessage(
                f"未加载到角色：请检查 config.yaml 的 {MODE_LABELS[mode]} 段后"
                f"点击「刷新配置」")

    def _current_nav_mode(self) -> AppMode:
        item = self.mode_nav.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else AppMode.ZHAIDUO

    def _on_refresh_config(self):
        # 必须强制重读磁盘：controller.characters() 只在未加载时读盘，
        # 否则配置文件改了界面也不会变
        if not self._reload_controller_config():
            return
        self._rebuild_cards()

    def _reload_controller_config(self) -> bool:
        try:
            self._controller.reload_config()
            return True
        except Exception as e:
            logger.exception("重读配置失败")
            QMessageBox.critical(self, "刷新配置", f"重读配置失败：{e}")
            return False

    # ---------------- 运行控制 ----------------
    def _on_start(self, mode: AppMode):
        # 相位闸门：按钮此时已禁用，但 `_on_start` 可能被程序化调用（脚本、
        # 将来的快捷键）——真起了两份协调器会争同一个模拟器。
        if self._phase != self.IDLE:
            return
        if not self._license_ok():             # 到期就不让跑（但仍能开窗）
            return
        if not self._controller.config_loaded and not self._controller.load_config():
            return
        self._rebuild_cards(mode)   # 懒加载后建卡，状态才有落点
        self._set_phase(self.STARTING, mode)
        self.statusBar().showMessage("正在启动…")
        # 预检要连模拟器、载 ONNX，真机上几秒起步——放主线程就是那几秒的卡顿。
        self._run_async(lambda: self._controller.start(mode),
                        self._on_start_done)

    def _on_start_done(self, ok):
        """启动收尾（主线程）。失败时错误已由 error_occurred 弹框呈现。"""
        if ok:
            self._set_phase(self.RUNNING, self._run_mode)
            self.statusBar().showMessage("运行中")
            return
        self._set_phase(self.IDLE)
        self.statusBar().showMessage("启动失败")

    def _on_stop(self):
        if self._phase != self.RUNNING:
            return
        self._set_phase(self.STOPPING, self._run_mode)
        self.statusBar().showMessage("正在停止…")
        # 停止要逐个 join worker 线程（每个最多 2s），同样不能压在主线程上
        self._run_async(self._controller.stop, self._on_stop_done)

    def _on_stop_done(self, _result):
        self._set_phase(self.IDLE)
        # 立刻把最后一轮读数推到统计条：空闲时定时器已经不取帧了，
        # 等下一个周期意味着用户点完停止盯着看的是一份过期战绩。
        self._refresh_stats()
        self.statusBar().showMessage("已停止")

    def _set_phase(self, phase: str, mode: AppMode | None = None) -> None:
        """**唯一的相位变更入口**。所有按钮态与文案都从 _phase 推导。"""
        self._phase = phase
        self._run_mode = None if phase == self.IDLE else (mode or self._run_mode)
        self._sync_ui_state()

    def _run_async(self, fn, on_done) -> None:
        """把 fn 丢到后台线程，返回值经 on_done 回主线程。

        `on_done` 是绑定方法 → PyQt 按接收者（主窗口）做自动断连，窗口先
        销毁时结果不会打进已删的控件。
        """
        thread = QThread()
        task = _BgTask(fn)
        task.moveToThread(thread)
        pair = (thread, task)
        self._bg.append(pair)
        thread.started.connect(task.run)
        task.done.connect(on_done)
        task.done.connect(thread.quit)
        thread.finished.connect(lambda: self._forget_bg(pair))
        thread.start()

    def _forget_bg(self, pair) -> None:
        if pair in self._bg:
            self._bg.remove(pair)

    def closeEvent(self, event):                   # noqa: N802 - Qt 命名
        """关窗前等在跑的后台任务收尾。

        QThread 不是守护线程：窗口关掉时它还活着，C++ 侧对象先被销毁就是
        「QThread: Destroyed while thread is still running」——直接 abort。
        """
        self._timer.stop()
        for thread, _task in list(self._bg):
            thread.quit()
            thread.wait(3000)
        super().closeEvent(event)

    def _sync_ui_state(self):
        """从三个输入推导全部界面状态：相位 / 相位所属模式 / 有无角色。

        互斥不是靠三处 if 维护的，是从 _phase 这一个状态**推导**出来的
        （spec §5.4）。加模式维度后散落的 setEnabled 会翻倍，改一处漏一处。
        """
        phase = self._phase
        busy = phase != self.IDLE              # 启动/运行/停止中都算「占着」
        self.mode_nav.setEnabled(not busy)     # 非空闲时锁导航
        for mode, page in self._pages.items():
            mine = mode == self._run_mode
            page.start_btn.setEnabled(not busy and page.implemented)
            page.stop_btn.setEnabled(phase == self.RUNNING and mine)
            # 文案也是推导出来的：点完那几秒界面得看得出「在做事」
            page.start_btn.setText(
                "启动中…" if phase == self.STARTING and mine else "开始运行")
            page.stop_btn.setText(
                "停止中…" if phase == self.STOPPING and mine else "停止")
            if not page.implemented:
                page.body.setCurrentIndex(ModePage.LOCKED)
            elif page.card_layout.count():
                page.body.setCurrentIndex(ModePage.CARD)
            else:
                page.body.setCurrentIndex(ModePage.EMPTY)

    # ---------------- 状态 / 错误 / 缩略图 ----------------
    def _on_status_changed(self, payload: dict):
        card = self._find_card(payload.get("char_id"))
        if card is not None:
            card.set_status(payload.get("state", ""))

    def _on_error(self, message: str):
        QMessageBox.critical(self, "错误", message)

    def _on_run_finished(self, payload: dict):
        """全部 worker 跑完（自然收工）：按钮复位到停止态。

        用户点 Stop 走的不是这条路——runner 只在 stopped_reason 非 None
        时上报 worker_finished。不弹模态框：跑完是正常结束，打断无人值守
        场景反而添乱。
        """
        # 只在运行中才复位：停止中收到它（收工与手动停止撞车）时相位归
        # `_on_stop_done` 收尾，否则 worker 还没 join 完按钮就先亮了。
        if self._phase == self.RUNNING:
            self._set_phase(self.IDLE)
        reasons = "；".join(f"{k}: {v}" for k, v
                            in (payload.get("reasons") or {}).items())
        self.statusBar().showMessage(f"已收工 —— {reasons}" if reasons else "已收工")

    def _setup_refresh_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._on_refresh)
        self._timer.start()

    def _on_refresh(self):
        """2s 定时刷新：统计条常刷，缩略图只在运行中且图文模式下取。

        缩略图这条路以前是「每周期对每个角色走一趟全帧 JPEG 编码 + 解码 +
        平滑缩放」，号越多越贵，而画面绝大多数时候根本没变。三道减法：
        空闲不取、文字模式不取、字节没变不重画。
        """
        self._refresh_stats()
        if self._phase != self.RUNNING:
            return
        if self._view_mode == "text":
            return          # 文字模式不展示截屏：连帧都不去协调器拿
        for cards in self._cards_by_mode.values():
            for char_id, card in cards.items():
                data = self._controller.snapshot(char_id)
                if data is None or data == self._last_thumb.get(char_id):
                    continue    # 没帧（正在切场景）或同一帧：保留上一张，不重画
                self._last_thumb[char_id] = data
                card.set_thumbnail(data)

    def _refresh_stats(self):
        stats = self._controller.stats()
        for page in self._pages.values():
            page.set_stats(stats)

    # ---------------- 授权 ----------------
    def _refresh_license_label(self):
        """状态栏常驻授权标签。

        **不弹窗、不拦启动**——到期也照常开窗，用户看得到自己的配置还在
        （spec §2「能进界面，不能跑任务」）。
        """
        try:
            self._apply_license_label(guard.current_guard().status())
        except Exception:                      # noqa: BLE001 - 授权坏了不该拖垮界面
            logger.exception("读取授权状态失败")
            self.license_label.setText("授权状态未知")
            self.license_label.setStyleSheet(theme.tag_style("default"))

    def _apply_license_label(self, status):
        self.license_label.setText(status.label())
        # 标准状态标签（浅底 + 深字），不再用裸彩色文字
        self.license_label.setStyleSheet(
            theme.tag_style("success" if status.allows_run else "error"))

    def _license_ok(self) -> bool:
        """Start 前的授权闸门：不允许就弹激活窗、拒绝启动（按钮保持可点，spec §8.1）。

        读不出状态时**一律拦**（fail closed）：这是 Qt 槽，异常逃出去 PyQt6
        会直接 abort 整个进程；而且放行等于给了一条「让 status() 抛异常即可
        免授权」的路径。界面仍能开，用户看得到自己的配置还在。
        """
        try:
            status = guard.current_guard().status()
        except Exception:                      # noqa: BLE001 - 授权坏了不该拖垮界面
            logger.exception("读取授权状态失败，拒绝启动")
            self.license_label.setText("授权状态未知")
            self.license_label.setStyleSheet(theme.tag_style("default"))
            self.statusBar().showMessage("授权状态未知，无法启动任务")
            return False
        self._apply_license_label(status)
        if status.allows_run:
            return True
        self.statusBar().showMessage(status.label())
        self._open_license_dialog()
        return False

    def _open_license_dialog(self):
        """打开激活窗——授权出问题时用户**唯一**的自救入口。

        这是个 Qt 槽，异常逃出去 PyQt6 默认 qFatal → 整个进程 abort。构造
        `LicenseDialog` 前要 `current_guard()`，而它可能抛（记录被改坏等），
        所以这里必须兜住：弹提示总好过点「激活」直接崩。
        """
        try:
            dlg = LicenseDialog(guard.current_guard(), self)
            if dlg.exec():
                self._refresh_license_label()
        except Exception:                      # noqa: BLE001 - 授权坏了不该拖垮界面
            logger.exception("打开授权窗口失败")
            QMessageBox.warning(self, "授权",
                                "授权组件异常，请把 --selftest 的输出发给作者")

    def _open_config(self):
        path = config_path()
        if not path.exists():
            QMessageBox.warning(self, "配置", f"未找到 {path}（请先在项目根目录准备 config.yaml）")
            return
        from .config_dialog import ConfigDialog
        dlg = ConfigDialog(path, self)
        if dlg.exec():   # accept 只在保存成功后发生
            # 配置对话框保存后可能改动了阵容，回来强制重读并刷新卡片
            if self._reload_controller_config():
                self._rebuild_cards()


def main():
    import sys
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from rok_assistant.infra.logger import setup_logging

    # 首启：没有 config.yaml 就从 config.example.yaml 生成一份并探测 MuMu 路径。
    # 冻结运行时 CWD 可能是任意目录，所以 config/logs/recordings 一律按
    # user_dir()（exe 同级）走，只读资源按 resource_dir()（_internal）走。
    ensure_user_files()
    # 2026-09-11 实机验收发现：入口从未接 setup_logging —— 日志文件缺失，
    # 控制台报错无 traceback。日志目录优先取项目 logs/（§3.8 验收要求）。
    setup_logging(user_dir() / "logs")

    # 授权状态在这里查一次就够（WMI 在冻结包里慢，1~2s）。
    # **不拦截启动**：到期也照常开窗，由 Start 按钮拦。
    try:
        guard.current_guard().status()
    except Exception:                          # noqa: BLE001
        logger.exception("授权状态初始化失败，界面照常打开")

    try:
        app = QApplication(sys.argv)
        # 主题必须在**建控件之前**装：QSS 在 polish 时读动态属性，
        # 控件先建好再上样式，主按钮的 [primary="true"] 选择器不生效。
        theme.apply_theme(app)
        w = MainWindow()
        w.show()
        _maybe_warn_expiring(w)                # 到期前 7 天提醒一次（spec §8.1）
    except Exception as e:            # noqa: BLE001 - console=False 时看不到 traceback
        import traceback
        crash = user_dir() / "logs" / "startup_crash.log"
        try:
            crash.parent.mkdir(parents=True, exist_ok=True)
            crash.write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        QMessageBox.critical(None, "启动失败",
                             f"{e}\n\n详情见：{crash}")
        raise
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
