from __future__ import annotations
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

class CharacterCard(QFrame):
    def __init__(self, name: str, role: str, status: str = "idle"):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedSize(220, 280)
        self.error_state = False
        self._build(name, role, status)

    def _build(self, name, role, status):
        layout = QVBoxLayout(self)
        self.title_label = QLabel(f"{name} ({role})")
        self.status_label = QLabel(status)
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(200, 150)
        self.thumbnail.setStyleSheet("background: #222;")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setText("(no image)")
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.thumbnail)
        layout.addStretch()

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
        self.status_label.setText(status)
