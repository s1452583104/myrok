"""起外部程序（MuMuManager / adb）的统一封装。

**所有 fork 外部程序的地方都该走这里。** 有三件事必须做对，而漏掉任何一件都
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

3. **`cwd=neutral_cwd()`：别让子进程继承 app 自己的 CWD。**
   绿色包是解压即用、双击 exe 启动的，所以 app 进程的 CWD **就是解压出来
   的那个文件夹**；子进程默认继承它。而 adb 客户端在本地没有 server 时会
   fork 出一个**常驻**的 `adb -L tcp:5037 fork-server server` 守护进程，
   它连客户端的工作目录句柄一起继承下去——Windows 不允许删除任何活进程
   还开着的目录，于是**app 退出之后那个文件夹照样删不掉**，报「另一个程序
   正在使用此文件，进程无法访问」。用户看到的现象就是「运行过一次就再也
   删不掉解压出来的文件夹」，而他已经在任务管理器里找不到我们的进程了
   （2026-10-11 用户报的正是这个）。见 `neutral_cwd()`。
"""
from __future__ import annotations

import os
import subprocess
import tempfile


def child_env() -> dict:
    """给外部程序用的环境变量：**剥掉 `QT_*`**（理由见模块 docstring）。"""
    return {k: v for k, v in os.environ.items() if not k.startswith("QT_")}


def neutral_cwd() -> str | None:
    """子进程该用的「中性」工作目录（理由见模块 docstring 第 3 条）。

    指到系统临时目录就够了：那儿本来就是「用完就扔」的，钉住它没有副作用
    （清理工具删的是里面的文件，不是它本身）。

    **不能指 app 自己的目录**，哪怕是它的子目录——子目录被钉住，父目录一样
    删不掉，等于没修。取不到临时目录就返回 None（= 维持继承，退回旧行为），
    不能因为这一步失败就把 adb 起不来。
    """
    d = tempfile.gettempdir()
    return d if os.path.isdir(d) else None


# Windows 专有；其它平台取不到就给 0（等价于不传，不影响行为）
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(args, **kwargs):
    """跑一个外部程序，自动带上 `child_env()` / `CREATE_NO_WINDOW` / 中性 CWD。

    调用方显式传的 `env` / `creationflags` / `cwd` 优先（测试要注入假 runner
    时会用到）。
    """
    kwargs.setdefault("env", child_env())
    if _NO_WINDOW:
        kwargs.setdefault("creationflags", _NO_WINDOW)
    kwargs.setdefault("cwd", neutral_cwd())
    return subprocess.run(args, **kwargs)
