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
    args = fake.calls[0]
    assert "exec-out" in args
    assert "screencap" in args
    assert "-s" in args
    assert "127.0.0.1:16384" in args


def test_click_uses_input_tap():
    fake = FakeAdb()
    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb", _runner=fake)
    src.click(500, 300)
    args = fake.calls[0]
    assert "shell" in args and "input" in args and "tap" in args
    assert "500" in args and "300" in args


def test_swipe_uses_input_swipe():
    fake = FakeAdb()
    src = AdbHandleSource(adb_address="127.0.0.1:16384", adb_path="adb", _runner=fake)
    src.swipe(10, 20, 300, 400, duration_ms=500)
    args = fake.calls[0]
    assert "swipe" in args
    assert "500" in args


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
