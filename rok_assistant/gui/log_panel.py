from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QComboBox, QSpinBox
)
from PyQt6.QtCore import Qt
import logging
from infrastructure import get_logger


class LogPanel(QDialog):
    """日志面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._logger = get_logger(self.__class__.__name__)
        
        self.setWindowTitle("日志面板")
        self.setGeometry(400, 200, 800, 500)
        
        self._setup_ui()
        self._load_log()
    
    def _setup_ui(self):
        """设置UI"""
        main_layout = QVBoxLayout(self)
        
        # 顶部控制栏
        control_layout = QHBoxLayout()
        
        self.level_combo = QComboBox()
        self.level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.level_combo.setCurrentText("INFO")
        
        self.refresh_button = QPushButton("刷新")
        self.clear_button = QPushButton("清空")
        self.save_button = QPushButton("保存")
        
        control_layout.addWidget(QLabel("日志级别:"))
        control_layout.addWidget(self.level_combo)
        control_layout.addStretch()
        control_layout.addWidget(self.refresh_button)
        control_layout.addWidget(self.clear_button)
        control_layout.addWidget(self.save_button)
        
        main_layout.addLayout(control_layout)
        
        # 日志内容
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(400)
        main_layout.addWidget(self.log_text)
        
        # 连接信号
        self.refresh_button.clicked.connect(self._load_log)
        self.clear_button.clicked.connect(self._clear_log)
        self.save_button.clicked.connect(self._save_log)
        self.level_combo.currentTextChanged.connect(self._filter_log)
    
    def _load_log(self):
        """加载日志"""
        try:
            log_file = "logs/rok_assistant.log"
            with open(log_file, 'r', encoding='utf-8') as f:
                log_content = f.read()
            self.log_text.setText(log_content)
            self._logger.info("Log loaded successfully")
        except Exception as e:
            self._logger.error(f"Failed to load log: {e}")
            self.log_text.setText(f"Failed to load log: {e}")
    
    def _clear_log(self):
        """清空日志"""
        self.log_text.clear()
    
    def _save_log(self):
        """保存日志"""
        try:
            import datetime
            import os
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            save_dir = "logs/archives"
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
            
            filename = os.path.join(save_dir, f"log_{timestamp}.txt")
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(self.log_text.toPlainText())
            
            self._logger.info(f"Log saved to {filename}")
        except Exception as e:
            self._logger.error(f"Failed to save log: {e}")
    
    def _filter_log(self):
        """过滤日志"""
        # 这里可以实现日志过滤功能
        pass