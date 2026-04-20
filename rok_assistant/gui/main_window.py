"""主窗口模块.

提供PyQt6图形界面, 包含:
- 游戏画面实时预览
- 检测结果显示
- 启动/停止控制
- 状态栏信息
"""

import sys
import time
from typing import Optional

import cv2
import numpy as np

from coordination.event_bus import (
    DetectionCompletedEvent,
    EngineStartedEvent,
    EngineStoppedEvent,
    EventBus,
    TaskCompletedEvent,
    TaskFailedEvent,
    WindowFoundEvent,
    WindowLostEvent,
)
from infrastructure.logger import get_logger

try:
    from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
    from PyQt6.QtGui import QImage, QPixmap, QFont
    from PyQt6.QtWidgets import (
        QApplication,
        QMainWindow,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QPushButton,
        QLabel,
        QTextEdit,
        QGroupBox,
        QStatusBar,
        QMessageBox,
    )

    _PYQT6_AVAILABLE = True
except ImportError:
    _PYQT6_AVAILABLE = False


class CaptureThread(QThread):
    """画面捕获线程.

    定期截取游戏画面并发射信号.
    """

    frame_ready = pyqtSignal(object)  # np.ndarray

    def __init__(self, capture_func, fps: int = 2):
        """初始化.

        Args:
            capture_func: 截图函数
            fps: 捕获帧率
        """
        super().__init__()
        self._capture_func = capture_func
        self._fps = fps
        self._running = False

    def run(self):
        """线程主循环."""
        self._running = True
        interval = 1.0 / self._fps if self._fps > 0 else 1.0

        while self._running:
            try:
                frame = self._capture_func()
                if frame is not None:
                    self.frame_ready.emit(frame)
            except Exception as e:
                pass  # 静默处理捕获错误
            self.msleep(int(interval * 1000))

    def stop(self):
        """停止线程."""
        self._running = False
        self.wait(2000)


class MainWindow(QMainWindow):
    """主窗口.

    功能:
    - 显示游戏画面实时预览
    - 显示检测结果叠加画面
    - 启动/停止自动化任务
    - 显示运行状态和日志

    使用示例:
        app = QApplication(sys.argv)
        window = MainWindow(event_bus, capture, detector, controller)
        window.show()
        sys.exit(app.exec())
    """

    def __init__(
        self,
        event_bus: EventBus,
        capture_func=None,
        detector=None,
        game_controller=None,
        task_runner=None,
    ):
        """初始化主窗口.

        Args:
            event_bus: 事件总线
            capture_func: 截图函数
            detector: YOLO检测器
            game_controller: 游戏控制器
            task_runner: 任务执行函数
        """
        super().__init__()
        self._event_bus = event_bus
        self._capture_func = capture_func
        self._detector = detector
        self._game_controller = game_controller
        self._task_runner = task_runner
        self._logger = get_logger(self.__class__.__name__)

        self._running = False
        self._capture_thread: Optional[CaptureThread] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_detection = None

        self._setup_ui()
        self._connect_events()

        self._logger.info("Main window initialized")

    def _setup_ui(self) -> None:
        """设置用户界面."""
        self.setWindowTitle("万国觉醒辅助工具 - ROK Assistant")
        self.setMinimumSize(900, 700)
        self.resize(1000, 750)

        # 中心部件
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # 左侧: 画面预览 + 控制按钮
        left_layout = QVBoxLayout()

        # 画面预览区域
        preview_group = QGroupBox("游戏画面")
        preview_layout = QVBoxLayout(preview_group)

        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(640, 480)
        self._preview_label.setStyleSheet(
            "background-color: #1a1a2e; border: 1px solid #333;"
        )
        self._preview_label.setText("等待游戏画面...")
        self._preview_label.setFont(QFont("Microsoft YaHei", 12))
        preview_layout.addWidget(self._preview_label)

        # 检测信息
        self._detection_info = QLabel("检测到: 0 个元素")
        self._detection_info.setFont(QFont("Microsoft YaHei", 9))
        preview_layout.addWidget(self._detection_info)

        left_layout.addWidget(preview_group)

        # 控制按钮
        control_group = QGroupBox("控制面板")
        control_layout = QHBoxLayout(control_group)

        self._start_btn = QPushButton("▶ 开始")
        self._start_btn.setMinimumHeight(40)
        self._start_btn.setFont(QFont("Microsoft YaHei", 11))
        self._start_btn.clicked.connect(self._on_start)

        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.setMinimumHeight(40)
        self._stop_btn.setFont(QFont("Microsoft YaHei", 11))
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)

        self._detect_btn = QPushButton("🔍 检测")
        self._detect_btn.setMinimumHeight(40)
        self._detect_btn.setFont(QFont("Microsoft YaHei", 11))
        self._detect_btn.clicked.connect(self._on_detect)

        control_layout.addWidget(self._start_btn)
        control_layout.addWidget(self._stop_btn)
        control_layout.addWidget(self._detect_btn)

        left_layout.addWidget(control_group)
        main_layout.addLayout(left_layout, stretch=2)

        # 右侧: 检测结果 + 日志
        right_layout = QVBoxLayout()

        # 检测结果
        result_group = QGroupBox("检测结果")
        result_layout = QVBoxLayout(result_group)
        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setMaximumHeight(150)
        result_layout.addWidget(self._result_text)
        right_layout.addWidget(result_group)

        # 任务状态
        status_group = QGroupBox("任务状态")
        status_layout = QVBoxLayout(status_group)
        self._task_status = QLabel("状态: 空闲")
        self._task_status.setFont(QFont("Microsoft YaHei", 10))
        status_layout.addWidget(self._task_status)

        self._task_count = QLabel("完成任务: 0")
        self._task_count.setFont(QFont("Microsoft YaHei", 9))
        status_layout.addWidget(self._task_count)

        self._error_count = QLabel("失败任务: 0")
        self._error_count.setFont(QFont("Microsoft YaHei", 9))
        status_layout.addWidget(self._error_count)

        right_layout.addWidget(status_group)

        # 日志
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_group)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Consolas", 8))
        log_layout.addWidget(self._log_text)
        right_layout.addWidget(log_group, stretch=1)

        main_layout.addLayout(right_layout, stretch=1)

        # 状态栏
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("就绪")

        # 任务统计
        self._completed_tasks = 0
        self._failed_tasks = 0

    def _connect_events(self) -> None:
        """连接事件总线."""
        self._event_bus.subscribe("engine.started", self._on_engine_started)
        self._event_bus.subscribe("engine.stopped", self._on_engine_stopped)
        self._event_bus.subscribe("engine.error", self._on_engine_error)
        self._event_bus.subscribe("task.completed", self._on_task_completed)
        self._event_bus.subscribe("task.failed", self._on_task_failed)
        self._event_bus.subscribe("window.found", self._on_window_found)
        self._event_bus.subscribe("window.lost", self._on_window_lost)
        self._event_bus.subscribe(
            "detection.completed", self._on_detection_completed
        )

    # ========== 事件处理 ==========

    def _on_engine_started(self, event) -> None:
        self._append_log("引擎已启动")
        self._status_bar.showMessage("运行中")

    def _on_engine_stopped(self, event) -> None:
        self._append_log("引擎已停止")
        self._status_bar.showMessage("已停止")

    def _on_engine_error(self, event) -> None:
        msg = getattr(event, "error_message", "未知错误")
        self._append_log(f"引擎错误: {msg}")
        self._status_bar.showMessage(f"错误: {msg}")

    def _on_task_completed(self, event) -> None:
        self._completed_tasks += 1
        self._task_count.setText(f"完成任务: {self._completed_tasks}")
        self._task_status.setText("状态: 空闲")
        self._append_log(f"任务完成: {event.task_id}")

    def _on_task_failed(self, event) -> None:
        self._failed_tasks += 1
        self._error_count.setText(f"失败任务: {self._failed_tasks}")
        self._task_status.setText("状态: 错误")
        self._append_log(f"任务失败: {event.task_id} - {event.error}")

    def _on_window_found(self, event) -> None:
        self._append_log("游戏窗口已找到")
        self._status_bar.showMessage("游戏窗口已连接")

    def _on_window_lost(self, event) -> None:
        self._append_log("游戏窗口丢失!")
        self._status_bar.showMessage("警告: 游戏窗口丢失")

    def _on_detection_completed(self, event) -> None:
        result = getattr(event, "result", None)
        if result is not None:
            self._latest_detection = result
            self._detection_info.setText(
                f"检测到: {result.element_count} 个元素"
            )
            self._update_detection_text(result)

    # ========== 按钮处理 ==========

    def _on_start(self) -> None:
        """开始按钮点击."""
        self._running = True
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._append_log("开始自动化...")

        # 启动捕获线程
        if self._capture_func is not None:
            self._capture_thread = CaptureThread(self._capture_func, fps=2)
            self._capture_thread.frame_ready.connect(self._update_preview)
            self._capture_thread.start()

        # 启动任务
        if self._task_runner is not None:
            try:
                self._task_runner()
            except Exception as e:
                self._append_log(f"启动任务失败: {e}")
                self._on_stop()

        self._event_bus.publish(EngineStartedEvent())

    def _on_stop(self) -> None:
        """停止按钮点击."""
        self._running = False
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._append_log("停止自动化...")

        if self._capture_thread is not None:
            self._capture_thread.stop()
            self._capture_thread = None

        self._event_bus.publish(EngineStoppedEvent())

    def _on_detect(self) -> None:
        """手动检测按钮点击."""
        if self._detector is None or self._capture_func is None:
            self._append_log("检测器或捕获功能不可用")
            return

        try:
            frame = self._capture_func()
            if frame is None:
                self._append_log("截图失败")
                return

            result = self._detector.detect(frame)
            self._event_bus.publish(
                DetectionCompletedEvent(result=result)
            )
            self._append_log(
                f"检测完成: {result.element_count} 个元素"
            )

            # 显示结果
            self._update_preview(frame)

        except Exception as e:
            self._append_log(f"检测错误: {e}")

    # ========== 显示更新 ==========

    def _update_preview(self, frame: np.ndarray) -> None:
        """更新画面预览.

        Args:
            frame: BGR格式图像
        """
        self._latest_frame = frame

        display_frame = frame.copy()

        # 叠加检测框
        if self._latest_detection is not None:
            display_frame = self._draw_detections(
                display_frame, self._latest_detection
            )

        # 转换为QPixmap
        pixmap = self._numpy_to_pixmap(display_frame)
        if pixmap is not None:
            # 适配label大小
            scaled = pixmap.scaled(
                self._preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._preview_label.setPixmap(scaled)

    def _draw_detections(
        self, frame: np.ndarray, result
    ) -> np.ndarray:
        """在画面上叠加检测框.

        Args:
            frame: BGR格式图像
            result: DetectionResult

        Returns:
            叠加了检测框的图像
        """
        for element in result.elements:
            bbox = element.bbox
            color = (0, 255, 0)  # 绿色
            cv2.rectangle(
                frame,
                (bbox.x1, bbox.y1),
                (bbox.x2, bbox.y2),
                color,
                2,
            )

            # 标签
            label = f"{element.class_name} {element.confidence:.2f}"
            cv2.putText(
                frame,
                label,
                (bbox.x1, bbox.y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
            )

        return frame

    def _update_detection_text(self, result) -> None:
        """更新检测结果文本.

        Args:
            result: DetectionResult
        """
        lines = []
        for elem in result.elements:
            lines.append(
                f"* {elem.class_name} (置信度: {elem.confidence:.2f}) "
                f"@ ({elem.center[0]}, {elem.center[1]})"
            )
        if not lines:
            lines.append("未检测到元素")
        self._result_text.setText("\n".join(lines))

    def _numpy_to_pixmap(self, frame: np.ndarray) -> Optional[QPixmap]:
        """将numpy数组转换为QPixmap.

        Args:
            frame: BGR格式图像

        Returns:
            QPixmap对象
        """
        if frame is None or frame.size == 0:
            return None

        try:
            height, width = frame.shape[:2]
            if len(frame.shape) == 3:
                bytes_per_line = 3 * width
                q_image = QImage(
                    frame.data,
                    width,
                    height,
                    bytes_per_line,
                    QImage.Format.Format_BGR888,
                )
            else:
                bytes_per_line = width
                q_image = QImage(
                    frame.data,
                    width,
                    height,
                    bytes_per_line,
                    QImage.Format.Format_Grayscale8,
                )
            return QPixmap.fromImage(q_image)
        except Exception as e:
            self._logger.error(f"Failed to convert frame to pixmap: {e}")
            return None

    def _append_log(self, message: str) -> None:
        """追加日志.

        Args:
            message: 日志消息
        """
        timestamp = time.strftime("%H:%M:%S")
        self._log_text.append(f"[{timestamp}] {message}")
        # 自动滚动到底部
        scrollbar = self._log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event) -> None:
        """窗口关闭事件."""
        self._on_stop()
        self._logger.info("Main window closed")
        event.accept()
