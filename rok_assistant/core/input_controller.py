from abc import ABC, abstractmethod
import random
import time
from typing import Optional, Tuple
import win32api
import win32con
import win32gui
import pyautogui
from infrastructure import get_logger


class BaseInputController(ABC):
    """输入控制抽象基类"""
    @abstractmethod
    def click(self, x: int, y: int, button: str = "left"):
        pass
    
    @abstractmethod
    def move(self, x: int, y: int):
        pass
    
    @abstractmethod
    def press_key(self, key: str):
        pass
    
    @abstractmethod
    def release_key(self, key: str):
        pass


class PyAutoGUIInputController(BaseInputController):
    """基于PyAutoGUI的输入控制器"""
    
    def __init__(self, min_delay: float = 0.05, max_delay: float = 0.3, random_offset: int = 5):
        """
        Args:
            min_delay: 最小延迟（秒）
            max_delay: 最大延迟（秒）
            random_offset: 随机偏移像素
        """
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._random_offset = random_offset
        self._logger = get_logger(self.__class__.__name__)
    
    def click(self, x: int, y: int, button: str = "left"):
        """模拟点击"""
        # 添加随机偏移
        x += random.randint(-self._random_offset, self._random_offset)
        y += random.randint(-self._random_offset, self._random_offset)
        
        # 添加随机延迟
        time.sleep(random.uniform(self._min_delay, self._max_delay))
        
        try:
            pyautogui.click(x, y, button=button, duration=0.1)
            self._logger.debug(f"Clicked at ({x}, {y}) with {button} button")
        except Exception as e:
            self._logger.error(f"Click failed: {e}")
    
    def move(self, x: int, y: int):
        """模拟移动鼠标"""
        # 添加随机偏移
        x += random.randint(-self._random_offset, self._random_offset)
        y += random.randint(-self._random_offset, self._random_offset)
        
        try:
            pyautogui.moveTo(x, y, duration=0.3)
            self._logger.debug(f"Moved mouse to ({x}, {y})")
        except Exception as e:
            self._logger.error(f"Move failed: {e}")
    
    def press_key(self, key: str):
        """模拟按键"""
        try:
            pyautogui.keyDown(key)
            self._logger.debug(f"Pressed key: {key}")
        except Exception as e:
            self._logger.error(f"Press key failed: {e}")
    
    def release_key(self, key: str):
        """模拟释放按键"""
        try:
            pyautogui.keyUp(key)
            self._logger.debug(f"Released key: {key}")
        except Exception as e:
            self._logger.error(f"Release key failed: {e}")


class BackgroundInputController(BaseInputController):
    """后台输入控制器（使用Windows消息）"""
    
    def __init__(self, hwnd: int, min_delay: float = 0.05, max_delay: float = 0.3):
        """
        Args:
            hwnd: 窗口句柄
            min_delay: 最小延迟（秒）
            max_delay: 最大延迟（秒）
        """
        self._hwnd = hwnd
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._logger = get_logger(self.__class__.__name__)
    
    def click(self, x: int, y: int, button: str = "left"):
        """后台模拟点击"""
        # 添加随机延迟
        time.sleep(random.uniform(self._min_delay, self._max_delay))
        
        try:
            # 转换为客户端坐标
            lParam = win32api.MAKELONG(x, y)
            
            if button == "left":
                # 左键点击
                win32gui.PostMessage(self._hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
                time.sleep(0.05)
                win32gui.PostMessage(self._hwnd, win32con.WM_LBUTTONUP, 0, lParam)
            elif button == "right":
                # 右键点击
                win32gui.PostMessage(self._hwnd, win32con.WM_RBUTTONDOWN, win32con.MK_RBUTTON, lParam)
                time.sleep(0.05)
                win32gui.PostMessage(self._hwnd, win32con.WM_RBUTTONUP, 0, lParam)
            
            self._logger.debug(f"Background clicked at ({x}, {y}) with {button} button")
        except Exception as e:
            self._logger.error(f"Background click failed: {e}")
    
    def move(self, x: int, y: int):
        """后台模拟移动鼠标"""
        try:
            # 转换为客户端坐标
            lParam = win32api.MAKELONG(x, y)
            win32gui.PostMessage(self._hwnd, win32con.WM_MOUSEMOVE, 0, lParam)
            self._logger.debug(f"Background moved mouse to ({x}, {y})")
        except Exception as e:
            self._logger.error(f"Background move failed: {e}")
    
    def press_key(self, key: str):
        """后台模拟按键"""
        try:
            # 这里需要根据具体的键码映射实现
            # 简单示例：发送回车键
            if key == "enter":
                win32gui.PostMessage(self._hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
                self._logger.debug(f"Background pressed key: {key}")
        except Exception as e:
            self._logger.error(f"Background press key failed: {e}")
    
    def release_key(self, key: str):
        """后台模拟释放按键"""
        try:
            # 这里需要根据具体的键码映射实现
            # 简单示例：释放回车键
            if key == "enter":
                win32gui.PostMessage(self._hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
                self._logger.debug(f"Background released key: {key}")
        except Exception as e:
            self._logger.error(f"Background release key failed: {e}")


class InputController:
    """输入控制器工厂类"""
    
    @staticmethod
    def create_controller(
        mode: str = "foreground",
        hwnd: Optional[int] = None,
        min_delay: float = 0.05,
        max_delay: float = 0.3,
        random_offset: int = 5
    ) -> BaseInputController:
        """
        创建输入控制器
        
        Args:
            mode: 控制模式 (foreground/background)
            hwnd: 窗口句柄（后台模式需要）
            min_delay: 最小延迟
            max_delay: 最大延迟
            random_offset: 随机偏移
            
        Returns:
            BaseInputController: 输入控制器实例
        """
        if mode == "background" and hwnd:
            return BackgroundInputController(hwnd, min_delay, max_delay)
        else:
            return PyAutoGUIInputController(min_delay, max_delay, random_offset)