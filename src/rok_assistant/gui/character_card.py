"""角色卡片：名字 / 分工 + 运行状态标签 + 画面缩略图 + 该角色的日志。

版式遵循企业级卡片标准（design-tokens §6）：白底、1px 弱描边、8px 圆角、
16px 内边距；标题 16/500，运行状态走标准状态标签（浅底 + 深字 + 同色圆点）。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                             QVBoxLayout)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

from . import theme
from .labels import role_label, state_kind, state_label
from .log_panel import LogPanel

_LOG_MAX_LINES = 200

_CARD_W = 300
_CARD_H = 440
_PAD = theme.SP_LG
# 缩略图宽度 = 卡片宽 - 左右内边距 - 左右各 1px 描边
_THUMB_W = _CARD_W - 2 * _PAD - 2
_THUMB_H = 150


class CharacterCard(QFrame):
    def __init__(self, name: str, role: str, status: str = "idle"):
        super().__init__()
        self.setObjectName("characterCard")
        self.setFixedSize(_CARD_W, _CARD_H)
        self.error_state = False
        self._build(name, role, status)

    def _build(self, name, role, status):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        layout.setSpacing(theme.SP_MD)

        # 分工翻中文：配置页写「车头」，主界面卡片却写「leader」是同一个人在两处
        # 看到两个词（2026-10-05 用户反馈）。名字与分工同处一个标签，测试也据此断言。
        self.title_label = QLabel(f"{name}（{role_label(role)}）")
        self.title_label.setObjectName("cardTitle")
        layout.addWidget(self.title_label)

        # 状态标签：圆点是**独立控件**，不拼进 status_label 的文本里
        # （测试按精确串断言 status_label.text()）。
        self._status_tag = QFrame()
        self._status_tag.setObjectName("statusTag")
        tag_layout = QHBoxLayout(self._status_tag)
        tag_layout.setContentsMargins(theme.SP_SM, 2, theme.SP_SM, 2)
        tag_layout.setSpacing(theme.SP_XS + 2)
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(6, 6)
        self.status_label = QLabel(state_label(status))
        tag_layout.addWidget(self._status_dot)
        tag_layout.addWidget(self.status_label)
        tag_row = QHBoxLayout()
        tag_row.setContentsMargins(0, 0, 0, 0)
        tag_row.addWidget(self._status_tag)
        tag_row.addStretch(1)
        layout.addLayout(tag_row)

        self.thumbnail = QLabel("暂无画面")
        self.thumbnail.setFixedSize(_THUMB_W, _THUMB_H)
        # 浅色占位块，不再是深灰 `#222`（浅色界面里那是个洞）
        self.thumbnail.setStyleSheet(
            f"background:{theme.BG_HEADER};border:1px solid {theme.BORDER_SPLIT};"
            f"border-radius:{theme.RADIUS_MD}px;color:{theme.TEXT_TERTIARY};")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.thumbnail)

        section = QLabel("运行日志")
        section.setObjectName("sectionTitle")
        layout.addWidget(section)

        # 复用既有的 LogPanel（只读 + 环形裁剪 + 时间戳），不另造一个同款。
        # 归属由 MainWindow 按线程名解析后投递（见 gui/log_handler.py）。
        self.log_view = LogPanel(max_lines=_LOG_MAX_LINES)
        self.log_view.setSizePolicy(QSizePolicy.Policy.Preferred,
                                    QSizePolicy.Policy.Expanding)
        layout.addWidget(self.log_view)

        self._apply_tag(state_kind(status))

    # ---------------- 状态 ----------------
    def _apply_tag(self, kind: str) -> None:
        # 选择器限定到 #statusTag：裸声明会连子控件（圆点、文字）一起刷成同底色
        self._status_tag.setStyleSheet(
            f"QFrame#statusTag {{ {theme.tag_style(kind)} }}")
        self._status_dot.setStyleSheet(theme.dot_style(kind))

    def set_status(self, status: str) -> None:
        self.status_label.setText(state_label(status))
        self._apply_tag(state_kind(status))

    def set_error(self, message: str) -> None:
        """错误态：标签转红 + 卡片 1px 红描边。

        不再整块铺 `#500` 暗红——状态色只承载语义，不做装饰（design-tokens §4.2）。
        """
        self.error_state = True
        self.status_label.setText(f"ERROR: {message}")
        self._apply_tag("error")
        self.setStyleSheet(
            f"QFrame#characterCard {{ border:1px solid {theme.ERROR}; }}")

    def append_log(self, text: str) -> None:
        self.log_view.append_message(text)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def set_thumbnail(self, img_bytes: bytes) -> None:
        pix = QPixmap()
        pix.loadFromData(img_bytes)
        self.thumbnail.setPixmap(pix.scaled(
            _THUMB_W, _THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
