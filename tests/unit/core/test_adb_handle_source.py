"""Tests for AdbHandleSource (subprocess mocked, no real device)."""
import subprocess
import numpy as np
import pytest
from rok_assistant.core.handle_source import AdbHandleSource


import cv2

_TINY_PNG = cv2.imencode(".png", np.zeros((4, 4, 3), dtype=np.uint8))[1].tobytes()


class FakeAdb:
    """Runs in place of adb.exe; records invocations, returns canned output."""

    def __init__(self, png_bytes: bytes = _TINY_PNG):
        self.png_bytes = png_bytes
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout=self._stdout(args), stderr=b"")

    def _stdout(self, args):
        if "screencap" in args:
            return self.png_bytes
        if "devices" in args:
            return b"List of devices attached\n127.0.0.1:16384\tdevice\n"
        return b"ok"

    def find(self, keyword: str) -> list[str] | None:
        """第一条含 keyword 的调用（connect 会插到最前面，不能再取 calls[0]）。"""
        return next((c for c in self.calls if keyword in c), None)


def test_capture_decodes_png():
    import cv2
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    fake = FakeAdb(buf.tobytes())
    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb", _runner=fake)
    out = src.capture()
    assert out.shape == (1080, 1920, 3)


def test_capture_invokes_screencap_with_serial():
    fake = FakeAdb()
    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb", _runner=fake)
    src.capture()
    args = fake.find("screencap")
    assert args is not None
    assert "exec-out" in args
    assert "-s" in args
    assert "127.0.0.1:16384" in args


def test_click_uses_input_tap():
    fake = FakeAdb()
    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb", _runner=fake)
    src.click(500, 300)
    args = fake.find("tap")
    assert args is not None
    assert "shell" in args and "input" in args
    assert "500" in args and "300" in args


def test_swipe_uses_input_swipe():
    fake = FakeAdb()
    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb", _runner=fake)
    src.swipe(10, 20, 300, 400, duration_ms=500)
    args = fake.find("swipe")
    assert args is not None
    assert "500" in args


# ---- adb connect（2026-10-05）：不连就发命令必失败 ----

def test_connects_before_first_screencap():
    """MuMu 的 adb 端口是 TCP 设备，没 connect 过时 -s 会报 device not found。"""
    fake = FakeAdb()
    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb", _runner=fake)
    src.capture()
    assert fake.calls[0] == ["adb", "connect", "127.0.0.1:16384"]


def test_connects_only_once_across_calls():
    """成功路径上不该每次都 connect——只在首次多发一条命令。"""
    fake = FakeAdb()
    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb", _runner=fake)
    src.capture()
    src.capture()
    src.click(1, 2)
    assert sum(1 for c in fake.calls if "connect" in c) == 1
    assert sum(1 for c in fake.calls if "screencap" in c) == 2


def test_reconnects_and_retries_after_failure():
    """模拟器/adb server 重启后设备会掉线，重连一次就该恢复。"""

    class FlakyAdb(FakeAdb):
        def __init__(self):
            super().__init__()
            self.screencap_attempts = 0

        def __call__(self, args, **kwargs):
            if "screencap" in args:
                self.screencap_attempts += 1
                if self.screencap_attempts == 1:
                    self.calls.append(list(args))
                    raise subprocess.CalledProcessError(
                        1, args, stderr=b"error: device offline")
            return super().__call__(args, **kwargs)

    fake = FlakyAdb()
    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb", _runner=fake)
    out = src.capture()

    assert out.shape == (4, 4, 3)
    assert fake.screencap_attempts == 2, "第一次失败后应重试"
    assert sum(1 for c in fake.calls if "connect" in c) == 2, "重试前应重连"


def test_failure_surfaces_after_retry():
    """重连也救不回来时要把原始错误抛出去，不能吞掉。"""
    import pytest

    class DeadAdb(FakeAdb):
        def __call__(self, args, **kwargs):
            if "screencap" in args:
                raise subprocess.CalledProcessError(
                    1, args, stderr=b"error: device '127.0.0.1:16384' not found")
            return super().__call__(args, **kwargs)

    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb",
                          _runner=DeadAdb())
    with pytest.raises(subprocess.CalledProcessError):
        src.capture()


def test_is_alive_true_when_device_listed():
    fake = FakeAdb()
    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb", _runner=fake)
    assert src.is_alive() is True


def test_is_alive_false_when_offline():
    class OfflineAdb(FakeAdb):
        def _stdout(self, args):
            if "devices" in args:
                return b"List of devices attached\n127.0.0.1:16384\toffline\n"
            return b""

    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb",
                          _runner=OfflineAdb())
    assert src.is_alive() is False


def test_factory_prefers_adb_when_address_set():
    from rok_assistant.core.handle_source import create_handle_source
    src = create_handle_source(adb_address="127.0.0.1:16384", window_title_pattern="MuMu")
    assert isinstance(src, AdbHandleSource)
    assert src._address == "127.0.0.1:16384"


def test_factory_falls_back_to_win32():
    from rok_assistant.core.handle_source import Win32HandleSource, create_handle_source
    src = create_handle_source(window_title_pattern="MuMu")
    assert isinstance(src, Win32HandleSource)


class FakeLocator:
    def __init__(self, manager_path, adb_path):
        self.manager_path = manager_path
        self.adb_path = adb_path

    def resolve_adb_address(self, index):
        return f"127.0.0.1:{17000 + index}"


def test_factory_resolves_mumu_index():
    from rok_assistant.core.handle_source import create_handle_source
    src = create_handle_source(mumu_index=3, mumu_manager_path="C:/mumu/MuMuManager.exe",
                               adb_path="adb", _locator=FakeLocator)
    assert isinstance(src, AdbHandleSource)
    assert src._address == "127.0.0.1:17003"
    assert src._adb_path == "adb"


def test_factory_manual_adb_still_works_without_mumu_fields():
    from rok_assistant.core.handle_source import create_handle_source
    src = create_handle_source(adb_address="127.0.0.1:16384", adb_path="adb")
    assert isinstance(src, AdbHandleSource)


def test_factory_forwards_manager_and_adb_path_to_locator():
    from rok_assistant.core.handle_source import create_handle_source
    captured = {}

    class SpyLocator:
        def __init__(self, manager_path, adb_path):
            captured["manager"] = manager_path
            captured["adb"] = adb_path

        def resolve_adb_address(self, index):
            return "127.0.0.1:19999"

    src = create_handle_source(mumu_index=1, mumu_manager_path="C:/m/MuMuManager.exe",
                               adb_path="C:/m/adb.exe", _locator=SpyLocator)
    assert captured == {"manager": "C:/m/MuMuManager.exe", "adb": "C:/m/adb.exe"}
    assert src._address == "127.0.0.1:19999"
    assert src._adb_path == "C:/m/adb.exe"
