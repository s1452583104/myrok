import os
import yaml
from typing import Dict, Any, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from infrastructure import get_logger, ConfigError
from coordination import EventBus, ConfigChangedEvent


class ConfigChangeHandler(FileSystemEventHandler):
    """配置文件变更处理器"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    def on_modified(self, event):
        """文件修改事件"""
        if not event.is_directory and event.src_path == self.config_manager._config_file:
            self.config_manager._logger.info(f"Config file changed: {event.src_path}")
            self.config_manager.load_config()


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_file: str, event_bus: EventBus):
        """
        Args:
            config_file: 配置文件路径
            event_bus: 事件总线
        """
        self._config_file = config_file
        self._event_bus = event_bus
        self._config: Dict[str, Any] = {}
        self._logger = get_logger(self.__class__.__name__)
        self._observer: Optional[Observer] = None
    
    def load_config(self) -> bool:
        """
        加载配置
        
        Returns:
            bool: 是否加载成功
        """
        try:
            if not os.path.exists(self._config_file):
                self._logger.error(f"Config file not found: {self._config_file}")
                raise ConfigError(f"Config file not found: {self._config_file}")
            
            with open(self._config_file, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
            
            self._logger.info(f"Config loaded from {self._config_file}")
            
            # 发布配置变更事件
            self._event_bus.publish(ConfigChangedEvent(self._config))
            
            return True
        except Exception as e:
            self._logger.error(f"Failed to load config: {e}")
            raise ConfigError(f"Failed to load config: {e}")
    
    def save_config(self) -> bool:
        """
        保存配置
        
        Returns:
            bool: 是否保存成功
        """
        try:
            # 确保目录存在
            config_dir = os.path.dirname(self._config_file)
            if config_dir and not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)
            
            with open(self._config_file, 'w', encoding='utf-8') as f:
                yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True, indent=2)
            
            self._logger.info(f"Config saved to {self._config_file}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to save config: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键（支持点号分隔的路径）
            default: 默认值
            
        Returns:
            Any: 配置值
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """
        设置配置值
        
        Args:
            key: 配置键（支持点号分隔的路径）
            value: 配置值
        """
        keys = key.split('.')
        config = self._config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
    
    def enable_watch(self) -> None:
        """
        启用配置文件监控
        """
        if self._observer:
            self._observer.stop()
        
        self._observer = Observer()
        event_handler = ConfigChangeHandler(self)
        config_dir = os.path.dirname(self._config_file)
        self._observer.schedule(event_handler, config_dir, recursive=False)
        self._observer.start()
        self._logger.info(f"Config watch enabled for {self._config_file}")
    
    def disable_watch(self) -> None:
        """
        禁用配置文件监控
        """
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            self._logger.info("Config watch disabled")
    
    @property
    def config(self) -> Dict[str, Any]:
        """配置字典"""
        return self._config
    
    def validate_config(self) -> bool:
        """
        验证配置
        
        Returns:
            bool: 配置是否有效
        """
        # 基本配置验证
        required_sections = ['window', 'model', 'safety', 'automation']
        
        for section in required_sections:
            if section not in self._config:
                self._logger.error(f"Missing required section: {section}")
                return False
        
        # 窗口配置验证
        if 'title' not in self._config.get('window', {}):
            self._logger.error("Missing window title")
            return False
        
        # 模型配置验证
        if 'path' not in self._config.get('model', {}):
            self._logger.error("Missing model path")
            return False
        
        return True