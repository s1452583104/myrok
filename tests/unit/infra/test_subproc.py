"""起外部程序的统一封装。

这组测试守的是**只在打包后才暴露**的三个坑——源码模式下父进程有控制台、
环境也干净、CWD 也是仓库而不是解压目录，怎么跑都对，所以必须有单测把这三
个标志钉住：

1. 漏掉 `CREATE_NO_WINDOW` → 打包后每调一次 adb 就闪一个黑窗
   （2026-10-05 用户报「点击 start 后一直有黑色弹窗一闪而过」）。
2. 漏掉剥 `QT_*` → MuMuManager 当场崩（rc=3221226505）。
3. 漏掉中性 `cwd` → adb 守护进程继承 app 的 CWD（= 解压目录）并一直钉着
   它，app 退出后那个文件夹删不掉（2026-10-11 用户报）。
"""
import os
import subprocess
import sys

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
    subproc.run(["adb"], env={"X": "1"}, creationflags=0, cwd="C:\\")
    assert spy["env"] == {"X": "1"}
    assert spy["creationflags"] == 0
    assert spy["cwd"] == "C:\\"


# ---- 子进程别继承 app 的 CWD（否则解压出来的文件夹删不掉） ----

def test_run_does_not_inherit_the_app_cwd(spy):
    """打包后 app 的 CWD 就是解压目录，继承下去会被 adb 守护进程钉住。"""
    subproc.run(["adb", "devices"])
    assert spy["cwd"], "必须显式给 cwd，不能让它继承 app 的 CWD"
    assert os.path.isdir(spy["cwd"]), "cwd 不存在的话 CreateProcess 直接失败"


def test_neutral_cwd_is_not_the_app_dir_or_below_it():
    """**不能指 app 目录，子目录也不行**：子目录被钉住，父目录一样删不掉。"""
    cwd = subproc.neutral_cwd()
    if cwd is None:
        pytest.skip("取不到临时目录，此时退回继承（见 neutral_cwd docstring）")
    app_dir = os.path.normcase(os.path.abspath(os.getcwd()))   # 双击启动时 = 解压目录
    got = os.path.normcase(os.path.abspath(cwd))
    assert got != app_dir
    assert not got.startswith(app_dir + os.sep), \
        f"中性 CWD {got} 在 app 目录 {app_dir} 里面，等于没修"


def test_real_child_really_lands_in_the_neutral_cwd():
    """真起一个进程问它 `os.getcwd()`——spy 只能证明我们**传了** cwd，
    证明不了 CreateProcess 真的照做了。"""
    if subproc.neutral_cwd() is None:
        pytest.skip("取不到临时目录")
    proc = subproc.run([sys.executable, "-c", "import os; print(os.getcwd())"],
                       capture_output=True, timeout=60)
    child_cwd = proc.stdout.decode(errors="replace").strip()
    assert child_cwd, f"子进程没打印 CWD：{proc.stderr.decode(errors='replace')[:200]}"
    assert os.path.normcase(child_cwd) != os.path.normcase(os.getcwd()), \
        "子进程落在了 app 的 CWD 里——adb 守护进程会照样钉住解压目录"


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
