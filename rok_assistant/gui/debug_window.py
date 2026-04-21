from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
import cv2
import numpy as np
from business import DetectionService
from infrastructure import get_logger


class DebugWindow(QDialog):
    """调试窗口"""
    
    def __init__(self, detection_service: DetectionService, parent=None):
        super().__init__(parent)
        self._detection_service = detection_service
        self._logger = get_logger(self.__class__.__name__)
        
        self.setWindowTitle("调试窗口")
        self.setGeometry(300, 300, 800, 600)
        
        self._setup_ui()
        self._setup_timer()
    
    def _setup_ui(self):
        """设置UI"""
        main_layout = QVBoxLayout(self)
        
        # 顶部控制栏
        control_layout = QHBoxLayout()
        
        self.start_button = QPushButton("开始")
        self.stop_button = QPushButton("停止")
        self.capture_button = QPushButton("截图")
        
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.capture_button)
        control_layout.addStretch()
        
        main_layout.addLayout(control_layout)
        
        # 中间预览区域
        self.preview_label = QLabel("预览画面")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(780, 400)
        main_layout.addWidget(self.preview_label)
        
        # 底部调试信息
        debug_group = QHBoxLayout()
        
        # 左侧检测信息
        self.detection_info = QTextEdit()
        self.detection_info.setReadOnly(True)
        self.detection_info.setMinimumWidth(380)
        debug_group.addWidget(QLabel("检测信息:"))
        debug_group.addWidget(self.detection_info)
        
        # 右侧控制选项
        control_group = QVBoxLayout()
        
        self.overlay_check = QCheckBox("显示检测框")
        self.overlay_check.setChecked(True)
        control_group.addWidget(self.overlay_check)
        
        self.class_combo = QComboBox()
        self.class_combo.addItem("所有类别")
        # 这里可以动态添加类别
        control_group.addWidget(QLabel("过滤类别:"))
        control_group.addWidget(self.class_combo)
        
        debug_group.addLayout(control_group)
        
        main_layout.addLayout(debug_group)
        
        # 连接信号
        self.start_button.clicked.connect(self._start_preview)
        self.stop_button.clicked.connect(self._stop_preview)
        self.capture_button.clicked.connect(self._capture_image)
    
    def _setup_timer(self):
        """设置定时器"""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_preview)
        self._running = False
    
    def _start_preview(self):
        """开始预览"""
        self._running = True
        self._timer.start(50)  # 20fps
        self._logger.info("Debug preview started")
    
    def _stop_preview(self):
        """停止预览"""
        self._running = False
        self._timer.stop()
        self._logger.info("Debug preview stopped")
    
    def _update_preview(self):
        """更新预览"""
        if not self._running:
            return
        
        # 捕获画面
        image = self._detection_service.get_window_capture().capture_background()
        if image is None:
            return
        
        # 执行检测
        result = self._detection_service.detect()
        
        # 绘制检测结果
        if result and self.overlay_check.isChecked():
            for elem in result.elements:
                x1, y1, x2, y2 = elem.bbox.x1, elem.bbox.y1, elem.bbox.x2, elem.bbox.y2
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label = f"{elem.class_name}: {elem.confidence:.2f}"
                cv2.putText(image, label, (x1, y1 - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        # 更新预览
        self._display_image(image)
        
        # 更新检测信息
        if result:
            text = f"检测到 {len(result.elements)} 个元素\n\n"
            for elem in result.elements:
                text += f"{elem.class_name}: ({elem.center[0]}, {elem.center[1]}) - {elem.confidence:.2f}\n"
            self.detection_info.setText(text)
    
    def _display_image(self, image):
        """显示图像"""
        # 转换为Qt图像格式
        height, width, channel = image.shape
        bytes_per_line = 3 * width
        q_image = QImage(image.data, width, height, bytes_per_line, QImage.Format.Format_BGR888)
        pixmap = QPixmap.fromImage(q_image)
        
        # 调整大小以适应标签
        scaled_pixmap = pixmap.scaled(
            self.preview_label.width(),
            self.preview_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio
        )
        
        self.preview_label.setPixmap(scaled_pixmap)
    
    def _capture_image(self):
        """截图"""
        image = self._detection_service.get_window_capture().capture_background()
        if image is not None:
            import datetime
            import os
            
            # 保存截图
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            save_dir = "screenshots"
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
            
            filename = os.path.join(save_dir, f"screenshot_{timestamp}.png")
            cv2.imwrite(filename, image)
            
            self._logger.info(f"Screenshot saved to {filename}")