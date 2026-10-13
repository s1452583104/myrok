"""自适应流式布局：子项按行排列，一行放不下就落行。

卡片区专用。重构前卡片用 `QVBoxLayout` 纵向堆叠，每张 220×430——2 台模拟器 ×
2 个角色就是 1720px 的长条，必须滚动才能看全；宽屏上又大片留白。流式布局让窗口
变宽自动多排一列，变窄自动收成一列。

实现取自 Qt 官方 FlowLayout 示例（BSD 许可）。
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin: int = 0,
                 h_spacing: int = 16, v_spacing: int = 16):
        super().__init__(parent)
        self._items: list = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    # ---- QLayout 必须实现的一组接口 ----
    def addItem(self, item):        # noqa: N802 - Qt 接口名
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):        # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):        # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        # 不主动抢占空间：卡片按自身 sizeHint 排布，多余空间留给右侧留白
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:   # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:   # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):    # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:    # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        """排一遍子项；test_only 时只算高度不落位（heightForWidth 用）。"""
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(),
                                  -margins.right(), -margins.bottom())
        x, y = effective.x(), effective.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            # 超出右边界且本行已有内容 → 换行（line_height > 0 保证一行至少放一个）
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


def clear_layout(layout) -> None:
    """移除布局里的全部项并 deleteLater 掉控件（重建卡片区用）。

    注意不能只 `takeAt`：控件不从父级删除就会留在窗口上继续显示。
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            # 先 hide 再脱父：setParent(None) 会把可见控件变成独立顶层窗口，
            # 在事件循环处理 deleteLater 之前闪一下
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


__all__ = ["FlowLayout", "clear_layout"]
