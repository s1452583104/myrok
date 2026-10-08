from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QScrollArea, QStatusBar, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer

from .character_card import CharacterCard
from .controller import GuiController
from .license_dialog import LicenseDialog
from .log_handler import QtLogHandler
from ..infra.app_paths import config_path, ensure_user_files, user_dir
from ..infra.licensing import guard
from ..infra.logger import get_logger

logger = get_logger(__name__)

_WARN_DAYS = 7
_NOTICE_FILE = ".roklicense-notice"


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


class MainWindow(QMainWindow):
    def __init__(self, controller: GuiController | None = None):
        super().__init__()
        self.setWindowTitle("rok-assistant")
        self.resize(1200, 800)
        self._controller = controller if controller is not None \
            else GuiController(config_path=config_path())
        self._cards: dict[str, CharacterCard] = {}
        self._build_ui()
        self._rebuild_cards()
        self._connect_controller()
        self._install_log_handler()
        self._setup_refresh_timer()

    # ---------------- UI 骨架 ----------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        # Top bar
        top = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)   # 初始未运行，Stop 不可用
        self.stop_btn.clicked.connect(self._on_stop)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["rally"])
        self.refresh_btn = QPushButton("刷新配置")
        self.refresh_btn.clicked.connect(self._on_refresh_config)
        top.addWidget(self.start_btn)
        top.addWidget(self.stop_btn)
        top.addWidget(QLabel("Mode:"))
        top.addWidget(self.mode_combo)
        top.addWidget(self.refresh_btn)
        self.config_btn = QPushButton("⚙ 配置")
        self.config_btn.clicked.connect(self._open_config)
        top.addWidget(self.config_btn)
        top.addStretch()                      # 授权标签推到右边
        self.license_label = QLabel("")
        top.addWidget(self.license_label)
        self.activate_btn = QPushButton("激活")
        self.activate_btn.clicked.connect(self._open_license_dialog)
        top.addWidget(self.activate_btn)
        root.addLayout(top)
        # Account area
        self.account_area = QScrollArea()
        # 内部容器必须随卡片撑开，否则真机窗口里卡片区一片空白
        # （离屏测试只断言卡片对象存在，测不出不可见——2026-09-11 实机验收发现）
        self.account_area.setWidgetResizable(True)
        self.account_widget = QWidget()
        self.account_layout = QVBoxLayout(self.account_widget)
        self.account_layout.addStretch()
        self.account_area.setWidget(self.account_widget)
        root.addWidget(self.account_area)
        # Status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")
        self._refresh_license_label()

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

    def _on_log_line(self, char_id: str, text: str):
        if not char_id:
            self.statusBar().showMessage(text)
            return
        card = self._cards.get(char_id)
        if card is not None:
            card.append_log(text)

    # ---------------- 角色卡片 ----------------
    def _rebuild_cards(self):
        # 清空旧卡片
        while self.account_layout.count() > 1:   # 末尾是 stretch
            item = self.account_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards.clear()
        for info in self._controller.characters():
            card = CharacterCard(info["char_name"], info["role"])
            self._cards[info["char_id"]] = card
            self.account_layout.insertWidget(self.account_layout.count() - 1, card)
        if not self._cards:
            self.statusBar().showMessage("未加载到角色：请检查 config.yaml 后点击「刷新配置」")

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
    def _on_start(self):
        if not self._license_ok():             # 到期就不让跑（但仍能开窗）
            return
        if not self._controller.config_loaded and not self._controller.load_config():
            return
        self._rebuild_cards()   # 懒加载后建卡，状态才有落点
        # 只有真起来了才切运行态。启动失败（如预检被拒）时 start() 返回 False，
        # 错误已由 error_occurred 弹框呈现；若照旧置位，界面会谎报「运行中」，
        # Start 变灰、Stop 可点，而实际什么都没跑。
        if not self._controller.start():
            return
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.statusBar().showMessage("运行中")

    def _on_stop(self):
        self._controller.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.statusBar().showMessage("已停止")

    # ---------------- 状态 / 错误 / 缩略图 ----------------
    def _on_status_changed(self, payload: dict):
        card = self._cards.get(payload.get("char_id"))
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
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        reasons = "；".join(f"{k}: {v}" for k, v
                            in (payload.get("reasons") or {}).items())
        self.statusBar().showMessage(f"已收工 —— {reasons}" if reasons else "已收工")

    def _setup_refresh_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._on_refresh)
        self._timer.start()

    def _on_refresh(self):
        # 缩略图轮询：只在运行中拉取（未运行时 snapshot 返回 None，直接跳过）
        if not self._controller.config_loaded:
            return
        for char_id, card in self._cards.items():
            data = self._controller.snapshot(char_id)
            if data is not None:
                card.set_thumbnail(data)

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

    def _apply_license_label(self, status):
        self.license_label.setText(status.label())
        self.license_label.setStyleSheet(
            "color:#27ae60;" if status.allows_run else "color:#c0392b;")

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
