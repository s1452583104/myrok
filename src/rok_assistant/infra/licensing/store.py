"""三处冗余存储 + HMAC 校验 + 取最早 + 自愈补写。

三处（spec §5.1）：

    1. 注册表 HKCU\\Software\\RoKAssistant\\License   重新解压清不掉
    2. C:\\ProgramData\\RoKAssistant\\license.dat      重新解压清不掉
    3. <user_dir>\\.roklicense                         重新解压会清掉

**重新解压只会清掉第 3 处，1 和 2 留着——这就是防「解压刷新试用期」的全部机制。**

写入失败（如 ProgramData 无权限）静默跳过、只记日志；剩两处照常工作。
"""
from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..app_paths import user_dir
from ..logger import get_logger
from . import codec

logger = get_logger(__name__)

try:
    import winreg
except ImportError:                       # 非 Windows：注册表这一处直接缺席
    winreg = None

RECORD_VERSION = 1
_HMAC_SALT = b"rok-lic-v1"
_HMAC_BYTES = 16

_REG_PATH = r"Software\RoKAssistant\License"
_REG_VALUE = "state"
_PROGRAM_DATA = Path(r"C:\ProgramData\RoKAssistant\license.dat")
_USER_FILE_NAME = ".roklicense"

_ATTR_NORMAL = 0x80
_ATTR_HIDDEN = 0x02
_ATTR_SYSTEM = 0x04


def _set_attrs(path: Path, attrs: int) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)
    except Exception:                     # noqa: BLE001 - 只是隐藏，失败无所谓
        logger.debug("设置文件属性失败：%s", path)


class _RegistrySlot:
    """注册表：**重新解压清不掉**的那一处。值以 base64 存，避免 JSON 里的
    反斜杠/引号被 REG_SZ 的解析规则弄坏。"""

    def __init__(self, path: str, value: str):
        self._path = path
        self._value = value

    def load(self) -> str | None:
        if winreg is None:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._path) as k:
                raw, _ = winreg.QueryValueEx(k, self._value)
        except OSError:
            return None
        try:
            return base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    def save(self, text: str) -> None:
        if winreg is None:
            return
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self._path) as k:
                winreg.SetValueEx(
                    k, self._value, 0, winreg.REG_SZ,
                    base64.b64encode(text.encode("utf-8")).decode("ascii"))
        except OSError:
            logger.warning("注册表写入失败，跳过这一处：%s", self._path)

    def mtime(self) -> float | None:
        return None                       # 注册表没有 mtime，时钟校验跳过它


class _FileSlot:
    def __init__(self, path: Path, attrs: int):
        self._path = path
        self._attrs = attrs

    def load(self) -> str | None:
        try:
            return self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def save(self, text: str) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 带 HIDDEN|SYSTEM 的文件在这台机器上无法用 O_TRUNC 打开
            # （`write_text` 就是 O_TRUNC）——本方法上一轮刚给它设过这两个属性，
            # 不先摘掉的话第二次保存会 PermissionError 被 except OSError 静默吞掉，
            # 三处冗余只剩注册表一处还在更新。写完再戴回去。
            _set_attrs(self._path, _ATTR_NORMAL)
            self._path.write_text(text, encoding="utf-8")
        except OSError:
            logger.warning("授权记录写入失败，跳过这一处：%s", self._path)
            return
        _set_attrs(self._path, self._attrs)

    def mtime(self) -> float | None:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return None


@dataclass(frozen=True)
class Locations:
    registry: tuple[str, str] | None = None
    program_data: Path | None = None
    user_file: Path | None = None


def default_locations() -> Locations:
    return Locations(registry=(_REG_PATH, _REG_VALUE),
                     program_data=_PROGRAM_DATA,
                     user_file=user_dir() / _USER_FILE_NAME)


@dataclass
class Record:
    trial_start: int
    last_seen: int
    licenses: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ReadResult:
    exists: bool
    valid: bool
    tampered: bool
    record: Record | None


# ---------------- 编解码 / 校验 ----------------

def _fingerprint_tag(fp_main: bytes) -> str:
    # 存**完整 32 字节**（64 hex），不是摘要的摘要：spec §4.4 的指纹缓存
    # 要拿它当整份 fp_main 用，只存 8 字节的话缓存就废了。
    return bytes(fp_main).hex()


def _hmac_key(fp_main: bytes) -> bytes:
    return hashlib.sha256(bytes(fp_main) + _HMAC_SALT).digest()


def _canonical(obj: dict) -> bytes:
    body = {k: v for k, v in obj.items() if k != "hmac"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hmac_for(obj: dict, fp_main: bytes) -> str:
    return hmac_mod.new(_hmac_key(fp_main), _canonical(obj),
                        hashlib.sha256).hexdigest()[:_HMAC_BYTES * 2]


def _serialize(rec: Record, fp_main: bytes) -> str:
    obj = {"v": RECORD_VERSION,
           "fp": _fingerprint_tag(fp_main),
           "trial_start": int(rec.trial_start),
           "last_seen": int(rec.last_seen),
           "licenses": [{"code": str(c["code"]), "applied_at": int(c["applied_at"])}
                        for c in rec.licenses]}
    obj["hmac"] = _hmac_for(obj, fp_main)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _parse(text: str | None) -> dict | None:
    """结构与版本闸门。返回 None 表示「**当作不存在**」，**不是**篡改。

    这一层必须和 HMAC 校验分开（spec §5.3.1）：认得出、结构完整、但 HMAC
    对不上才是篡改；版本号不认识或 JSON 坏了要当成「没有记录」，否则将来
    记录格式升级到 v2 时，用户一升级程序就会被当场锁死。
    """
    if not text:
        return None
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or obj.get("v") != RECORD_VERSION:
        return None
    for key in ("fp", "trial_start", "last_seen", "licenses", "hmac"):
        if key not in obj:
            return None
    if not isinstance(obj["licenses"], list):
        return None
    for item in obj["licenses"]:
        if not isinstance(item, dict) or "code" not in item \
                or "applied_at" not in item:
            return None
    return obj


def _verify(obj: dict, fp_main: bytes) -> bool:
    if obj["fp"] != _fingerprint_tag(fp_main):
        return False
    return hmac_mod.compare_digest(obj["hmac"], _hmac_for(obj, fp_main))


def _to_record(obj: dict) -> Record:
    return Record(trial_start=int(obj["trial_start"]),
                  last_seen=int(obj["last_seen"]),
                  licenses=[{"code": str(c["code"]),
                             "applied_at": int(c["applied_at"])}
                            for c in obj["licenses"]])


def _merge(records: list[Record]) -> Record:
    """取最早 trial_start、最大 last_seen、licenses 按 serial 并集去重。

    同一 serial 出现多次时取 `applied_at` **较小**的那条——与「取最早」
    同向的保守选择（spec §5.3）。
    """
    by_serial: dict[int, dict] = {}
    for rec in records:
        for item in rec.licenses:
            serial = codec.serial_of(item["code"])
            if serial is None:
                continue                  # 解析不了的码留着也没用
            old = by_serial.get(serial)
            if old is None or item["applied_at"] < old["applied_at"]:
                by_serial[serial] = {"code": item["code"],
                                     "applied_at": item["applied_at"]}
    return Record(trial_start=min(r.trial_start for r in records),
                  last_seen=max(r.last_seen for r in records),
                  licenses=list(by_serial.values()))


class Store:
    def __init__(self, locations: Locations):
        self._locations = locations
        self._slots: list = []
        if locations.registry is not None:
            self._slots.append(_RegistrySlot(*locations.registry))
        if locations.program_data is not None:
            self._slots.append(_FileSlot(locations.program_data,
                                         _ATTR_HIDDEN | _ATTR_SYSTEM))
        if locations.user_file is not None:
            self._slots.append(_FileSlot(locations.user_file, _ATTR_HIDDEN))

    def cached_fp_main(self) -> bytes | None:
        """从任意可解析的记录里取指纹缓存。

        **不验 HMAC**——验它需要指纹本身，而那正是我们要取的东西。不验也是
        安全的：攻击者改掉缓存里的 fp 只会让自己的激活码绑不上（spec §4.4）。
        """
        for slot in self._slots:
            obj = _parse(slot.load())
            if obj is None:
                continue
            try:
                raw = bytes.fromhex(obj["fp"])
            except ValueError:
                continue
            if len(raw) == 32:
                return raw
        return None

    def read(self, fp_main: bytes) -> ReadResult:
        found = False
        recognized_but_invalid = False
        records: list[Record] = []
        for slot in self._slots:
            text = slot.load()
            if text is None:
                continue
            found = True
            obj = _parse(text)
            if obj is None:
                continue                  # 认不出 → 当作不存在
            if not _verify(obj, fp_main):
                recognized_but_invalid = True   # 认得出、结构完整、验不过 → 篡改
                continue
            records.append(_to_record(obj))

        if not records:
            # 「都不存在」与「都存在但全是假的」绝不能混（spec §5.3.1）：混了
            # 就等于给了一条「把记录改坏即可重置试用期」的路径。
            return ReadResult(exists=found, valid=False,
                              tampered=recognized_but_invalid, record=None)

        merged = _merge(records)
        self.write(fp_main, merged)       # 自愈：补写被删/损坏的那几处
        return ReadResult(exists=True, valid=True, tampered=False, record=merged)

    def write(self, fp_main: bytes, rec: Record) -> None:
        text = _serialize(rec, fp_main)
        for slot in self._slots:
            slot.save(text)               # 单处失败已在 slot 内静默

    def newest_mtime(self) -> float | None:
        times = [t for t in (s.mtime() for s in self._slots) if t is not None]
        return max(times) if times else None
