from __future__ import annotations
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

from .labels import role_label, state_label
from .log_panel import LogPanel

_LOG_MAX_LINES = 200


class CharacterCard(QFrame):
    def __init__(self, name: str, role: str, status: str = "idle"):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        # 比原来的 220x280 高出一截，给日志区让位
        self.setFixedSize(220, 430)
        self.error_state = False
        self._build(name, role, status)

    def _build(self, name, role, status):
        layout = QVBoxLayout(self)
        # 分工/状态都翻中文：配置页写「车头」，主界面卡片却写「leader」
        # 是同一个人在两处看到两个词（2026-10-05 用户反馈）
        self.title_label = QLabel(f"{name}（{role_label(role)}）")
        self.status_label = QLabel(state_label(status))
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(200, 150)
        self.thumbnail.setStyleSheet("background: #222;")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setText("(no image)")
        # 复用既有的 LogPanel（只读 + 环形裁剪 + 时间戳），不另造一个同款。
        # 归属由 MainWindow 按线程名解析后投递（见 gui/log_handler.py）。
        self.log_view = LogPanel(max_lines=_LOG_MAX_LINES)
        self.log_view.setSizePolicy(QSizePolicy.Policy.Preferred,
                                    QSizePolicy.Policy.Expanding)
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.thumbnail)
        layout.addWidget(self.log_view)

    def append_log(self, text: str) -> None:
        self.log_view.append_message(text)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def set_thumbnail(self, img_bytes: bytes) -> None:
        pix = QPixmap()
        pix.loadFromData(img_bytes)
        self.thumbnail.setPixmap(pix.scaled(
            200, 150, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))

    def set_error(self, message: str) -> None:
        self.error_state = True
        self.status_label.setText(f"ERROR: {message}")
        self.setStyleSheet("background: #500;")

    def set_status(self, status: str) -> None:
        self.status_label.setText(state_label(status))
