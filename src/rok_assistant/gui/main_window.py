from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QScrollArea, QStatusBar, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer

from .character_card import CharacterCard
from .controller import GuiController
from .log_handler import QtLogHandler
from ..infra.app_paths import config_path, ensure_user_files, user_dir
from ..infra.logger import get_logger

logger = get_logger(__name__)


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
        if not self._controller.config_loaded and not self._controller.load_config():
            return
        self._rebuild_cards()   # 懒加载后建卡，状态才有落点
        self._controller.start()
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

    try:
        app = QApplication(sys.argv)
        w = MainWindow()
        w.show()
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
