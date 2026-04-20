#!/usr/bin/env python3
"""后台输入控制器 - 使用 Windows API 实现后台键盘鼠标操作."""

import time
from typing import Tuple

import win32api
import win32con

from infrastructure.logger import get_logger


class BackgroundInputController:
    """后台输入控制器.
    
    使用 Windows API 发送后台键盘和鼠标消息，
    窗口不需要在前台即可接收输入。
    
    使用示例:
        controller = BackgroundInputController(hwnd)
        controller.send_text("你好")
        controller.send_enter()
        controller.click(100, 200)
    """
    
    def __init__(self, hwnd: int):
        """初始化.
        
        Args:
            hwnd: 窗口句柄
        """
        self._hwnd = hwnd
        self._logger = get_logger(self.__class__.__name__)
    
    def send_char(self, char: str) -> bool:
        """发送单个字符.
        
        Args:
            char: 要发送的字符
            
        Returns:
            是否成功
        """
        try:
            code_point = ord(char)
            win32api.PostMessage(self._hwnd, win32con.WM_CHAR, code_point, 0)
            time.sleep(0.05)
            self._logger.debug(f"Sent char: {char}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to send char '{char}': {e}")
            return False
    
    def send_text(self, text: str) -> bool:
        """发送文本.
        
        Args:
            text: 要发送的文本
            
        Returns:
            是否成功
        """
        try:
            for char in text:
                self.send_char(char)
            self._logger.info(f"Sent text: {text}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to send text '{text}': {e}")
            return False
    
    def send_key_down(self, vk_code: int) -> bool:
        """发送按键按下.
        
        Args:
            vk_code: 虚拟键码
            
        Returns:
            是否成功
        """
        try:
            win32api.PostMessage(self._hwnd, win32con.WM_KEYDOWN, vk_code, 0)
            self._logger.debug(f"Key down: {vk_code}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to send key down {vk_code}: {e}")
            return False
    
    def send_key_up(self, vk_code: int) -> bool:
        """发送按键释放.
        
        Args:
            vk_code: 虚拟键码
            
        Returns:
            是否成功
        """
        try:
            win32api.PostMessage(self._hwnd, win32con.WM_KEYUP, vk_code, 0)
            self._logger.debug(f"Key up: {vk_code}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to send key up {vk_code}: {e}")
            return False
    
    def send_key_press(self, vk_code: int) -> bool:
        """发送完整按键（按下+释放）.
        
        Args:
            vk_code: 虚拟键码
            
        Returns:
            是否成功
        """
        try:
            self.send_key_down(vk_code)
            time.sleep(0.05)
            self.send_key_up(vk_code)
            self._logger.debug(f"Key press: {vk_code}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to send key press {vk_code}: {e}")
            return False
    
    def send_enter(self) -> bool:
        """发送回车键.
        
        Returns:
            是否成功
        """
        VK_RETURN = 0x0D
        return self.send_key_press(VK_RETURN)
    
    def send_escape(self) -> bool:
        """发送ESC键.
        
        Returns:
            是否成功
        """
        VK_ESCAPE = 0x1B
        return self.send_key_press(VK_ESCAPE)
    
    def send_tab(self) -> bool:
        """发送TAB键.
        
        Returns:
            是否成功
        """
        VK_TAB = 0x09
        return self.send_key_press(VK_TAB)
    
    def send_space(self) -> bool:
        """发送空格键.
        
        Returns:
            是否成功
        """
        VK_SPACE = 0x20
        return self.send_key_press(VK_SPACE)
    
    def click(self, x: int, y: int, button: str = "left") -> bool:
        """鼠标点击.
        
        Args:
            x: X坐标（相对于窗口）
            y: Y坐标（相对于窗口）
            button: 鼠标按钮 (left, right)
            
        Returns:
            是否成功
        """
        try:
            # 构建 LPARAM
            lparam = (y << 16) | (x & 0xFFFF)
            
            if button == "left":
                win32api.PostMessage(self._hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
                time.sleep(0.05)
                win32api.PostMessage(self._hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            elif button == "right":
                win32api.PostMessage(self._hwnd, win32con.WM_RBUTTONDOWN, win32con.MK_RBUTTON, lparam)
                time.sleep(0.05)
                win32api.PostMessage(self._hwnd, win32con.WM_RBUTTONUP, 0, lparam)
            else:
                self._logger.error(f"Unknown button: {button}")
                return False
            
            self._logger.debug(f"Click {button} at ({x}, {y})")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to click at ({x}, {y}): {e}")
            return False
    
    def double_click(self, x: int, y: int) -> bool:
        """鼠标双击.
        
        Args:
            x: X坐标
            y: Y坐标
            
        Returns:
            是否成功
        """
        try:
            lparam = (y << 16) | (x & 0xFFFF)
            
            # 发送 WM_LBUTTONDBLCLK 消息
            win32api.PostMessage(self._hwnd, win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON, lparam)
            
            self._logger.debug(f"Double click at ({x}, {y})")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to double click at ({x}, {y}): {e}")
            return False
    
    def move_mouse(self, x: int, y: int) -> bool:
        """移动鼠标（后台）.
        
        Args:
            x: X坐标
            y: Y坐标
            
        Returns:
            是否成功
        """
        try:
            lparam = (y << 16) | (x & 0xFFFF)
            win32api.PostMessage(self._hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
            self._logger.debug(f"Mouse move to ({x}, {y})")
            return True
        except Exception as e:
            self._logger.error(f"Failed to move mouse to ({x}, {y}): {e}")
            return False
    
    def drag(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """鼠标拖拽.
        
        Args:
            x1: 起始X坐标
            y1: 起始Y坐标
            x2: 目标X坐标
            y2: 目标Y坐标
            
        Returns:
            是否成功
        """
        try:
            # 按下
            lparam1 = (y1 << 16) | (x1 & 0xFFFF)
            win32api.PostMessage(self._hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam1)
            time.sleep(0.1)
            
            # 移动
            lparam2 = (y2 << 16) | (x2 & 0xFFFF)
            win32api.PostMessage(self._hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, lparam2)
            time.sleep(0.1)
            
            # 释放
            win32api.PostMessage(self._hwnd, win32con.WM_LBUTTONUP, 0, lparam2)
            
            self._logger.debug(f"Drag from ({x1}, {y1}) to ({x2}, {y2})")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to drag: {e}")
            return False


# 常用虚拟键码常量
class VKCodes:
    """虚拟键码常量."""
    VK_RETURN = 0x0D      # 回车
    VK_ESCAPE = 0x1B      # ESC
    VK_TAB = 0x09         # TAB
    VK_SPACE = 0x20       # 空格
    VK_SHIFT = 0x10       # Shift
    VK_CONTROL = 0x11     # Control
    VK_ALT = 0x12         # Alt
    VK_BACK = 0x08        # 退格
    VK_DELETE = 0x2E      # Delete
    VK_INSERT = 0x2D      # Insert
    VK_HOME = 0x24        # Home
    VK_END = 0x23         # End
    VK_PAGEUP = 0x21      # Page Up
    VK_PAGEDOWN = 0x22    # Page Down
    VK_UP = 0x26          # 上箭头
    VK_DOWN = 0x28        # 下箭头
    VK_LEFT = 0x25        # 左箭头
    VK_RIGHT = 0x27       # 右箭头
    VK_F1 = 0x70          # F1
    VK_F2 = 0x71          # F2
    VK_F3 = 0x72          # F3
    VK_F4 = 0x73          # F4
    VK_F5 = 0x74          # F5
    VK_F6 = 0x75          # F6
    VK_F7 = 0x76          # F7
    VK_F8 = 0x77          # F8
    VK_F9 = 0x78          # F9
    VK_F10 = 0x79         # F10
    VK_F11 = 0x7A         # F11
    VK_F12 = 0x7B         # F12
