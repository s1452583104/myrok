from __future__ import annotations
import re
import ctypes
from ctypes import wintypes
from typing import Protocol, runtime_checkable
import numpy as np

@runtime_checkable
class HandleSource(Protocol):
    """Provides screenshot capture and click input for a single window.

    Implementations may additionally provide an optional `swipe` method;
    it is not part of the runtime-checked interface so that lightweight
    implementations (e.g. a headless test double) can omit it.
    """
    def capture(self) -> np.ndarray:
        """Return current screen as BGR numpy array."""
        ...
    def click(self, x: int, y: int) -> None:
        """Click at (x, y) in window-local pixel coordinates."""
        ...
    def is_alive(self) -> bool:
        """True if the underlying window is still present."""
        ...


class MockHandleSource:
    """Test double for HandleSource. Records calls, returns canned image."""
    def __init__(self, screenshot: np.ndarray, alive: bool = True):
        self._screenshot = screenshot
        self._alive = alive
        self.clicks: list = []
        self.swipes: list = []

    def capture(self) -> np.ndarray:
        return self._screenshot.copy()

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipes.append((x1, y1, x2, y2, duration_ms))

    def is_alive(self) -> bool:
        return self._alive

    def set_alive(self, alive: bool) -> None:
        self._alive = alive


class Win32HandleSource:
    """Real Windows HandleSource using FindWindowW + PrintWindow + PostMessage."""
    def __init__(self, window_title_pattern: str):
        self._pattern = window_title_pattern
        self._hwnd = None
        self._user32 = ctypes.windll.user32

    def _find_window_by_title(self, pattern: str):
        hwnd_enum = []
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, lParam):
            length = self._user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                self._user32.GetWindowTextW(hwnd, buf, length + 1)
                if re.search(self._pattern, buf.value):
                    hwnd_enum.append(hwnd)
                    return False
            return True
        self._user32.EnumWindows(EnumWindowsProc(callback), 0)
        return hwnd_enum[0] if hwnd_enum else None

    def _resolve_hwnd(self):
        if self._hwnd is None:
            self._hwnd = self._find_window_by_title(self._pattern)
        return self._hwnd

    def capture(self):
        import cv2
        hwnd = self._resolve_hwnd()
        if hwnd is None:
            raise RuntimeError(f"No window matching: {self._pattern}")
        rect = wintypes.RECT()
        self._user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        hwnd_dc = self._user32.GetWindowDC(hwnd)
        mfc_dc = self._user32.CreateCompatibleDC(hwnd_dc)
        bmp = self._user32.CreateCompatibleBitmap(hwnd_dc, w, h)
        self._user32.SelectObject(mfc_dc, bmp)
        self._user32.PrintWindow(hwnd, mfc_dc, 2)
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
            ]
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        buf = (ctypes.c_ubyte * (w * h * 4))()
        self._user32.GetDIBits(mfc_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
        self._user32.DeleteObject(bmp)
        self._user32.DeleteDC(mfc_dc)
        self._user32.ReleaseDC(hwnd, hwnd_dc)
        img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def click(self, x: int, y: int) -> None:
        hwnd = self._resolve_hwnd()
        if hwnd is None:
            raise RuntimeError(f"No window matching: {self._pattern}")
        WM_LBUTTONDOWN = 0x0201
        WM_LBUTTONUP = 0x0202
        MK_LBUTTON = 0x0001
        lParam = (y << 16) | x
        self._user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lParam)
        self._user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lParam)

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        for i in range(1, 6):
            t = i / 5
            self.click(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))

    def is_alive(self) -> bool:
        hwnd = self._resolve_hwnd()
        if hwnd is None:
            return False
        return bool(self._user32.IsWindow(hwnd))
