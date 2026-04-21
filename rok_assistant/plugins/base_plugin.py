from abc import ABC, abstractmethod
from coordination import EventBus
from business import ConfigManager


class BasePlugin(ABC):
    """插件基类"""
    
    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._config_manager: ConfigManager = None
    
    def set_config_manager(self, config_manager: ConfigManager):
        """
        设置配置管理器
        
        Args:
            config_manager: 配置管理器
        """
        self._config_manager = config_manager
    
    @abstractmethod
    def initialize(self) -> bool:
        """初始化插件"""
        pass
    
    @abstractmethod
    def shutdown(self) -> None:
        """关闭插件"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """插件名称"""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """插件版本"""
        pass
    
    def get_config(self, key: str, default=None):
        """
        获取配置
        
        Args:
            key: 配置键
            default: 默认值
            
        Returns:
            配置值
        """
        if self._config_manager:
            return self._config_manager.get(key, default)
        return default
    
    def set_config(self, key: str, value):
        """
        设置配置
        
        Args:
            key: 配置键
            value: 配置值
        """
        if self._config_manager:
            self._config_manager.set(key, value)