"""窗口捕获模块.

提供游戏窗口查找、截图和状态管理功能.

核心功能:
- 查找并定位游戏窗口（支持模糊匹配标题）
- 截取窗口画面（支持区域截取）
- 处理DPI缩放
- 管理窗口状态

线程安全: 是（内部使用锁保护）
"""

import threading
from typing import Optional, Tuple

import cv2
import numpy as np

from infrastructure.exception_handler import WindowNotFoundError
from infrastructure.logger import get_logger

try:
    import win32con
    import win32gui
    import win32ui

    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False


class WindowCapture:
    """游戏窗口捕获模块.

    职责:
    - 查找并定位游戏窗口
    - 截取窗口画面（支持区域截取）
    - 处理DPI缩放
    - 管理窗口状态

    线程安全: 是（内部使用锁保护）
    异常: WindowNotFoundError, CaptureError

    使用示例:
        capture = WindowCapture("万国觉醒")
        if capture.find_window():
            img = capture.capture()
            if img is not None:
                cv2.imshow("Game", img)
                cv2.waitKey(0)
    """

    def __init__(self, window_title: str, dpi_aware: bool = True):
        """初始化窗口捕获器.

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

    def _setup_dpi_awareness(self) -> None:
        """设置DPI感知, 确保截图尺寸正确."""
        try:
            import ctypes

            # Windows 10 1703+ 推荐的方式
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except (AttributeError, OSError):
            try:
                # 兼容旧版Windows
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                self._logger.warning("Could not set DPI awareness")

        # 获取DPI缩放因子
        try:
            import ctypes

            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, hdc)
            self._dpi_scale = dpi / 96.0
            self._logger.info(f"DPI scale: {self._dpi_scale:.2f}")
        except Exception as e:
            self._logger.warning(f"Could not get DPI scale: {e}")
            self._dpi_scale = 1.0

    def find_window(self) -> bool:
        """查找游戏窗口（支持模糊匹配标题）.

        Returns:
            bool: 是否找到窗口

        Raises:
            WindowNotFoundError: 未找到匹配窗口
        """
        if not _WIN32_AVAILABLE:
            self._logger.error("pywin32 is not installed, cannot find window")
            return False

        def callback(hwnd: int, results: list) -> bool:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if self._window_title.lower() in title.lower():
                    results.append(hwnd)
            return True

        results: list = []
        win32gui.EnumWindows(callback, results)

        if not results:
            self._logger.error(f"Window not found: {self._window_title}")
            return False

        self._hwnd = results[0]
        try:
            self._rect = win32gui.GetWindowRect(self._hwnd)
            left, top, right, bottom = win32gui.GetClientRect(self._hwnd)
            self._client_rect = (0, 0, right - left, bottom - top)
            self._logger.info(
                f"Window found: hwnd={self._hwnd}, "
                f"size={self._client_rect[2]}x{self._client_rect[3]}"
            )
        except Exception as e:
            self._logger.error(f"Failed to get window rect: {e}")
            return False

        return True

    def get_client_rect(self) -> Tuple[int, int, int, int]:
        """获取窗口客户区坐标.

        Returns:
            (left, top, right, bottom) 相对于窗口客户区的坐标

        Raises:
            WindowNotFoundError: 窗口未找到
        """
        if self._client_rect is None:
            raise WindowNotFoundError(self._window_title)
        return self._client_rect

    def capture(self) -> Optional[np.ndarray]:
        """截取窗口客户区画面（使用后台截图方法）.

        Returns:
            BGR格式numpy数组, 失败返回None
        """
        if not _WIN32_AVAILABLE:
            self._logger.error("pywin32 is not installed, cannot capture")
            return None

        with self._lock:
            if not self._hwnd or not win32gui.IsWindow(self._hwnd):
                self._logger.error("Invalid window handle")
                return None

            if self._client_rect is None:
                self._logger.error("Client rect not available")
                return None

            try:
                left, top, right, bottom = self._client_rect
                width = int((right - left) * self._dpi_scale)
                height = int((bottom - top) * self._dpi_scale)

                if width <= 0 or height <= 0:
                    self._logger.error(f"Invalid window size: {width}x{height}")
                    return None

                # 方法1: 尝试使用 PrintWindow API（后台截图，更可靠）
                img = self._capture_printwindow(width, height)
                
                # 方法2: 如果 PrintWindow 失败，使用 BitBlt
                if img is None:
                    self._logger.debug("PrintWindow failed, trying BitBlt...")
                    img = self._capture_bitblt(width, height, left, top)
                
                return img

            except Exception as e:
                self._logger.error(f"Capture failed: {e}", exc_info=True)
                return None
    
    def _capture_printwindow(self, width: int, height: int) -> Optional[np.ndarray]:
        """使用 PrintWindow API 进行后台截图.
        
        Args:
            width: 截图宽度
            height: 截图高度
            
        Returns:
            BGR格式numpy数组, 失败返回None
        """
        try:
            import ctypes
            from ctypes import windll
            
            # 获取窗口 DC
            hwnd_dc = win32gui.GetWindowDC(self._hwnd)
            if not hwnd_dc:
                return None
            
            # 创建兼容 DC
            mem_dc = win32ui.CreateDCFromHandle(hwnd_dc).CreateCompatibleDC()
            
            # 创建位图
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(
                win32ui.CreateDCFromHandle(hwnd_dc),
                width,
                height
            )
            mem_dc.SelectObject(bitmap)
            
            # 使用 PrintWindow API
            # PW_RENDERFULLCONTENT = 0x00000002 (包含硬件加速内容)
            PW_RENDERFULLCONTENT = 2
            result = windll.user32.PrintWindow(
                self._hwnd,
                mem_dc.GetSafeHdc(),
                PW_RENDERFULLCONTENT
            )
            
            if result == 0:
                # 清理资源
                win32gui.DeleteObject(bitmap.GetHandle())
                mem_dc.DeleteDC()
                win32gui.ReleaseDC(self._hwnd, hwnd_dc)
                return None
            
            # 转换为 numpy 数组
            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8).reshape(
                (bmpinfo["bmHeight"], bmpinfo["bmWidth"], 4)
            )
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            
            # 清理资源
            win32gui.DeleteObject(bitmap.GetHandle())
            mem_dc.DeleteDC()
            win32gui.ReleaseDC(self._hwnd, hwnd_dc)
            
            self._logger.debug(f"PrintWindow capture success: {img.shape}")
            return img
            
        except Exception as e:
            self._logger.debug(f"PrintWindow capture failed: {e}")
            return None
    
    def _capture_bitblt(self, width: int, height: int, left: int, top: int) -> Optional[np.ndarray]:
        """使用 BitBlt 进行截图（备用方法）.
        
        Args:
            width: 截图宽度
            height: 截图高度
            left: 左边界
            top: 上边界
            
        Returns:
            BGR格式numpy数组, 失败返回None
        """
        try:
            # 使用pywin32 BitBlt进行截图
            hwnd_dc = win32gui.GetWindowDC(self._hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            # 截图
            save_dc.BitBlt(
                (0, 0),
                (width, height),
                mfc_dc,
                (int(left * self._dpi_scale), int(top * self._dpi_scale)),
                win32con.SRCCOPY,
            )

            # 转换为numpy数组
            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8).reshape(
                (bmpinfo["bmHeight"], bmpinfo["bmWidth"], 4)
            )
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            # 清理资源
            win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(self._hwnd, hwnd_dc)

            self._logger.debug(f"BitBlt capture success: {img.shape}")
            return img

        except Exception as e:
            self._logger.error(f"BitBlt capture failed: {e}")
            return None

    def capture_region(
        self, x: int, y: int, w: int, h: int
    ) -> Optional[np.ndarray]:
        """截取窗口指定区域.

        Args:
            x: 区域左上角X坐标（客户区相对坐标）
            y: 区域左上角Y坐标（客户区相对坐标）
            w: 区域宽度
            h: 区域高度

        Returns:
            BGR格式numpy数组, 失败返回None
        """
        if not _WIN32_AVAILABLE:
            self._logger.error("pywin32 is not installed, cannot capture")
            return None

        with self._lock:
            if not self._hwnd or not win32gui.IsWindow(self._hwnd):
                self._logger.error("Invalid window handle")
                return None

            try:
                # 转换到DPI缩放后的坐标
                sx = int(x * self._dpi_scale)
                sy = int(y * self._dpi_scale)
                sw = int(w * self._dpi_scale)
                sh = int(h * self._dpi_scale)

                hwnd_dc = win32gui.GetWindowDC(self._hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()

                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, sw, sh)
                save_dc.SelectObject(bitmap)

                save_dc.BitBlt(
                    (0, 0),
                    (sw, sh),
                    mfc_dc,
                    (sx, sy),
                    win32con.SRCCOPY,
                )

                bmpinfo = bitmap.GetInfo()
                bmpstr = bitmap.GetBitmapBits(True)
                img = np.frombuffer(bmpstr, dtype=np.uint8).reshape(
                    (bmpinfo["bmHeight"], bmpinfo["bmWidth"], 4)
                )
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                # 清理资源
                win32gui.DeleteObject(bitmap.GetHandle())
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(self._hwnd, hwnd_dc)

                return img

            except Exception as e:
                self._logger.error(f"Region capture failed: {e}", exc_info=True)
                return None

    def is_window_active(self) -> bool:
        """检查窗口是否在前台.

        Returns:
            窗口是否在前台
        """
        if self._hwnd is None:
            return False
        try:
            return win32gui.GetForegroundWindow() == self._hwnd
        except Exception:
            return False

    def bring_to_foreground(self) -> bool:
        """将窗口带到前台.

        Returns:
            是否成功
        """
        if self._hwnd is None:
            return False
        try:
            win32gui.SetForegroundWindow(self._hwnd)
            self._logger.info("Window brought to foreground")
            return True
        except Exception as e:
            self._logger.error(f"Failed to bring window to foreground: {e}")
            return False

    def get_window_size(self) -> Tuple[int, int]:
        """获取窗口客户区大小.

        Returns:
            (width, height) 窗口客户区大小
        """
        if self._client_rect is None:
            return (0, 0)
        return (
            self._client_rect[2] - self._client_rect[0],
            self._client_rect[3] - self._client_rect[1],
        )

    def close(self) -> None:
        """释放资源."""
        self._hwnd = None
        self._rect = None
        self._client_rect = None
        self._logger.info("WindowCapture resources released")

    @property
    def window_title(self) -> str:
        """窗口标题关键词."""
        return self._window_title

    @property
    def hwnd(self) -> Optional[int]:
        """窗口句柄."""
        return self._hwnd

    @property
    def dpi_scale(self) -> float:
        """DPI缩放因子."""
        return self._dpi_scale
