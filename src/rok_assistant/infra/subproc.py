"""起外部程序（MuMuManager / adb）的统一封装。

**所有 fork 外部程序的地方都该走这里。** 有两件事必须做对，而漏掉任何一件都
**只在打包后才暴露**——从终端跑源码时一切正常，所以开发时看不见：

1. **`env=child_env()`：剥掉 `QT_*`。**
   MuMuManager.exe 自己就是 Qt 程序；父进程（我们的 PyQt6 GUI）一旦带着
   `QT_QPA_PLATFORM` 之类的变量，子进程会去加载对应的平台插件，插件不在它
   自己目录里就**当场崩掉**（实测 rc=3221226505）或者卡死不返回。
   见 docs/HISTORY.md 2026-10-05。

2. **`creationflags=CREATE_NO_WINDOW`：别给子进程分配控制台窗口。**
   绿色包是 `console=False` 的 GUI 程序，**自身没有控制台**；而 adb.exe 和
   MuMuManager.exe 都是**控制台子系统**程序（PE Subsystem=3）。父进程没有
   控制台时，Windows 会给每个这样的子进程**新开一个控制台窗口**——
   2026-10-05 实测窗口类为 `PseudoConsoleWindow`、`visible=True`。
   adb 每截一帧、每点一下都要起一次，于是用户看到的是**黑窗一闪一闪、
   持续不断**（2026-10-05 用户报「点击 start 后一直有黑色弹窗一闪而过」）。
   加上这个标志后实测子进程窗口数 = 0。
"""
from __future__ import annotations

import os
import subprocess


def child_env() -> dict:
    """给外部程序用的环境变量：**剥掉 `QT_*`**（理由见模块 docstring）。"""
    return {k: v for k, v in os.environ.items() if not k.startswith("QT_")}


# Windows 专有；其它平台取不到就给 0（等价于不传，不影响行为）
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(args, **kwargs):
    """跑一个外部程序，自动带上 `child_env()` 与 `CREATE_NO_WINDOW`。

    调用方显式传的 `env` / `creationflags` 优先（测试要注入假 runner 时会用到）。
    """
    kwargs.setdefault("env", child_env())
    if _NO_WINDOW:
        kwargs.setdefault("creationflags", _NO_WINDOW)
    return subprocess.run(args, **kwargs)
