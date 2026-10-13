from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt

from . import theme
from .flow_layout import FlowLayout
from ..infra.config import AppMode, IMPLEMENTED_MODES, MODE_LABELS


class ModePage(QWidget):
    """一个模式一页：页头（模式名 + 开始/停止）+ 内容三态。

    内容用 QStackedWidget 的固定索引，让 _sync_ui_state 只做「选哪一页」：
      0 = 卡片流式网格（有角色）
      1 = 空态占位（未加载到角色）
      2 = 「该模式尚未开放」（未实现的模式）
    """

    CARD, EMPTY, LOCKED = 0, 1, 2

    def __init__(self, mode: AppMode):
        super().__init__()
        self.mode = mode
        self.implemented = mode in IMPLEMENTED_MODES

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_head())

        self.body = QStackedWidget()
        self.body.addWidget(self._build_cards())
        self.body.addWidget(self._build_empty())
        self.body.addWidget(self._build_locked())
        lay.addWidget(self.body, 1)

    def _build_head(self) -> QWidget:
        head = QFrame()
        head.setObjectName("modePageHead")
        lay = QHBoxLayout(head)
        lay.setContentsMargins(theme.SP_XL, theme.SP_LG, theme.SP_XL, theme.SP_LG)
        lay.setSpacing(theme.SP_SM)
        title = QLabel(MODE_LABELS[self.mode])
        title.setObjectName("modePageTitle")
        lay.addWidget(title)
        lay.addStretch(1)
        self.start_btn = QPushButton("开始运行")
        theme.make_primary(self.start_btn)
        self.stop_btn = QPushButton("停止")
        lay.addWidget(self.start_btn)
        lay.addWidget(self.stop_btn)
        return head

    def _build_cards(self) -> QWidget:
        # 内部容器必须随卡片撑开，否则真机窗口里卡片区一片空白
        # （离屏测试只断言卡片对象存在，测不出不可见——2026-09-11 实机验收发现）
        self.card_area = QScrollArea()
        self.card_area.setObjectName("cardArea")
        self.card_area.setWidgetResizable(True)
        self.card_area.setFrameShape(QFrame.Shape.NoFrame)
        self.card_widget = QWidget()
        self.card_layout = FlowLayout(self.card_widget,
                                      margin=theme.SP_XL,
                                      h_spacing=theme.SP_LG,
                                      v_spacing=theme.SP_LG)
        self.card_area.setWidget(self.card_widget)
        return self.card_area

    def _build_empty(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.addStretch(1)
        title = QLabel("暂无角色")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("请在 config.yaml 中配置角色，然后点击「刷新配置」")
        hint.setObjectName("emptyHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        lay.addSpacing(theme.SP_SM)
        lay.addWidget(hint)
        lay.addStretch(1)
        return box

    def _build_locked(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.addStretch(1)
        title = QLabel(f"{MODE_LABELS[self.mode]} · 开发中")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("该模式尚未开放")
        hint.setObjectName("emptyHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        lay.addSpacing(theme.SP_SM)
        lay.addWidget(hint)
        lay.addStretch(1)
        return box
