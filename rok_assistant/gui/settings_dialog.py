from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QGroupBox, QFileDialog
)
from PyQt6.QtCore import Qt
from business import ConfigManager
from infrastructure import get_logger


class SettingsDialog(QDialog):
    """设置对话框"""
    
    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self._config_manager = config_manager
        self._logger = get_logger(self.__class__.__name__)
        
        self.setWindowTitle("设置")
        self.setGeometry(200, 200, 600, 500)
        
        self._setup_ui()
        self._load_config()
    
    def _setup_ui(self):
        """设置UI"""
        main_layout = QVBoxLayout(self)
        
        # 游戏设置
        game_group = QGroupBox("游戏设置")
        game_layout = QVBoxLayout(game_group)
        
        # 窗口标题
        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("窗口标题:"))
        self.window_title_edit = QLineEdit()
        title_layout.addWidget(self.window_title_edit)
        game_layout.addLayout(title_layout)
        
        # 进程名称
        process_layout = QHBoxLayout()
        process_layout.addWidget(QLabel("进程名称:"))
        self.process_name_edit = QLineEdit()
        process_layout.addWidget(self.process_name_edit)
        game_layout.addLayout(process_layout)
        
        # 游戏路径
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("游戏路径:"))
        self.game_path_edit = QLineEdit()
        path_layout.addWidget(self.game_path_edit)
        self.game_path_browse = QPushButton("浏览...")
        self.game_path_browse.setFixedWidth(80)
        self.game_path_browse.clicked.connect(self._browse_game_path)
        path_layout.addWidget(self.game_path_browse)
        game_layout.addLayout(path_layout)
        
        main_layout.addWidget(game_group)
        
        # 模型设置
        model_group = QGroupBox("模型设置")
        model_layout = QVBoxLayout(model_group)
        
        # 模型路径
        model_path_layout = QHBoxLayout()
        model_path_layout.addWidget(QLabel("模型路径:"))
        self.model_path_edit = QLineEdit()
        model_path_layout.addWidget(self.model_path_edit)
        model_layout.addLayout(model_path_layout)
        
        # 置信度
        conf_layout = QHBoxLayout()
        conf_layout.addWidget(QLabel("置信度:"))
        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.1, 1.0)
        self.conf_spin.setSingleStep(0.1)
        conf_layout.addWidget(self.conf_spin)
        model_layout.addLayout(conf_layout)
        
        # 输入尺寸
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("输入尺寸:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(320, 1280)
        self.size_spin.setSingleStep(32)
        size_layout.addWidget(self.size_spin)
        model_layout.addLayout(size_layout)
        
        # 设备
        device_layout = QHBoxLayout()
        device_layout.addWidget(QLabel("设备:"))
        self.device_combo = QComboBox()
        self.device_combo.addItems(["cpu", "cuda"])
        device_layout.addWidget(self.device_combo)
        model_layout.addLayout(device_layout)
        
        main_layout.addWidget(model_group)
        
        # 安全设置
        safety_group = QGroupBox("安全设置")
        safety_layout = QVBoxLayout(safety_group)
        
        # 最小延迟
        min_delay_layout = QHBoxLayout()
        min_delay_layout.addWidget(QLabel("最小延迟 (秒):"))
        self.min_delay_spin = QDoubleSpinBox()
        self.min_delay_spin.setRange(0.01, 1.0)
        self.min_delay_spin.setSingleStep(0.01)
        min_delay_layout.addWidget(self.min_delay_spin)
        safety_layout.addLayout(min_delay_layout)
        
        # 最大延迟
        max_delay_layout = QHBoxLayout()
        max_delay_layout.addWidget(QLabel("最大延迟 (秒):"))
        self.max_delay_spin = QDoubleSpinBox()
        self.max_delay_spin.setRange(0.1, 2.0)
        self.max_delay_spin.setSingleStep(0.1)
        max_delay_layout.addWidget(self.max_delay_spin)
        safety_layout.addLayout(max_delay_layout)
        
        # 随机偏移
        offset_layout = QHBoxLayout()
        offset_layout.addWidget(QLabel("随机偏移 (像素):"))
        self.offset_spin = QSpinBox()
        self.offset_spin.setRange(0, 20)
        offset_layout.addWidget(self.offset_spin)
        safety_layout.addLayout(offset_layout)
        
        main_layout.addWidget(safety_group)
        
        # 自动化设置
        auto_group = QGroupBox("自动化设置")
        auto_layout = QVBoxLayout(auto_group)
        
        # 资源收集
        resource_layout = QHBoxLayout()
        self.resource_check = QCheckBox("资源自动收集")
        resource_layout.addWidget(self.resource_check)
        resource_layout.addWidget(QLabel("间隔 (秒):"))
        self.resource_interval_spin = QSpinBox()
        self.resource_interval_spin.setRange(60, 86400)
        resource_layout.addWidget(self.resource_interval_spin)
        auto_layout.addLayout(resource_layout)
        
        # 建筑升级
        building_layout = QHBoxLayout()
        self.building_check = QCheckBox("建筑自动升级")
        building_layout.addWidget(self.building_check)
        auto_layout.addLayout(building_layout)
        
        # 军队训练
        training_layout = QHBoxLayout()
        self.training_check = QCheckBox("部队自动训练")
        training_layout.addWidget(self.training_check)
        training_layout.addWidget(QLabel("数量:"))
        self.training_quantity_spin = QSpinBox()
        self.training_quantity_spin.setRange(100, 10000)
        training_layout.addWidget(self.training_quantity_spin)
        auto_layout.addLayout(training_layout)
        
        main_layout.addWidget(auto_group)
        
        # 按钮
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("保存")
        self.cancel_button = QPushButton("取消")
        
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        
        main_layout.addLayout(button_layout)
        
        # 连接信号
        self.save_button.clicked.connect(self._save_config)
        self.cancel_button.clicked.connect(self.reject)
    
    def _load_config(self):
        """加载配置"""
        # 游戏设置
        self.window_title_edit.setText(self._config_manager.get('window.title', '万国觉醒'))
        self.process_name_edit.setText(self._config_manager.get('window.process_name', 'RiseofKingdoms.exe'))
        self.game_path_edit.setText(self._config_manager.get('window.game_path', ''))
        
        # 模型设置
        self.model_path_edit.setText(self._config_manager.get('model.path', 'models/current/rok_detector.pt'))
        self.conf_spin.setValue(self._config_manager.get('model.confidence', 0.6))
        self.size_spin.setValue(self._config_manager.get('model.input_size', 640))
        self.device_combo.setCurrentText(self._config_manager.get('model.device', 'cpu'))
        
        # 安全设置
        self.min_delay_spin.setValue(self._config_manager.get('safety.min_delay', 0.05))
        self.max_delay_spin.setValue(self._config_manager.get('safety.max_delay', 0.3))
        self.offset_spin.setValue(self._config_manager.get('safety.random_offset', 5))
        
        # 自动化设置
        self.resource_check.setChecked(self._config_manager.get('automation.resource_collect.enabled', False))
        self.resource_interval_spin.setValue(self._config_manager.get('automation.resource_collect.interval', 36000))
        self.building_check.setChecked(self._config_manager.get('automation.building_upgrade.enabled', False))
        self.training_check.setChecked(self._config_manager.get('automation.army_training.enabled', False))
        self.training_quantity_spin.setValue(self._config_manager.get('automation.army_training.quantity', 1000))
    
    def _browse_game_path(self):
        """浏览游戏路径"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择游戏可执行文件",
            "",
            "可执行文件 (*.exe);;所有文件 (*.*)"
        )
        if file_path:
            self.game_path_edit.setText(file_path)
    
    def _save_config(self):
        """保存配置"""
        # 游戏设置
        self._config_manager.set('window.title', self.window_title_edit.text())
        self._config_manager.set('window.process_name', self.process_name_edit.text())
        self._config_manager.set('window.game_path', self.game_path_edit.text())
        
        # 模型设置
        self._config_manager.set('model.path', self.model_path_edit.text())
        self._config_manager.set('model.confidence', self.conf_spin.value())
        self._config_manager.set('model.input_size', self.size_spin.value())
        self._config_manager.set('model.device', self.device_combo.currentText())
        
        # 安全设置
        self._config_manager.set('safety.min_delay', self.min_delay_spin.value())
        self._config_manager.set('safety.max_delay', self.max_delay_spin.value())
        self._config_manager.set('safety.random_offset', self.offset_spin.value())
        
        # 自动化设置
        self._config_manager.set('automation.resource_collect.enabled', self.resource_check.isChecked())
        self._config_manager.set('automation.resource_collect.interval', self.resource_interval_spin.value())
        self._config_manager.set('automation.building_upgrade.enabled', self.building_check.isChecked())
        self._config_manager.set('automation.army_training.enabled', self.training_check.isChecked())
        self._config_manager.set('automation.army_training.quantity', self.training_quantity_spin.value())
        
        # 保存配置
        if self._config_manager.save_config():
            self._logger.info("Config saved successfully")
            self.accept()
        else:
            self._logger.error("Failed to save config")