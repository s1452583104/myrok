"""MuMu 模拟器实例自动发现（spec 2026-09-09 §3）。

通过 MuMuManager.exe 查询实例的 adb 端口。命令输出格式随 MuMu 版本可能
不同，因此对 JSON 做递归查找 adb_port/port 字段；若实机输出不一致，只需
调整 _extract_port，解析与调用已隔离。
"""
from __future__ import annotations
import json


class MumuLocatorError(RuntimeError):
    pass


def _extract_port(obj) -> int | None:
    """Recursively find an adb port int in decoded MuMuManager JSON output."""
    if isinstance(obj, dict):
        for key in ("adb_port", "port"):
            v = obj.get(key)
            if isinstance(v, int):
                return v
        for v in obj.values():
            found = _extract_port(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _extract_port(item)
            if found is not None:
                return found
    return None


class MumuLocator:
    def __init__(self, mumu_manager_path: str, adb_path: str = "adb", _runner=None):
        self._manager = mumu_manager_path
        self._adb_path = adb_path  # 预留：MumuLocator 自身不发 adb 命令，供调用方组装
        self._run = _runner if _runner is not None else self._subprocess_run

    @staticmethod
    def _subprocess_run(args, **kwargs):
        import subprocess
        return subprocess.run(args, capture_output=True, timeout=10)

    def resolve_adb_address(self, index: int) -> str:
        proc = self._run([self._manager, "info", "-v", str(index)])
        if proc.returncode != 0:
            msg = proc.stderr.decode(errors="replace").strip() or f"returncode={proc.returncode}"
            raise MumuLocatorError(f"MuMuManager 查询实例 {index} 失败: {msg}")
        try:
            data = json.loads(proc.stdout.decode(errors="replace"))
        except json.JSONDecodeError:
            raise MumuLocatorError(
                f"MuMuManager 输出无法解析为 JSON: {proc.stdout[:200]!r}")
        port = _extract_port(data)
        if port is None:
            raise MumuLocatorError(f"MuMuManager 输出中未找到 adb 端口: {data}")
        return f"127.0.0.1:{port}"

    def is_running(self, index: int) -> bool:
        try:
            self.resolve_adb_address(index)
            return True
        except Exception:
            return False
