from __future__ import annotations
from PyQt6.QtWidgets import QPlainTextEdit
from PyQt6.QtCore import Qt
from datetime import datetime


class LogPanel(QPlainTextEdit):
    """只读日志视图：环形裁剪 + 时间戳。

    外观（等宽字体、`#FAFAFA` 底、弱描边）由全局 QSS 的 `QPlainTextEdit#logView`
    规则给，不在这里写死色值——色值只从 `theme.py` 取。
    """

    def __init__(self, max_lines: int = 500):
        super().__init__()
        self.setObjectName("logView")
        self.setReadOnly(True)
        self._max_lines = max_lines

    def append_message(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.appendPlainText(f"[{ts}] {message}")
        # Trim
        doc = self.document()
        if doc.blockCount() > self._max_lines:
            cursor = self.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down,
                                cursor.MoveMode.KeepAnchor,
                                doc.blockCount() - self._max_lines)
            cursor.removeSelectedText()
            cursor.deleteChar()
