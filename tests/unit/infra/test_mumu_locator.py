import json
import subprocess
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


def test_resolve_rejects_string_port():
    proc = FakeProc(stdout=_json_bytes({"adb_port": "16384"}))
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(proc))
    with pytest.raises(MumuLocatorError, match="端口"):
        loc.resolve_adb_address(0)


def test_resolve_rejects_bool_port():
    proc = FakeProc(stdout=_json_bytes({"adb_port": True}))
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(proc))
    with pytest.raises(MumuLocatorError, match="端口"):
        loc.resolve_adb_address(0)


def test_resolve_rejects_out_of_range_port():
    proc = FakeProc(stdout=_json_bytes({"adb_port": 99999}))
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(proc))
    with pytest.raises(MumuLocatorError, match="端口"):
        loc.resolve_adb_address(0)


def test_resolve_timeout_does_not_blame_the_path():
    """超时 ≠ 路径错。

    2026-10-05 有用户拿到「请检查安装路径」后去反复改路径，其实路径是对的。
    超时要说「没响应、稍后重试」，不能把人往错的方向带。
    """
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(
        error=subprocess.TimeoutExpired(cmd="x", timeout=10)))
    with pytest.raises(MumuLocatorError) as ei:
        loc.resolve_adb_address(0)
    msg = str(ei.value)
    assert "没有响应" in msg
    assert "路径" not in msg, f"超时不该提路径：{msg}"


def test_resolve_missing_exe_still_blames_the_path():
    """真·路径错的时候还得说路径——别把两种情况搞成一锅粥。"""
    loc = MumuLocator("C:/nope/MuMuManager.exe", _runner=FakeRunner(
        error=FileNotFoundError(2, "系统找不到指定的文件")))
    with pytest.raises(MumuLocatorError, match="安装路径"):
        loc.resolve_adb_address(0)


def test_query_timeout_leaves_room_for_frozen_slowness():
    """别再把超时按开发机耗时收紧。

    打包后的 exe 跑同一条命令实测 0.67~1.03s，开发机只要 0.12~0.23s。
    按开发机数字定超时会假超时——2026-10-05 就是这么把用户启动打断的。
    """
    from rok_assistant.infra.mumu import _QUERY_TIMEOUT
    assert _QUERY_TIMEOUT >= 10.0, "低于 10s 会在慢机器 / 冻结包里假超时"


def test_resolve_nonzero_returncode_falls_back_to_returncode():
    proc = FakeProc(stderr=b"", returncode=1)
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(proc))
    with pytest.raises(MumuLocatorError, match="returncode="):
        loc.resolve_adb_address(0)


def test_resolve_uses_nested_adb_host_ip():
    out = _json_bytes({"index": 0, "adb": {"adb_host_ip": "10.0.0.2", "adb_port": 16384}})
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(FakeProc(stdout=out)))
    assert loc.resolve_adb_address(0) == "10.0.0.2:16384"


def test_is_running_false_on_non_json_payload():
    proc = FakeProc(stdout=b"not json at all")
    loc = MumuLocator("m", _runner=FakeRunner(proc))
    assert loc.is_running(0) is False


def test_is_running_true_and_false():
    ok = MumuLocator("m", _runner=FakeRunner(FakeProc(stdout=_json_bytes({"adb_port": 16384}))))
    assert ok.is_running(0) is True
    bad = MumuLocator("m", _runner=FakeRunner(FakeProc(returncode=1)))
    assert bad.is_running(0) is False
    crash = MumuLocator("m", _runner=FakeRunner(error=FileNotFoundError("no exe")))
    assert crash.is_running(0) is False
