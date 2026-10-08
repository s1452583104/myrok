"""机器指纹：主板 UUID + CPU ID → `fp_main`（32 字节）+ 机器码（17 字符）。

主项全是硬件级（主板、CPU），所以**重装系统、换硬盘、插拔网卡都不影响指纹**
——用户明确选了「不误伤重装」（spec §4.1）。`MachineGuid` 特意只放降级路径：
它随 Windows 安装生成，重装就会变。

WMI 查询在冻结包里慢（`docs/PROGRESS.md` 已知问题 10），所以一次启动只查一次。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from ..logger import get_logger
from ..subproc import run as run_proc
from . import codec

logger = get_logger(__name__)

# 只查一次、一次拿两个值。ErrorActionPreference=Stop 让 CIM 失败直接非零退出，
# 而不是打印一行错误文本让我们当成数据解析。
_WMI_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "$p=Get-CimInstance -ClassName Win32_ComputerSystemProduct;"
    "$c=Get-CimInstance -ClassName Win32_Processor;"
    "Write-Output ($p.UUID + '|' + $c.ProcessorId)"
)

_CHECK_PREFIX = b"rok-mc-check"
_PREFIX_BYTES = 10            # 80 位 → 16 个 base32 字符，刚好整除、无填充
_MACHINE_CODE_CHARS = _PREFIX_BYTES * 8 // 5 + 1     # 16 + 校验位 = 17

# 部分主板/虚拟机把 UUID 报成全 F；它不是唯一标识，必须当失败处理
_DEGENERATE = "F" * 32


@dataclass(frozen=True)
class Fingerprint:
    fp_main: bytes
    machine_code: str
    degraded: bool
    reason: str


def normalize(raw: str) -> str:
    """转大写、去空白与连字符、去 `0x` 前缀、奇数长度补零对齐。

    补零是为了让 `"ABC"` 与 `"0ABC"` 落到同一个值——否则同一台机器
    换个 WMI 版本报出不同长度，指纹就变了。
    """
    s = re.sub(r"[\s\-]", "", (raw or "")).upper()
    if s.startswith("0X"):
        s = s[2:]
    if len(s) % 2:
        s = "0" + s
    return s


def fp_main_from(mainboard_uuid: str, cpu_id: str) -> bytes:
    joined = f"{normalize(mainboard_uuid)}|{normalize(cpu_id)}".encode("utf-8")
    return hashlib.sha256(joined).digest()


def check_char(fp_main: bytes) -> str:
    """机器码第 17 位。给**人工环节**兜底：用户手抄机器码抄错一位时当场发现。

    **只吃前 10 字节**（就是机器码里显示的那 16 个字符）：发码工具只拿得到
    这 17 个字符，若校验字符依赖它看不到的另外 22 字节，工具就没法在发码前
    校验机器码了（spec §4.2 / §9）。
    """
    digest = hashlib.sha256(_CHECK_PREFIX + bytes(fp_main[:_PREFIX_BYTES])).digest()
    return codec.ALPHABET[digest[0] >> 3]


def is_valid_machine_code(text: str) -> bool:
    """只凭显示出来的 17 个字符验校验位。

    发码工具在发码前用它拦下抄错的机器码——否则会发出一个**永远激活不了**
    的码，来回一轮就是一次售后。
    """
    clean = codec.clean_input(text)
    if len(clean) != _MACHINE_CODE_CHARS:
        return False
    if any(c not in codec.ALPHABET for c in clean):
        return False
    raw = codec.b32decode_nopad(clean[:16])          # 16 字符 → 10 字节
    expected = codec.ALPHABET[
        hashlib.sha256(_CHECK_PREFIX + raw).digest()[0] >> 3]
    return expected == clean[16]


def machine_code_from(fp_main: bytes) -> str:
    body = codec.b32encode_nopad(fp_main[:_PREFIX_BYTES])   # 10 字节 → 16 字符
    return (f"{body[:4]}-{body[4:8]}-{body[8:12]}-{body[12:16]}-"
            f"{check_char(fp_main)}")


def _is_degenerate(uuid: str) -> bool:
    n = normalize(uuid)
    return not n or n.strip("F") == ""


def query_wmi() -> tuple[str, str] | None:
    """返回 `(主板 UUID, CPU ID)`；任何失败都返回 `None`（不抛）。

    走 `subproc.run`——`tests/unit/infra/test_subproc.py` 会扫 `src/` 下的裸
    `subprocess.run`，而且它会替我们剥掉 `QT_*`、加 `CREATE_NO_WINDOW`。
    """
    try:
        cp = run_proc(["powershell", "-NoProfile", "-NonInteractive",
                       "-Command", _WMI_SCRIPT],
                      capture_output=True, text=True, encoding="utf-8",
                      errors="replace", timeout=20)
    except Exception:                        # noqa: BLE001 - 超时/没有 powershell 都算降级
        logger.warning("WMI 查询异常，走降级路径", exc_info=True)
        return None
    if cp.returncode != 0:
        logger.warning("WMI 查询失败 rc=%s：%s", cp.returncode,
                       (cp.stderr or "").strip()[:200])
        return None
    lines = [ln for ln in (cp.stdout or "").strip().splitlines() if ln.strip()]
    if not lines:
        return None
    parts = lines[-1].split("|")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        logger.warning("WMI 输出无法解析：%r", lines[-1][:120])
        return None
    return parts[0].strip(), parts[1].strip()


def _machine_guid() -> str | None:
    try:
        import winreg
    except ImportError:                      # 非 Windows
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography") as k:
            value, _ = winreg.QueryValueEx(k, "MachineGuid")
        return str(value)
    except OSError:
        return None


def compute(*, cached_fp_main: bytes | None = None,
            wmi_runner=None) -> Fingerprint:
    """按 spec §4.4 的顺序解析指纹。

    顺序是**防「WMI 偶发失败白送试用期」的全部机制**：指纹一变，三处记录
    的 HMAC 全验不过，会被判成篡改（更糟的实现会当成首次运行、把试用期
    重置并覆盖掉原始记录）。所以 WMI 失败时优先用记录里缓存的指纹。
    """
    runner = wmi_runner or query_wmi
    try:
        got = runner()
    except Exception:                        # noqa: BLE001 - 注入的 runner 可能抛
        logger.warning("WMI runner 异常，走降级路径", exc_info=True)
        got = None

    if got and not _is_degenerate(got[0]):
        fp = fp_main_from(got[0], got[1])
        return Fingerprint(fp, machine_code_from(fp), False, "WMI 正常")

    if cached_fp_main:
        logger.warning("WMI 不可用，改用记录里的指纹缓存（判定为偶发故障）")
        fp = bytes(cached_fp_main)
        return Fingerprint(fp, machine_code_from(fp), True, "WMI 不可用，用缓存")

    guid = _machine_guid()
    if guid:
        logger.warning("指纹降级：WMI 不可用且无缓存，改用 MachineGuid")
        fp = fp_main_from(guid, "")
        return Fingerprint(fp, machine_code_from(fp), True,
                           "WMI 不可用且无缓存，降级用 MachineGuid")

    # 最后兜底：连 MachineGuid 都读不到（极罕见，通常是权限或损坏的 Windows）。
    # 用**固定哨兵**而不是随机值——随机值会让每次启动的指纹都不同，
    # 把用户的试用记录和激活码一起废掉，比「绑不上」更糟。启动路径**不能抛异常**。
    logger.error("无法获取机器指纹：WMI 与 MachineGuid 都不可用")
    fp = fp_main_from("ROK-NO-FINGERPRINT", "")
    return Fingerprint(fp, machine_code_from(fp), True, "指纹不可用")
