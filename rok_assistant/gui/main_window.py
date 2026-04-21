import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QStatusBar, QSplitter, QTextEdit, QTabWidget, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from business import ConfigManager, DetectionService, GameController, AutomationEngine
from coordination import EventBus, TaskScheduler, PluginManager
from infrastructure import get_logger
from .settings_dialog import SettingsDialog
from .log_panel import LogPanel
from .debug_window import DebugWindow


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        detection_service: DetectionService,
        game_controller: GameController,
        automation_engine: AutomationEngine,
        task_scheduler: TaskScheduler,
        plugin_manager: PluginManager
    ):
        super().__init__()
        self._config_manager = config_manager
        self._event_bus = event_bus
        self._detection_service = detection_service
        self._game_controller = game_controller
        self._automation_engine = automation_engine
        self._task_scheduler = task_scheduler
        self._plugin_manager = plugin_manager
        self._logger = get_logger(self.__class__.__name__)
        
        self._setup_ui()
        self._setup_timer()
        self._connect_signals()
    
    def _setup_ui(self):
        """设置UI"""
        self.setWindowTitle("万国觉醒辅助工具")
        self.setGeometry(100, 100, 1000, 700)
        
        # 主布局
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # 顶部状态信息
        status_frame = QFrame()
        status_layout = QHBoxLayout(status_frame)
        
        self.game_status_label = QLabel("游戏状态: 未连接")
        self.detection_label = QLabel("检测到: 0个元素")
        self.task_label = QLabel("任务: 就绪")
        
        status_layout.addWidget(self.game_status_label)
        status_layout.addWidget(self.detection_label)
        status_layout.addWidget(self.task_label)
        status_layout.addStretch()
        
        main_layout.addWidget(status_frame)
        
        # 中间分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧检测预览
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        self.preview_label = QLabel("游戏窗口预览")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(600, 400)
        left_layout.addWidget(self.preview_label)
        
        # 检测结果
        self.detection_results = QTextEdit()
        self.detection_results.setReadOnly(True)
        self.detection_results.setMinimumHeight(150)
        left_layout.addWidget(QLabel("检测结果:"))
        left_layout.addWidget(self.detection_results)
        
        splitter.addWidget(left_widget)
        
        # 右侧设置
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        self.tab_widget = QTabWidget()
        
        # 自动化设置
        auto_tab = QWidget()
        auto_layout = QVBoxLayout(auto_tab)
        
        self.start_button = QPushButton("开始")
        self.stop_button = QPushButton("停止")
        self.refresh_button = QPushButton("刷新检测")
        
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        button_layout.addWidget(self.refresh_button)
        
        auto_layout.addLayout(button_layout)
        
        # 插件列表
        plugins_tab = QWidget()
        plugins_layout = QVBoxLayout(plugins_tab)
        
        self.plugins_list = QTextEdit()
        self.plugins_list.setReadOnly(True)
        plugins_layout.addWidget(QLabel("已加载插件:"))
        plugins_layout.addWidget(self.plugins_list)
        
        self.tab_widget.addTab(auto_tab, "自动化")
        self.tab_widget.addTab(plugins_tab, "插件")
        
        right_layout.addWidget(self.tab_widget)
        
        splitter.addWidget(right_widget)
        splitter.setSizes([700, 300])
        
        main_layout.addWidget(splitter)
        
        # 底部按钮栏
        bottom_frame = QFrame()
        bottom_layout = QHBoxLayout(bottom_frame)
        
        self.log_button = QPushButton("日志")
        self.settings_button = QPushButton("设置")
        
        bottom_layout.addWidget(self.log_button)
        bottom_layout.addWidget(self.settings_button)
        bottom_layout.addStretch()
        
        main_layout.addWidget(bottom_frame)
        
        self.setCentralWidget(central_widget)
    
    def _setup_timer(self):
        """设置定时器"""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_status)
        self._timer.start(1000)  # 1秒更新一次
    
    def _connect_signals(self):
        """连接信号"""
        self.start_button.clicked.connect(self._start_automation)
        self.stop_button.clicked.connect(self._stop_automation)
        self.refresh_button.clicked.connect(self._refresh_detection)
        self.log_button.clicked.connect(self._show_log)
        self.settings_button.clicked.connect(self._show_settings)
    
    def _update_status(self):
        """更新状态"""
        # 更新游戏状态
        if self._detection_service.get_window_capture():
            self.game_status_label.setText("游戏状态: 已连接")
        else:
            self.game_status_label.setText("游戏状态: 未连接")
        
        # 更新引擎状态
        state = self._automation_engine.state
        self.task_label.setText(f"任务: {state.value}")
    
    def _start_automation(self):
        """开始自动化"""
        self._automation_engine.start()
        self._task_scheduler.start()
        self._logger.info("Automation started")
    
    def _stop_automation(self):
        """停止自动化"""
        self._automation_engine.stop()
        self._task_scheduler.stop()
        self._logger.info("Automation stopped")
    
    def _refresh_detection(self):
        """刷新检测"""
        result = self._detection_service.detect()
        if result:
            self.detection_label.setText(f"检测到: {len(result.elements)}个元素")
            
            # 更新检测结果
            text = ""
            for elem in result.elements:
                text += f"* {elem.class_name} (conf: {elem.confidence:.2f}) at ({elem.center[0]}, {elem.center[1]})\n"
            self.detection_results.setText(text)
    
    def _show_log(self):
        """显示日志"""
        log_file = self._config_manager.get('logging.file', 'logs/rok_assistant.log')
        self._log_window = LogPanel(log_file)
        self._log_window.show()
    
    def _show_settings(self):
        """显示设置"""
        self._settings_dialog = SettingsDialog(self._config_manager, self)
        self._settings_dialog.exec()
    
    def update_plugins_list(self):
        """更新插件列表"""
        plugins = self._plugin_manager.get_all_plugins()
        text = ""
        for plugin in plugins:
            text += f"- {plugin.name} v{plugin.version}\n"
        self.plugins_list.setText(text)
    
    def closeEvent(self, event):
        """关闭事件"""
        self._automation_engine.stop()
        self._task_scheduler.stop()
        self._plugin_manager.unload_plugins()
        event.accept()