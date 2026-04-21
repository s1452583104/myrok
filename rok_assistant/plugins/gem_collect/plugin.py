from plugins.base_plugin import BasePlugin
from .strategy import GemCollectStrategy
from infrastructure import get_logger


class GemCollectPlugin(BasePlugin):
    """宝石采集插件"""
    
    def __init__(self, event_bus):
        super().__init__(event_bus)
        self._strategy: GemCollectStrategy = None
        self._logger = get_logger(self.__class__.__name__)
    
    def initialize(self) -> bool:
        """
        初始化插件
        
        Returns:
            bool: 是否初始化成功
        """
        try:
            self._strategy = GemCollectStrategy()
            self._logger.info(f"Gem collect plugin initialized: v{self.version}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to initialize gem collect plugin: {e}")
            return False
    
    def shutdown(self) -> None:
        """
        关闭插件
        """
        self._logger.info("Gem collect plugin shutdown")
    
    @property
    def name(self) -> str:
        """
        插件名称
        """
        return "gem_collect"
    
    @property
    def version(self) -> str:
        """
        插件版本
        """
        return "1.0.0"
    
    def get_strategy(self) -> GemCollectStrategy:
        """
        获取采集策略
        
        Returns:
            GemCollectStrategy: 采集策略
        """
        return self._strategy