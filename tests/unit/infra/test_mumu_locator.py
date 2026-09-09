import json
import pytest
from rok_assistant.infra.mumu import MumuLocator, MumuLocatorError


class FakeProc:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeRunner:
    def __init__(self, proc=None, error=None):
        self.proc = proc or FakeProc()
        self.error = error
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.proc


def _json_bytes(d) -> bytes:
    return json.dumps(d).encode("utf-8")


def test_resolve_parses_nested_adb_port():
    out = _json_bytes({"index": 0, "adb": {"adb_port": 16384}})
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(FakeProc(stdout=out)))
    assert loc.resolve_adb_address(0) == "127.0.0.1:16384"


def test_resolve_accepts_top_level_port_key():
    out = _json_bytes({"port": 16385})
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(FakeProc(stdout=out)))
    assert loc.resolve_adb_address(1) == "127.0.0.1:16385"


def test_resolve_uses_adb_host_ip_when_present():
    out = _json_bytes({"adb_host_ip": "192.168.1.5", "adb_port": 16384})
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(FakeProc(stdout=out)))
    assert loc.resolve_adb_address(0) == "192.168.1.5:16384"


def test_resolve_passes_index_to_manager():
    runner = FakeRunner(FakeProc(stdout=_json_bytes({"adb_port": 16384})))
    loc = MumuLocator("C:/mumu/MuMuManager.exe", _runner=runner)
    loc.resolve_adb_address(2)
    assert runner.calls[0][:4] == ["C:/mumu/MuMuManager.exe", "info", "-v", "2"]


def test_resolve_nonzero_returncode_raises():
    proc = FakeProc(stderr="instance not found".encode(), returncode=1)
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(proc))
    with pytest.raises(MumuLocatorError, match="失败"):
        loc.resolve_adb_address(9)


def test_resolve_non_json_output_raises():
    proc = FakeProc(stdout=b"not json at all")
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(proc))
    with pytest.raises(MumuLocatorError, match="JSON"):
        loc.resolve_adb_address(0)


def test_resolve_missing_port_raises():
    proc = FakeProc(stdout=_json_bytes({"foo": "bar"}))
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(proc))
    with pytest.raises(MumuLocatorError, match="端口"):
        loc.resolve_adb_address(0)


def test_is_running_true_and_false():
    ok = MumuLocator("m", _runner=FakeRunner(FakeProc(stdout=_json_bytes({"adb_port": 16384}))))
    assert ok.is_running(0) is True
    bad = MumuLocator("m", _runner=FakeRunner(FakeProc(returncode=1)))
    assert bad.is_running(0) is False
    crash = MumuLocator("m", _runner=FakeRunner(error=FileNotFoundError("no exe")))
    assert crash.is_running(0) is False
