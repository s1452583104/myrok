"""MuMu 模拟器实例自动发现（spec 2026-09-09 §3）。

通过 MuMuManager.exe 查询实例的 adb 端口。命令输出格式随 MuMu 版本可能
不同，因此对 JSON 做递归查找 adb_port/port 字段；若实机输出不一致，只需
调整 _extract_port，解析与调用已隔离。
"""
from __future__ import annotations
import glob
import json
import os
import shutil
from pathlib import Path

from .logger import get_logger
from .subproc import child_env, run as run_child  # noqa: F401  child_env 转出给老调用方

logger = get_logger(__name__)



class MumuLocatorError(RuntimeError):
    pass


class MumuNotRunningError(MumuLocatorError):
    """该模拟器存在但没在运行（因此没有 adb 端口）。

    单独一个类型，是为了让界面能把「没启动」翻译成「请先在 MuMu 里启动它」，
    而不用去匹配中文错误文本。"""
    pass


def _extract_port(obj) -> int | None:
    """Recursively find an adb port int in decoded MuMuManager JSON output."""
    if isinstance(obj, dict):
        for key in ("adb_port", "port"):
            v = obj.get(key)
            if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 65535:
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


def _extract_host(obj) -> str | None:
    """Recursively find an adb host ip string in decoded MuMuManager JSON output."""
    if isinstance(obj, dict):
        v = obj.get("adb_host_ip")
        if isinstance(v, str) and v:
            return v
        for v in obj.values():
            found = _extract_host(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _extract_host(item)
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
        # 走 infra/subproc.run：剥 QT_* + CREATE_NO_WINDOW 都由它负责。
        # 这条路径是启动和「测试连接」走的，正是用户最容易撞上的那一个。
        return run_child(args, capture_output=True, timeout=_QUERY_TIMEOUT)

    def resolve_adb_address(self, index: int) -> str:
        import subprocess
        try:
            proc = self._run([self._manager, "info", "-v", str(index)])
        except subprocess.TimeoutExpired as e:
            # **别把它说成「路径不对」**：超时说明路径是对的、程序也起来了，
            # 只是没在时限内回答。2026-10-05 有用户按「请检查安装路径」去反复
            # 改路径，其实该做的是等一会儿重试。
            raise MumuLocatorError(
                f"MuMuManager 超过 {_QUERY_TIMEOUT:.0f} 秒没有响应"
                f"（模拟器可能正忙或刚启动，稍等一会再试；"
                f"一直如此就重启 MuMu 和本程序）: {e}") from e
        except FileNotFoundError as e:
            raise MumuLocatorError(f"无法运行 MuMuManager（请检查安装路径）: {e}") from e
        except Exception as e:
            raise MumuLocatorError(f"无法运行 MuMuManager: {e}") from e
        if proc.returncode != 0:
            msg = proc.stderr.decode(errors="replace").strip() or f"returncode={proc.returncode}"
            raise MumuLocatorError(f"MuMuManager 查询实例 {index} 失败: {msg}")
        try:
            data = json.loads(proc.stdout.decode(errors="replace"))
        except json.JSONDecodeError:
            raise MumuLocatorError(
                f"MuMuManager 查询实例 {index} 输出无法解析为 JSON: {proc.stdout[:200]!r}")
        port = _extract_port(data)
        if port is None:
            # 实机上「查得到这个模拟器但没有 adb_port」= 它没在跑（见 list_instances）。
            #
            # **原始 JSON 只进日志，不进异常文本。** 这段话会一路冒到 GUI 弹窗
            # （启动时 `RuntimeCoordinator.start` 还会在前面拼上「模拟器「X」连不上」），
            # 塞 300 字符的 JSON 进去只会把用户真正要看的那句冲掉。
            # 2026-10-05 用户报「点 Start 后只连上一个，另一个成员实例报错」，
            # 最可能就是撞上这一条——而他当时看到的是一坨 JSON。
            logger.error("MuMuManager 查得到模拟器 %s 但没有 adb_port（= 没在运行）：%s",
                         index, str(data)[:300])
            raise MumuNotRunningError(
                f"模拟器 {index} 没有启动（MuMuManager 查不到它的 adb 端口）。"
                f"请先在 MuMu 里启动它，再点 Start。")
        host = _extract_host(data) or "127.0.0.1"
        return f"{host}:{port}"

    def is_running(self, index: int) -> bool:
        try:
            self.resolve_adb_address(index)
            return True
        except Exception:
            return False

    def list_instances(self) -> list[dict]:
        """列出 MuMu 里的所有模拟器（含未启动的）。见模块级 list_instances。"""
        return list_instances(self._manager, _runner=self._run)


# ---- 列出模拟器（配置界面「扫描模拟器」用） ----

# 单次 MuMuManager 查询的超时（`info -v all` 与 `info -v <n>` 共用）。
#
# **别按开发机的耗时来定这个值。** 2026-10-05 的教训：开发机上 `info -v 0`
# 只要 0.12~0.23s（n=30），我据此把超时从 10s 收到 6s，理由是「给到 6s 已经很
# 宽松」。但**打包后的 exe 跑同一条命令要 0.67~1.03s，慢 4~6 倍**——冻结进程
# 没有控制台、`_internal` 还挂在 PATH 上，起子进程本身就贵。有用户随即在启动时
# 撞上 6s 超时（见 docs/HISTORY.md 2026-10-05 续）。
#
# 10s 相对实测值留了约 10 倍余量。这条命令正常只要零点几秒，真等到 10s 说明
# MuMu 确实不对劲了；**宁可让用户多等，也不要一次假超时把启动整个打断**。
# （对话框自动扫描共用此值，最坏情况界面僵 10s 并显示等待光标——可接受。）
_QUERY_TIMEOUT = 10.0


def _default_run(args, **kwargs):
    return run_child(args, capture_output=True, timeout=_QUERY_TIMEOUT)


def _entry_index(key, entry, fallback: int) -> int | None:
    """条目自己的 index 字段优先，其次 JSON 的键（两者在实机上都是字符串）。"""
    for raw in (entry.get("index") if isinstance(entry, dict) else None, key, fallback):
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def _query_all(run, manager_path: str):
    """跑一次 `info -v all`，返回解析后的 JSON；失败抛 MumuLocatorError。

    三种失败要分清楚，因为**用户该做的事完全不同**：
    - 起不来（FileNotFoundError）→ 路径填错了
    - 超时 / 返回码非 0 → 路径没问题，是 MuMuManager 这会没起来或正忙
    - 输出不是 JSON → MuMu 版本不兼容
    """
    try:
        proc = run([manager_path, "info", "-v", "all"])
    except FileNotFoundError as e:
        raise MumuLocatorError(f"无法运行 MuMuManager（请检查安装路径）: {e}") from e
    except Exception as e:                       # 含 subprocess.TimeoutExpired
        raise MumuLocatorError(
            f"MuMuManager 没有响应（可能模拟器正忙或刚启动），请稍后重试: {e}") from e
    if proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip() or f"returncode={proc.returncode}"
        raise MumuLocatorError(
            f"MuMuManager 没有响应（可能模拟器正忙或刚启动），请稍后重试: {msg}")
    try:
        return json.loads(proc.stdout.decode(errors="replace"))
    except json.JSONDecodeError:
        raise MumuLocatorError(
            f"MuMuManager 输出无法解析为 JSON（MuMu 版本可能不兼容）: "
            f"{proc.stdout[:200]!r}")


def list_instances(manager_path: str, _runner=None) -> list[dict]:
    """列出 MuMu 里的所有模拟器，**含未启动的**，按编号升序。

    返回 `[{"index": int, "name": str, "running": bool, "adb_address": str|None}]`。

    为什么需要它：MuMu 自己的界面只显示**名字**（「如愿」「如愿-2」），从不显示
    0/1/2 编号，所以让人填「实例号」等于让人猜。界面改成按名字选。

    **未启动的模拟器在输出里没有 `adb_port` 字段**（2026-10-05 实机确认）——
    这时 `adb_address` 返回 `None` 而不是抛错，好让界面照常列出它并标「未启动」。
    """
    run = _runner if _runner is not None else _default_run
    data = _query_all(run, manager_path)

    if isinstance(data, dict):
        pairs = list(data.items())
    elif isinstance(data, list):
        pairs = [(i, e) for i, e in enumerate(data)]
    else:
        raise MumuLocatorError(f"MuMuManager 输出格式不认识: {str(data)[:200]}")

    out = []
    for i, (key, entry) in enumerate(pairs):
        if not isinstance(entry, dict):
            continue
        index = _entry_index(key, entry, i)
        if index is None:
            continue
        port = _extract_port(entry)
        out.append({
            "index": index,
            "name": str(entry.get("name") or f"模拟器{index}"),
            "running": bool(entry.get("is_android_started")),
            "adb_address": (f"{_extract_host(entry) or '127.0.0.1'}:{port}"
                            if port is not None else None),
        })
    out.sort(key=lambda e: e["index"])
    return out


# ---- 安装位置自动探测（首启生成 config.yaml 时用） ----

def _install_globs() -> list[str]:
    """MuMu 的常见安装目录 glob（MuMuManager.exe / adb.exe 都在这附近）。

    国内用户多数装在自定义目录（如 `C:\\模拟器\\MuMuPlayer`），所以除了
    Program Files 还要扫各盘根下的「模拟器」目录。
    """
    pats = []
    for base in (os.environ.get("ProgramFiles"),
                 os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            pats += [str(Path(base) / "Netease" / "MuMuPlayer*" / "shell"),
                     str(Path(base) / "Netease" / "MuMuPlayer*" / "nx_main"),
                     str(Path(base) / "MuMuPlayer*" / "nx_main")]
    for drive in ("C", "D", "E", "F", "G"):
        pats += [f"{drive}:/模拟器/MuMuPlayer*/nx_main",
                 f"{drive}:/模拟器/MuMuPlayer*",
                 f"{drive}:/MuMuPlayer*/nx_main",
                 f"{drive}:/Program Files/Netease/MuMuPlayer*/shell"]
    return pats


def _registry_dirs() -> list[Path]:
    """从注册表读安装目录（读不到就返回空，任何异常都吞掉）。"""
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    dirs = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (r"SOFTWARE\Netease\MuMuPlayer",
                    r"SOFTWARE\Netease\MuMuPlayer-12.0",
                    r"SOFTWARE\WOW6432Node\Netease\MuMuPlayer"):
            try:
                with winreg.OpenKey(hive, sub) as key:
                    for value in ("InstallDir", "install_path", "InstallPath"):
                        try:
                            d, _ = winreg.QueryValueEx(key, value)
                        except OSError:
                            continue
                        if d:
                            dirs.append(Path(str(d)))
            except OSError:
                continue
    return dirs


def _first_file(names, dirs) -> Path | None:
    for d in dirs:
        for name in names:
            p = Path(d) / name
            if p.is_file():
                return p
    return None


def _find_adb_near(manager: Path) -> str:
    """优先用 MuMu 自带的 adb（版本和它的 adb server 匹配），其次 PATH 上的。"""
    roots = [manager.parent,
             manager.parent / "vmonitor" / "bin",
             manager.parent.parent / "shell",
             manager.parent.parent / "vmonitor" / "bin"]
    for root in roots:
        p = root / "adb.exe"
        if p.is_file():
            return str(p)
    return shutil.which("adb") or ""


def detect_mumu_paths() -> dict[str, str]:
    """扫描常见安装位置，返回 `{"mumu_manager_path": ..., "adb_path": ...}`。

    探测不到的字段返回空串。**不抛异常**——探测失败只是让用户手填，
    不该阻断启动。
    """
    try:
        dirs = _registry_dirs()
        dirs += [Path(d) for pat in _install_globs() for d in glob.glob(pat)]
        manager = _first_file(["MuMuManager.exe"], dirs)
        if manager is None:
            return {"mumu_manager_path": "", "adb_path": shutil.which("adb") or ""}
        return {"mumu_manager_path": str(manager),
                "adb_path": _find_adb_near(manager)}
    except Exception:                                     # noqa: BLE001 - 探测失败不致命
        return {"mumu_manager_path": "", "adb_path": ""}
