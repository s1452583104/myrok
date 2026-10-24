from __future__ import annotations

from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal

from . import theme
from .flow_layout import FlowLayout
from ..infra.config import AppMode, IMPLEMENTED_MODES, MODE_LABELS

# 统计条高度：一条横条，不占地方。数字与名称同一行，省掉「标签在上、数值
# 在下」的两行版式——后者更像仪表盘，但每张卡都要多付一份高度。
_STATS_H = 2 * theme.SP_XL


class ModePage(QWidget):
    """一个模式一页：页头（模式名 + 显示模式开关 + 开始/停止）+ 内容三态。

    内容用 QStackedWidget 的固定索引，让 _sync_ui_state 只做「选哪一页」：
      0 = 卡片流式网格（有角色）
      1 = 空态占位（未加载到角色）
      2 = 「该模式尚未开放」（未实现的模式）
    """

    CARD, EMPTY, LOCKED = 0, 1, 2

    # 用户点了页头的「文字模式 / 图文模式」。**只在用户点击时发**：主窗口收到
    # 它会去改写 config.yaml，而启动时读配置那条路径也调 set_view_mode——
    # 那里再发一次就成了「读配置→发信号→写配置」的空转。
    view_mode_changed = pyqtSignal(str)

    def __init__(self, mode: AppMode):
        super().__init__()
        self.mode = mode
        self.implemented = mode in IMPLEMENTED_MODES
        self._view_mode = "image"

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
        lay.addWidget(self._build_view_switch())
        lay.addSpacing(theme.SP_SM)
        self.start_btn = QPushButton("开始运行")
        theme.make_primary(self.start_btn)
        self.stop_btn = QPushButton("停止")
        lay.addWidget(self.start_btn)
        lay.addWidget(self.stop_btn)
        return head

    def _build_view_switch(self) -> QWidget:
        """文字模式 / 图文模式二选一。

        QButtonGroup 独占：两个都亮着等于没有开关。
        """
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.text_btn = QPushButton("文字模式")
        self.image_btn = QPushButton("图文模式")
        for btn, mode in ((self.text_btn, "text"), (self.image_btn, "image")):
            theme.make_segment(btn)
            btn.clicked.connect(
                lambda _checked=False, m=mode: self._on_segment_clicked(m))
            lay.addWidget(btn)
        self._segment_group = QButtonGroup(self)
        self._segment_group.setExclusive(True)
        self._segment_group.addButton(self.text_btn)
        self._segment_group.addButton(self.image_btn)
        self.image_btn.setChecked(True)     # 与 self._view_mode 初值一致
        return box

    # ---------------- 显示模式 ----------------
    def view_mode(self) -> str:
        return self._view_mode

    def set_view_mode(self, mode: str) -> None:
        """按代码设显示模式，**不发信号**（见 view_mode_changed 的注释）。"""
        self._view_mode = mode
        # setChecked 不发 clicked，所以这里不会被 _on_segment_clicked 收走
        (self.text_btn if mode == "text" else self.image_btn).setChecked(True)

    def _on_segment_clicked(self, mode: str) -> None:
        # 再点已选中项不重发：主窗口收到信号要落盘，重复点不该反复写文件
        if mode == self._view_mode:
            return
        self._view_mode = mode
        self.view_mode_changed.emit(mode)

    # ---------------- 统计条 ----------------
    def set_stats(self, stats: dict) -> None:
        """刷新卡片区上方的汇总读数。

        缺字段按 0：启动中/未运行时读数可能只有一部分（见 controller.stats）。
        状态色只承载语义——0 次失败是中性灰，不是红色。
        """
        ok = stats.get("ok", 0)
        target = stats.get("target", 0)
        failed = stats.get("failed", 0)
        env = stats.get("env", 0)
        self.stat_ok.setText(f"{ok}/{target}")
        self.stat_failed.setText(str(failed))
        self.stat_env.setText(str(env))
        self.stat_fills.setText(str(stats.get("fills", 0)))
        self._paint_stat(self.stat_ok, "primary")
        self._paint_stat(self.stat_failed, "error" if failed else "muted")
        self._paint_stat(self.stat_env, "warning" if env else "muted")
        self._paint_stat(self.stat_fills, "default")

    @staticmethod
    def _paint_stat(label: QLabel, kind: str) -> None:
        label.setStyleSheet(theme.stat_value_style(kind))

    def _build_cards(self) -> QWidget:
        # 统计条与卡片区同属 CARD 这一页：空态/未开放页不该顶着一条全 0 的战绩
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_stats_bar())

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
        lay.addWidget(self.card_area, 1)
        return box

    def _build_stats_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("statsBar")
        bar.setFixedHeight(_STATS_H)
        lay = QHBoxLayout(bar)
        # 左右对齐卡片区的 SP_XL 边距，统计数字与卡片左边缘同一条竖线
        lay.setContentsMargins(theme.SP_XL, 0, theme.SP_XL, 0)
        lay.setSpacing(theme.SP_XL)
        self.stat_ok, item = self._stat_item("完成")
        lay.addWidget(item)
        self.stat_failed, item = self._stat_item("失败")
        lay.addWidget(item)
        self.stat_env, item = self._stat_item("中止")
        lay.addWidget(item)
        self.stat_fills, item = self._stat_item("填兵")
        lay.addWidget(item)
        lay.addStretch(1)
        self.stats_bar = bar
        self.set_stats({})
        return bar

    @staticmethod
    def _stat_item(name: str) -> tuple[QLabel, QWidget]:
        """一个统计项：数值在前、名称在后 —— 用户扫的是数字，名称是注解。"""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP_XS + 2)
        value = QLabel("0")
        value.setObjectName("statsValue")
        label = QLabel(name)
        label.setObjectName("statsName")
        lay.addWidget(value)
        lay.addWidget(label)
        return value, box

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
