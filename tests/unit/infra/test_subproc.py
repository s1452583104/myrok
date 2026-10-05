"""起外部程序的统一封装。

这组测试守的是**只在打包后才暴露**的两个坑——源码模式下父进程有控制台、
环境也干净，怎么跑都对，所以必须有单测把这两个标志钉住：

1. 漏掉 `CREATE_NO_WINDOW` → 打包后每调一次 adb 就闪一个黑窗
   （2026-10-05 用户报「点击 start 后一直有黑色弹窗一闪而过」）。
2. 漏掉剥 `QT_*` → MuMuManager 当场崩（rc=3221226505）。
"""
import os
import subprocess

import pytest

from rok_assistant.infra import subproc


class FakeProc:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def spy(monkeypatch):
    """拦下真正的 subprocess.run，记下 kwargs。"""
    seen = {}

    def _fake(args, **kwargs):
        seen["args"] = args
        seen.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(subprocess, "run", _fake)
    return seen


def test_run_always_passes_create_no_window(spy):
    """少了这个，打包后每调一次外部程序就闪一个黑控制台窗。"""
    subproc.run(["adb", "devices"])
    assert spy["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_run_strips_qt_vars(spy, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    subproc.run(["adb", "devices"])
    assert "QT_QPA_PLATFORM" not in spy["env"]


def test_run_keeps_the_rest_of_the_environment(spy, monkeypatch):
    monkeypatch.setenv("ROK_PROBE", "1")
    subproc.run(["adb", "devices"])
    assert spy["env"].get("ROK_PROBE") == "1", "别把环境整个换掉，子进程还要 PATH"


def test_caller_can_override(spy):
    """显式传的优先——测试注入假 runner 时要用。"""
    subproc.run(["adb"], env={"X": "1"}, creationflags=0)
    assert spy["env"] == {"X": "1"}
    assert spy["creationflags"] == 0


# ---- 两个真实调用点都得走到 run() 上，不能各写各的 ----

def test_adb_handle_source_hot_path_uses_no_window(spy):
    """热路径：每截一帧 / 每点一下都起一次 adb。"""
    from rok_assistant.core.handle_source import AdbHandleSource
    AdbHandleSource._subprocess_run(["adb", "devices"])
    assert spy["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert "QT_" not in " ".join(spy["env"])


def test_mumu_locator_uses_no_window(spy):
    """启动和「测试连接」走的这条。"""
    from rok_assistant.infra.mumu import MumuLocator
    MumuLocator._subprocess_run(["MuMuManager.exe", "info", "-v", "all"])
    assert spy["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_mumu_default_run_uses_no_window(spy):
    from rok_assistant.infra.mumu import _default_run
    _default_run(["MuMuManager.exe", "info", "-v", "all"])
    assert spy["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_no_bare_subprocess_calls_left_in_src():
    """防止以后有人新写一个调用点时又忘了带标志。"""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[3] / "src"
    offenders = []
    for py in root.rglob("*.py"):
        if py.name == "subproc.py":
            continue
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"subprocess\.(run|Popen)\(", line):
                offenders.append(f"{py.relative_to(root)}:{i}")
    assert not offenders, (
        "这些地方直接用了 subprocess，会漏掉 CREATE_NO_WINDOW / 剥 QT_*，"
        f"请改走 infra.subproc.run：{offenders}")


def test_child_env_reexported_from_mumu():
    """老调用方 still import child_env from mumu——别断。"""
    from rok_assistant.infra.mumu import child_env as from_mumu
    assert from_mumu is subproc.child_env
