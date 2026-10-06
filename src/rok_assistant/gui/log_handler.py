"""把日志行按「属于哪个角色」投递到 GUI 卡片。

归属靠 **worker 线程名**（`runner.py:117` 命名成
`worker:<instance_id>:<char_id>`），所以 worker 侧一行日志调用都不用改。
解析不出来的（主线程的配置加载、连不上实例等）返回空串，由调用方
决定去向（当前是状态栏）。
"""
from __future__ import annotations

_WORKER_PREFIX = "worker:"


def char_id_from_thread_name(name: str) -> str:
    """`worker:<instance_id>:<char_id>` -> `<char_id>`；其它一律返回 ""。

    char_id 自身可能含冒号，所以只切前两段，剩余整体返回。
    """
    if not name or not name.startswith(_WORKER_PREFIX):
        return ""
    rest = name[len(_WORKER_PREFIX):]
    parts = rest.split(":", 1)
    if len(parts) != 2 or not parts[1]:
        return ""
    return parts[1]
