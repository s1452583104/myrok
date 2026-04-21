import os
import importlib.util
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from infrastructure import get_logger
from .event_bus import EventBus


class IPlugin(ABC):
    """插件接口"""
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


class PluginManager:
    """插件管理器"""
    
    def __init__(self, event_bus: EventBus, search_paths: List[str] = None):
        self._event_bus = event_bus
        self._search_paths = search_paths or ["plugins"]
        self._plugins: Dict[str, IPlugin] = {}
        self._logger = get_logger(self.__class__.__name__)
    
    def load_plugins(self) -> int:
        """
        加载插件
        
        Returns:
            int: 加载的插件数量
        """
        loaded_count = 0
        
        for search_path in self._search_paths:
            if not os.path.exists(search_path):
                self._logger.warning(f"Plugin search path not found: {search_path}")
                continue
            
            for item in os.listdir(search_path):
                plugin_path = os.path.join(search_path, item)
                if os.path.isdir(plugin_path) and os.path.exists(os.path.join(plugin_path, "__init__.py")):
                    plugin = self._load_plugin(plugin_path)
                    if plugin:
                        self._plugins[plugin.name] = plugin
                        loaded_count += 1
        
        self._logger.info(f"Loaded {loaded_count} plugins")
        return loaded_count
    
    def _load_plugin(self, plugin_path: str) -> Optional[IPlugin]:
        """
        加载单个插件
        
        Args:
            plugin_path: 插件路径
            
        Returns:
            Optional[IPlugin]: 插件实例
        """
        try:
            # 导入插件模块
            plugin_name = os.path.basename(plugin_path)
            spec = importlib.util.spec_from_file_location(
                f"plugins.{plugin_name}.plugin",
                os.path.join(plugin_path, "plugin.py")
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # 查找插件类
                for name, obj in module.__dict__.items():
                    if isinstance(obj, type) and issubclass(obj, IPlugin) and obj != IPlugin:
                        plugin = obj(self._event_bus)
                        if plugin.initialize():
                            self._logger.info(f"Plugin loaded: {plugin.name} v{plugin.version}")
                            return plugin
        except Exception as e:
            self._logger.error(f"Failed to load plugin from {plugin_path}: {e}")
        
        return None
    
    def unload_plugins(self) -> None:
        """
        卸载所有插件
        """
        for plugin_name, plugin in self._plugins.items():
            try:
                plugin.shutdown()
                self._logger.info(f"Plugin unloaded: {plugin_name}")
            except Exception as e:
                self._logger.error(f"Failed to unload plugin {plugin_name}: {e}")
        self._plugins.clear()
    
    def get_plugin(self, name: str) -> Optional[IPlugin]:
        """
        获取插件
        
        Args:
            name: 插件名称
            
        Returns:
            Optional[IPlugin]: 插件实例
        """
        return self._plugins.get(name)
    
    def get_all_plugins(self) -> List[IPlugin]:
        """
        获取所有插件
        
        Returns:
            List[IPlugin]: 插件列表
        """
        return list(self._plugins.values())
    
    def reload_plugin(self, name: str) -> bool:
        """
        重新加载插件
        
        Args:
            name: 插件名称
            
        Returns:
            bool: 是否成功重载
        """
        if name in self._plugins:
            # 卸载旧插件
            try:
                self._plugins[name].shutdown()
                del self._plugins[name]
            except Exception as e:
                self._logger.error(f"Failed to unload plugin {name}: {e}")
            
            # 重新加载
            for search_path in self._search_paths:
                plugin_path = os.path.join(search_path, name)
                if os.path.exists(plugin_path):
                    plugin = self._load_plugin(plugin_path)
                    if plugin:
                        self._plugins[name] = plugin
                        return True
        return False