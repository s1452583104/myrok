import ctypes
import threading
from typing import Optional, Tuple
import cv2
import numpy as np
import win32gui
import win32ui
import win32con
from win32com.client import Dispatch
from infrastructure import get_logger, WindowNotFoundError, CaptureError


class WindowCapture:
    """游戏窗口捕获模块"""
    
    def __init__(self, window_title: str, dpi_aware: bool = True):
        """
        Args:
            window_title: 窗口标题关键词（模糊匹配）
            dpi_aware: 是否启用DPI感知
        """
        self._window_title = window_title
        self._hwnd: Optional[int] = None
        self._rect: Optional[Tuple[int, int, int, int]] = None
        self._client_rect: Optional[Tuple[int, int, int, int]] = None
        self._dpi_scale: float = 1.0
        self._lock = threading.Lock()
        self._logger = get_logger(self.__class__.__name__)

        if dpi_aware:
            self._setup_dpi_awareness()

    def _setup_dpi_awareness(self):
        """设置DPI感知"""
        try:
            # 设置进程DPI感知
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            self._logger.info("DPI awareness enabled")
        except Exception as e:
            self._logger.warning(f"Failed to set DPI awareness: {e}")

    def find_window(self) -> bool:
        """
        查找游戏窗口（支持模糊匹配标题）

        Returns:
            bool: 是否找到窗口

        Raises:
            WindowNotFoundError: 未找到匹配窗口
        """
        def callback(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if self._window_title.lower() in title.lower():
                    results.append(hwnd)
            return True

        results = []
        win32gui.EnumWindows(callback, results)

        if not results:
            self._logger.error(f"Window not found: {self._window_title}")
            return False

        self._hwnd = results[0]
        self._rect = win32gui.GetWindowRect(self._hwnd)
        left, top, right, bottom = win32gui.GetClientRect(self._hwnd)
        self._client_rect = (0, 0, right - left, bottom - top)
        self._logger.info(f"Window found: hwnd={self._hwnd}, size={self._client_rect[2:]}")
        return True

    def capture(self) -> Optional[np.ndarray]:
        """
        截取窗口客户区画面

        Returns:
            np.ndarray: BGR格式图像，失败返回None
        """
        with self._lock:
            if not self._hwnd or not win32gui.IsWindow(self._hwnd):
                self._logger.error("Invalid window handle")
                return None

            try:
                left, top, right, bottom = self._client_rect
                width = right - left
                height = bottom - top

                # 使用pywin32 BitBlt进行截图
                hwnd_dc = win32gui.GetWindowDC(self._hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()

                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
                save_dc.SelectObject(bitmap)

                # 截图
                save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)

                # 转换为numpy数组
                bmpinfo = bitmap.GetInfo()
                bmpstr = bitmap.GetBitmapBits(True)
                img = np.frombuffer(bmpstr, dtype=np.uint8).reshape(
                    (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)
                )
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                # 清理资源
                win32gui.DeleteObject(bitmap.GetHandle())
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(self._hwnd, hwnd_dc)

                return img

            except Exception as e:
                self._logger.error(f"Capture failed: {e}")
                return None

    def capture_region(self, x: int, y: int, w: int, h: int) -> Optional[np.ndarray]:
        """
        截取窗口指定区域

        Args:
            x: 区域起始x坐标
            y: 区域起始y坐标
            w: 区域宽度
            h: 区域高度
            
        Returns:
            np.ndarray: BGR格式图像，失败返回None
        """
        full_image = self.capture()
        if full_image is None:
            return None
        
        try:
            return full_image[y:y+h, x:x+w]
        except Exception as e:
            self._logger.error(f"Region capture failed: {e}")
            return None

    def capture_background(self) -> Optional[np.ndarray]:
        """
        后台截取窗口画面（使用PrintWindow API）
        
        特点：
        - 窗口无需在前台
        - 支持最小化状态截图
        - 使用PrintWindow API而非BitBlt
        
        Returns:
            np.ndarray: BGR格式图像，失败返回None
        """
        with self._lock:
            if not self._hwnd or not win32gui.IsWindow(self._hwnd):
                self._logger.error("Invalid window handle")
                return None

            try:
                left, top, right, bottom = self._client_rect
                width = right - left
                height = bottom - top

                # 使用PrintWindow进行后台截图
                hwnd_dc = win32gui.GetWindowDC(self._hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()

                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
                save_dc.SelectObject(bitmap)

                # PrintWindow API (PW_RENDERFULLCONTENT = 0x00000002)
                ctypes.windll.user32.PrintWindow(self._hwnd, save_dc.GetSafeHdc(), 2)

                # 转换为numpy数组
                bmpinfo = bitmap.GetInfo()
                bmpstr = bitmap.GetBitmapBits(True)
                img = np.frombuffer(bmpstr, dtype=np.uint8).reshape(
                    (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)
                )
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                # 清理资源
                win32gui.DeleteObject(bitmap.GetHandle())
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(self._hwnd, hwnd_dc)

                self._logger.debug(f"Background capture success: {width}x{height}")
                return img

            except Exception as e:
                self._logger.error(f"Background capture failed: {e}")
                return None

    def is_window_active(self) -> bool:
        """检查窗口是否在前台"""
        return self._hwnd is not None and win32gui.GetForegroundWindow() == self._hwnd

    def bring_to_foreground(self) -> bool:
        """将窗口带到前台"""
        if self._hwnd:
            try:
                # 确保窗口可见
                if win32gui.IsIconic(self._hwnd):
                    win32gui.ShowWindow(self._hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(self._hwnd)
                return True
            except Exception as e:
                self._logger.error(f"Failed to bring window to foreground: {e}")
                return False
        return False

    def get_window_size(self) -> Tuple[int, int]:
        """获取窗口大小"""
        if self._client_rect:
            return (self._client_rect[2], self._client_rect[3])
        return (0, 0)

    @property
    def window_title(self) -> str:
        """窗口标题"""
        return self._window_title

    @property
    def hwnd(self) -> Optional[int]:
        """窗口句柄"""
        return self._hwnd

    def close(self) -> None:
        """清理资源"""
        self._hwnd = None
        self._rect = None
        self._client_rect = None