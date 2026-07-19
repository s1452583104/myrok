from __future__ import annotations
from PyQt6.QtWidgets import QPlainTextEdit
from PyQt6.QtCore import Qt
from datetime import datetime

class LogPanel(QPlainTextEdit):
    def __init__(self, max_lines: int = 500):
        super().__init__()
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
