#!/usr/bin/env python3
"""测试 PyQt6 GUI 是否正常工作."""

import sys
from PyQt6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout

def main():
    """运行简单的GUI测试."""
    app = QApplication(sys.argv)
    
    # 创建一个简单窗口
    window = QWidget()
    window.setWindowTitle("PyQt6 测试窗口")
    window.resize(400, 300)
    
    layout = QVBoxLayout(window)
    label = QLabel("如果你看到这个窗口，说明 PyQt6 工作正常！")
    label.setStyleSheet("font-size: 16px; padding: 20px;")
    layout.addWidget(label)
    
    window.show()
    
    print("GUI 窗口已显示...")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
