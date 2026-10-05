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


def create_handle_source(mumu_index: int | None = None, mumu_manager_path: str = "",
                         adb_address: str = "", adb_path: str = "adb",
                         window_title_pattern: str = "", _locator=None):
    """Build the best HandleSource for an instance.

    mumu_index set -> resolve adb address via MuMuManager, then AdbHandleSource.
    Precedence: mumu_index WINS over adb_address — mumu mode takes priority
    even if a manual adb_address is also present.
    adb_address set -> AdbHandleSource directly (manual mode / non-MuMu emulator).
    Otherwise fall back to Win32 capture.
    """
    if mumu_index is not None:
        from ..infra.mumu import MumuLocator
        locator = _locator(mumu_manager_path, adb_path) if _locator is not None \
            else MumuLocator(mumu_manager_path, adb_path)
        address = locator.resolve_adb_address(mumu_index)
        return AdbHandleSource(adb_address=address, adb_path=adb_path)
    if adb_address:
        return AdbHandleSource(adb_address=adb_address, adb_path=adb_path)
    return Win32HandleSource(window_title_pattern=window_title_pattern)


class AdbHandleSource:
    """HandleSource over MuMu's adb: screencap for capture, input tap/swipe for input.

    Captures at the emulator's native Android resolution (e.g. 1920x1080)
    regardless of window size or display DPI scaling.

    **必须先 `adb connect`**：MuMu 的 adb 端口是 TCP 设备，没连过时
    `adb -s 127.0.0.1:16384 exec-out screencap` 会直接报
    `error: device '...' not found`（2026-10-05 实机确认：`adb devices` 为空）。
    之前靠运行手册让人手动 connect，所以新用户点「测试连接」必然失败。
    这里在首次使用前自动连一次，失败时重连一次再试（adb server 重启 /
    模拟器重启后设备会掉线）。
    """

    def __init__(self, adb_address: str, adb_path: str = "adb", _runner=None):
        self._address = adb_address
        self._adb_path = adb_path
        self._run = _runner if _runner is not None else self._subprocess_run
        self._connected = False

    @staticmethod
    def _subprocess_run(args, **kwargs):
        from ..infra.subproc import run as run_child
        # 走 infra/subproc.run：它负责剥 QT_*，以及带上 CREATE_NO_WINDOW——
        # **这条是热路径**（每截一帧、每点一下都起一次 adb），漏掉后者的话
        # 打包后每调一次 adb 就闪一个黑窗，用户看到的就是「黑窗闪个不停」。
        return run_child(args, capture_output=True, check=True, timeout=10)

    def _serial_args(self) -> list:
        return ["-s", self._address]

    def _ensure_connected(self) -> None:
        """首次使用前连一次。**吞掉异常**：连不上时后续真实命令会给出
        更具体的错误（比如 adb.exe 路径不对），在这里抛只会掩盖它。"""
        if self._connected:
            return
        try:
            self._run([self._adb_path, "connect", self._address])
        except Exception:                       # noqa: BLE001 - 见 docstring
            pass
        self._connected = True

    def _run_checked(self, args):
        """跑一条真实命令；失败时重连一次再试一次。

        掉线是常态而非异常：adb server 重启、模拟器重启都会让设备从
        `adb devices` 里消失，重连即可恢复，不该让整轮跑挂掉。
        """
        self._ensure_connected()
        try:
            return self._run(args)
        except Exception:
            self._connected = False
            self._ensure_connected()
            return self._run(args)

    def capture(self) -> np.ndarray:
        import cv2
        proc = self._run_checked(
            [self._adb_path, *self._serial_args(), "exec-out", "screencap", "-p"])
        img = cv2.imdecode(np.frombuffer(proc.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"screencap returned undecodable data from {self._address}")
        return img

    def click(self, x: int, y: int) -> None:
        self._run_checked([self._adb_path, *self._serial_args(),
                           "shell", "input", "tap", str(int(x)), str(int(y))])

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self._run_checked([self._adb_path, *self._serial_args(), "shell", "input", "swipe",
                           str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)),
                           str(int(duration_ms))])

    def is_alive(self) -> bool:
        try:
            proc = self._run([self._adb_path, "devices"])
        except Exception:
            return False
        for line in proc.stdout.decode(errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == self._address:
                return parts[1] == "device"
        return False


class Win32HandleSource:
    """Real Windows HandleSource using FindWindowW + PrintWindow + PostMessage."""
    def __init__(self, window_title_pattern: str):
        self._pattern = window_title_pattern
        self._hwnd = None
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32

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
        mfc_dc = self._gdi32.CreateCompatibleDC(hwnd_dc)
        bmp = self._gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
        self._gdi32.SelectObject(mfc_dc, bmp)
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
        self._gdi32.GetDIBits(mfc_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
        self._gdi32.DeleteObject(bmp)
        self._gdi32.DeleteDC(mfc_dc)
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
