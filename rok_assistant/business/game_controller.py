from typing import Optional, Tuple
import time
import random
from core import InputController, WindowCapture
from infrastructure import get_logger
from .config_manager import ConfigManager


class GameController:
    """游戏控制器"""
    
    def __init__(self, config_manager: ConfigManager):
        """
        Args:
            config_manager: 配置管理器
        """
        self._config_manager = config_manager
        self._window_capture: Optional[WindowCapture] = None
        self._input_controller: Optional[InputController] = None
        self._last_action_time: float = 0
        self._action_count: int = 0
        self._logger = get_logger(self.__class__.__name__)
    
    def initialize(self, window_capture: WindowCapture) -> bool:
        """
        初始化游戏控制器
        
        Args:
            window_capture: 窗口捕获实例
            
        Returns:
            bool: 是否初始化成功
        """
        try:
            self._window_capture = window_capture
            
            # 获取安全配置
            min_delay = self._config_manager.get('safety.min_delay', 0.05)
            max_delay = self._config_manager.get('safety.max_delay', 0.3)
            random_offset = self._config_manager.get('safety.random_offset', 5)
            
            # 创建输入控制器
            self._input_controller = InputController.create_controller(
                mode="foreground",
                min_delay=min_delay,
                max_delay=max_delay,
                random_offset=random_offset
            )
            
            self._logger.info("Game controller initialized successfully")
            return True
        except Exception as e:
            self._logger.error(f"Failed to initialize game controller: {e}")
            return False
    
    def click(self, x: int, y: int, button: str = "left") -> bool:
        """
        模拟点击
        
        Args:
            x: x坐标
            y: y坐标
            button: 按钮类型
            
        Returns:
            bool: 是否成功
        """
        try:
            # 检查操作频率
            if not self._check_action_rate():
                return False
            
            self._input_controller.click(x, y, button)
            self._record_action()
            return True
        except Exception as e:
            self._logger.error(f"Click failed: {e}")
            return False
    
    def click_element(self, element_position: Tuple[int, int], button: str = "left") -> bool:
        """
        点击元素
        
        Args:
            element_position: 元素位置
            button: 按钮类型
            
        Returns:
            bool: 是否成功
        """
        if element_position:
            return self.click(element_position[0], element_position[1], button)
        return False
    
    def move(self, x: int, y: int) -> bool:
        """
        移动鼠标
        
        Args:
            x: x坐标
            y: y坐标
            
        Returns:
            bool: 是否成功
        """
        try:
            self._input_controller.move(x, y)
            return True
        except Exception as e:
            self._logger.error(f"Move failed: {e}")
            return False
    
    def press_key(self, key: str) -> bool:
        """
        按下按键
        
        Args:
            key: 按键名称
            
        Returns:
            bool: 是否成功
        """
        try:
            if not self._check_action_rate():
                return False
            
            self._input_controller.press_key(key)
            self._record_action()
            return True
        except Exception as e:
            self._logger.error(f"Press key failed: {e}")
            return False
    
    def release_key(self, key: str) -> bool:
        """
        释放按键
        
        Args:
            key: 按键名称
            
        Returns:
            bool: 是否成功
        """
        try:
            self._input_controller.release_key(key)
            return True
        except Exception as e:
            self._logger.error(f"Release key failed: {e}")
            return False
    
    def press_and_release(self, key: str, duration: float = 0.1) -> bool:
        """
        按下并释放按键
        
        Args:
            key: 按键名称
            duration: 按下持续时间
            
        Returns:
            bool: 是否成功
        """
        if self.press_key(key):
            time.sleep(duration)
            return self.release_key(key)
        return False
    
    def _check_action_rate(self) -> bool:
        """
        检查操作频率
        
        Returns:
            bool: 是否允许操作
        """
        now = time.time()
        max_actions = self._config_manager.get('safety.max_actions_per_minute', 30)
        
        # 每分钟重置计数
        if now - self._last_action_time > 60:
            self._action_count = 0
            self._last_action_time = now
        
        # 检查操作频率
        if self._action_count >= max_actions:
            self._logger.warning("Action rate limit reached")
            return False
        
        return True
    
    def _record_action(self) -> None:
        """
        记录操作
        """
        self._action_count += 1
        self._last_action_time = time.time()
    
    def wait(self, min_seconds: float = 0.5, max_seconds: float = 1.5) -> None:
        """
        随机等待
        
        Args:
            min_seconds: 最小等待时间
            max_seconds: 最大等待时间
        """
        wait_time = random.uniform(min_seconds, max_seconds)
        time.sleep(wait_time)
        self._logger.debug(f"Waited for {wait_time:.2f} seconds")
    
    def get_window_capture(self) -> Optional[WindowCapture]:
        """
        获取窗口捕获实例
        
        Returns:
            Optional[WindowCapture]: 窗口捕获实例
        """
        return self._window_capture
    
    def shutdown(self) -> None:
        """
        关闭游戏控制器
        """
        self._logger.info("Game controller shutdown")