"""Tests for list_instances() — 配置界面「扫描模拟器」的数据源。

喂进去的 JSON 是 2026-10-05 在实机上跑
`MuMuManager.exe info -v all` 原样拿到的，不是编的：
编号 0「如愿」在跑（有 adb_port），编号 1/2 没启动（**没有 adb_port 字段**）。
"""
import json
import os
import subprocess
import pytest
from rok_assistant.infra.mumu import (
    MumuLocator, MumuLocatorError, MumuNotRunningError, child_env, list_instances,
)

# 实机输出（去掉与本次无关的大数字段，保留全部键名与类型）
REAL_ALL = {
    "0": {
        "adb_host_ip": "127.0.0.1", "adb_port": 16384, "android_version": "15.0",
        "error_code": 0, "index": "0", "is_android_started": True,
        "is_main": False, "is_process_started": True, "name": "如愿",
        "player_state": "start_finished",
    },
    "1": {
        "android_version": "15.0", "error_code": 0, "index": "1",
        "is_android_started": False, "is_main": False, "is_process_started": False,
        "name": "15634025219",
    },
    "2": {
        "android_version": "15.0", "error_code": 0, "index": "2",
        "is_android_started": False, "is_main": False, "is_process_started": False,
        "name": "如愿-2",
    },
}


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


def _run_json(d) -> FakeRunner:
    return FakeRunner(FakeProc(stdout=json.dumps(d).encode("utf-8")))


def test_lists_running_and_stopped_instances():
    """未启动的也要列出来——用户得看见自己的「如愿-2」才能选它。"""
    got = list_instances("MuMuManager.exe", _runner=_run_json(REAL_ALL))
    assert got == [
        {"index": 0, "name": "如愿", "running": True,
         "adb_address": "127.0.0.1:16384"},
        {"index": 1, "name": "15634025219", "running": False, "adb_address": None},
        {"index": 2, "name": "如愿-2", "running": False, "adb_address": None},
    ]


def test_uses_all_flag_not_single_index():
    runner = _run_json(REAL_ALL)
    list_instances("C:/m/MuMuManager.exe", _runner=runner)
    assert runner.calls[0] == ["C:/m/MuMuManager.exe", "info", "-v", "all"]


def test_stopped_instance_does_not_raise():
    """没有 adb_port 是「没启动」，不是错误——resolve_adb_address 才抛。"""
    got = list_instances("m", _runner=_run_json(REAL_ALL))
    assert [e["adb_address"] for e in got] == ["127.0.0.1:16384", None, None]


def test_sorted_by_index_even_when_json_is_unordered():
    shuffled = {"2": REAL_ALL["2"], "0": REAL_ALL["0"], "1": REAL_ALL["1"]}
    got = list_instances("m", _runner=_run_json(shuffled))
    assert [e["index"] for e in got] == [0, 1, 2]


def test_accepts_list_payload():
    """有的版本可能直接吐数组；不能因此挂掉。"""
    payload = [{"index": "1", "name": "b", "is_android_started": False},
               {"index": "0", "name": "a", "is_android_started": True,
                "adb_port": 16384}]
    got = list_instances("m", _runner=_run_json(payload))
    assert [e["name"] for e in got] == ["a", "b"]
    assert got[0]["adb_address"] == "127.0.0.1:16384"


def test_empty_dict_returns_empty_list():
    """一个模拟器都没建时不该报错，界面显示「还没有模拟器」。"""
    assert list_instances("m", _runner=_run_json({})) == []


def test_uses_adb_host_ip_when_present():
    payload = {"0": {"index": "0", "name": "x", "is_android_started": True,
                     "adb_host_ip": "192.168.1.5", "adb_port": 16384}}
    got = list_instances("m", _runner=_run_json(payload))
    assert got[0]["adb_address"] == "192.168.1.5:16384"


def test_falls_back_to_placeholder_name():
    payload = {"0": {"index": "0", "is_android_started": False}}
    got = list_instances("m", _runner=_run_json(payload))
    assert got[0]["name"] == "模拟器0"


def test_skips_non_dict_entries():
    payload = {"0": REAL_ALL["0"], "junk": "not a dict"}
    got = list_instances("m", _runner=_run_json(payload))
    assert [e["index"] for e in got] == [0]


def test_missing_manager_path_raises_human_message():
    runner = FakeRunner(error=FileNotFoundError(2, "系统找不到指定的文件"))
    with pytest.raises(MumuLocatorError, match="无法运行 MuMuManager"):
        list_instances("C:/nope/MuMuManager.exe", _runner=runner)


def test_nonzero_returncode_raises_retryable_message():
    """返回码非 0 时路径是好的，不能让用户去改路径——要说「稍后重试」。"""
    runner = FakeRunner(FakeProc(stderr="boom".encode(), returncode=1))
    with pytest.raises(MumuLocatorError, match="稍后重试"):
        list_instances("m", _runner=runner)


def test_non_json_output_raises():
    runner = FakeRunner(FakeProc(stdout=b"<html>nope</html>"))
    with pytest.raises(MumuLocatorError, match="JSON"):
        list_instances("m", _runner=runner)


def test_scalar_payload_raises():
    with pytest.raises(MumuLocatorError, match="格式"):
        list_instances("m", _runner=_run_json(42))


# ---- 未启动 ≠ 端口缺失的通用错误：界面靠类型来翻译文案 ----

def test_resolve_missing_port_raises_not_running_subtype():
    runner = _run_json({"index": "2", "name": "如愿-2", "is_android_started": False})
    loc = MumuLocator("m", _runner=runner)
    with pytest.raises(MumuNotRunningError):
        loc.resolve_adb_address(2)
    # 仍是 MumuLocatorError 的子类，老调用方的 except 不受影响
    assert issubclass(MumuNotRunningError, MumuLocatorError)


def test_not_running_message_is_actionable_and_has_no_json_dump():
    """这段文本会冒到 GUI 弹窗，不能塞原始 JSON。

    2026-10-05 用户报「另一个成员实例报错」，最可能就是这一条——而他看到的是
    一坨 300 字符的 JSON。原始数据该进日志。
    """
    payload = {"index": "2", "name": "如愿-2", "is_android_started": False,
               "extra": "x" * 300}
    loc = MumuLocator("m", _runner=_run_json(payload))
    with pytest.raises(MumuNotRunningError) as ei:
        loc.resolve_adb_address(2)
    msg = str(ei.value)
    assert "没有启动" in msg, f"没说清是哪一步：{msg}"
    assert "先在 MuMu 里启动" in msg, f"没给出下一步动作：{msg}"
    # 配置对话框靠这两个词来翻译文案，别改掉
    assert "adb 端口" in msg, f"config_dialog 的匹配词没了：{msg}"
    assert "xxxx" not in msg, f"原始 JSON 漏进用户可见文本了：{msg}"


def test_locator_list_instances_uses_own_runner():
    loc = MumuLocator("m", _runner=_run_json(REAL_ALL))
    got = loc.list_instances()
    assert [e["name"] for e in got] == ["如愿", "15634025219", "如愿-2"]


def test_locator_list_instances_wraps_crash():
    loc = MumuLocator("m", _runner=FakeRunner(
        error=subprocess.TimeoutExpired(cmd="x", timeout=10)))
    with pytest.raises(MumuLocatorError, match="稍后重试"):
        loc.list_instances()


# ---- 子进程环境（2026-10-05 实机定位的崩溃根因）----

def test_child_env_strips_qt_vars():
    """MuMuManager 自己就是 Qt 程序：父进程带着 QT_QPA_PLATFORM 时它会去加载
    对应的平台插件，插件不在它目录里就当场崩（实测 rc=3221226505 / 卡死）。"""
    old = os.environ.get("QT_QPA_PLATFORM")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_QPA_FONTDIR"] = "C:/whatever"
    try:
        env = child_env()
        assert "QT_QPA_PLATFORM" not in env
        assert "QT_QPA_FONTDIR" not in env
    finally:
        os.environ.pop("QT_QPA_FONTDIR", None)
        if old is None:
            os.environ.pop("QT_QPA_PLATFORM", None)
        else:
            os.environ["QT_QPA_PLATFORM"] = old


def test_child_env_keeps_unrelated_vars():
    """别把 PATH / SystemRoot 也剥了——那样 MuMuManager 起不来。"""
    env = child_env()
    assert env, "环境不能整个清空"
    assert any(k.upper() == "PATH" for k in env)


def test_default_run_passes_sanitized_env(monkeypatch):
    """默认 runner 必须把 QT_* 剥掉再交给子进程。"""
    import subprocess as sp
    from rok_assistant.infra import mumu
    seen = {}
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    def _fake_run(args, **kwargs):
        seen.update(kwargs)
        return FakeProc(stdout=json.dumps(REAL_ALL).encode("utf-8"))

    monkeypatch.setattr(sp, "run", _fake_run)
    got = mumu.list_instances("m")
    assert "QT_QPA_PLATFORM" not in seen["env"]
    assert len(got) == 3


def test_locator_default_runner_also_strips_qt(monkeypatch):
    """「测试连接」走的是 MumuLocator 自己的 runner——同一条命，同样要剥。"""
    import subprocess as sp
    from rok_assistant.infra.mumu import MumuLocator
    seen = {}
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    def _fake_run(args, **kwargs):
        seen.update(kwargs)
        return FakeProc(stdout=json.dumps(REAL_ALL["0"]).encode("utf-8"))

    monkeypatch.setattr(sp, "run", _fake_run)
    addr = MumuLocator("m").resolve_adb_address(0)
    assert addr == "127.0.0.1:16384"
    assert "QT_QPA_PLATFORM" not in seen["env"]
