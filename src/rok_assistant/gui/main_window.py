from __future__ import annotations
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QScrollArea, QStatusBar, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer

from .character_card import CharacterCard
from .controller import GuiController
from ..infra.logger import get_logger

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, controller: GuiController | None = None):
        super().__init__()
        self.setWindowTitle("rok-assistant")
        self.resize(1200, 800)
        self._controller = controller if controller is not None \
            else GuiController(config_path=Path("config.yaml"))
        self._cards: dict[str, CharacterCard] = {}
        self._build_ui()
        self._rebuild_cards()
        self._connect_controller()
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
        path = Path("config.yaml")
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
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
