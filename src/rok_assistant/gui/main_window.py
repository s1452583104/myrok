from __future__ import annotations
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QScrollArea, QStatusBar
)
from PyQt6.QtCore import Qt, QTimer

class MainWindow(QMainWindow):
    def __init__(self, controller=None):
        super().__init__()
        self.setWindowTitle("rok-assistant")
        self.resize(1200, 800)
        self._controller = controller
        self._build_ui()
        self._setup_refresh_timer()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        # Top bar
        top = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["rally"])
        self.refresh_btn = QPushButton("Refresh Config")
        top.addWidget(self.start_btn)
        top.addWidget(self.stop_btn)
        top.addWidget(QLabel("Mode:"))
        top.addWidget(self.mode_combo)
        top.addWidget(self.refresh_btn)
        root.addLayout(top)
        # Account area
        self.account_area = QScrollArea()
        self.account_widget = QWidget()
        self.account_layout = QVBoxLayout(self.account_widget)
        self.account_area.setWidget(self.account_widget)
        root.addWidget(self.account_area)
        # Status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _setup_refresh_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._on_refresh)
        self._timer.start()

    def _on_refresh(self):
        # TODO: update thumbnails from workers
        pass

def main():
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
