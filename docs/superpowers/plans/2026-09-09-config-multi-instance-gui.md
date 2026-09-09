# 配置重构：多实例管理 + 弹性角色 + GUI 可视化配置 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/superpowers/specs/2026-09-09-config-multi-instance-gui-design.md` 重构配置层（instances / role=either / 显式填兵目标 / 全局 MuMu 字段）、新增 MuMu 实例自动发现、EitherStateMachine、以及左树右表单的 GUI 配置对话框。

**Architecture:** pydantic schema 全量替换（accounts→instances，交叉校验上移 RootConfig）；`MumuLocator` 封装 MuMuManager 命令行（fake runner 可测）；`create_handle_source` 支持 mumu_index 解析；`EitherStateMachine` 以委托组合 Leader/Member 两个状态机；GUI 用 dict 模式（`model_dump` + 表单写回 dict + 保存时 `model_validate`），编辑不经过 pydantic 对象。

**Tech Stack:** Python 3.11+, pydantic v2, PyQt6, PyYAML, OpenCV（连接测试截图），pytest。

**约定（每个任务通用）：**
- 工作目录 `C:\coding\workspace\git\myrok`；跑测试命令 `python -m pytest <路径> -v`
- 全量回归 `python -m pytest tests/ -q`，当前基线 91 passed
- GUI 测试需要 `QT_QPA_PLATFORM=offscreen`（在测试文件顶部 `os.environ.setdefault` 设置）
- Windows bash 环境；yaml 写文件用 utf-8

---

### Task 1: 配置 schema 全量重构

**Files:**
- Modify: `src/rok_assistant/infra/config.py`（全量替换）
- Replace: `tests/unit/infra/test_config_models.py`（全量替换）
- Replace: `tests/fixtures/config_valid.yaml`, `tests/fixtures/config_no_leader.yaml`, `tests/fixtures/config_invalid_level.yaml`
- Modify: `tests/unit/infra/test_config_loader.py`

- [ ] **Step 1: 重写 `tests/unit/infra/test_config_models.py`（失败的测试）**

```python
import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import (
    AppConfig, InstanceConfig, CharacterConfig, RoleEnum, FillLeader, RootConfig
)


def _leader(**kw):
    base = dict(id="c1", name="Hero", role=RoleEnum.LEADER, target_level=8,
                march_preset=1, march_troop_types=["infantry"])
    base.update(kw)
    return CharacterConfig(**base)


def _member(**kw):
    base = dict(id="c2", name="M1", role=RoleEnum.MEMBER, target_level=5,
                march_preset=2, march_troop_types=["cavalry"],
                fill_target_leaders=[FillLeader(instance="i1", name="Hero")])
    base.update(kw)
    return CharacterConfig(**base)


def _root(*characters) -> RootConfig:
    return RootConfig(instances=[InstanceConfig(
        id="i1", mumu_index=0, characters=list(characters))])


def test_leader_minimal():
    c = _leader()
    assert c.role == RoleEnum.LEADER
    assert c.fill_target_leaders == []


def test_member_requires_fill_targets():
    with pytest.raises(ValidationError, match="fill_target_leaders"):
        _root(_leader(), _member(fill_target_leaders=[]))


def test_either_role_with_fill_targets():
    c = _member(id="c3", name="F1", role=RoleEnum.EITHER)
    assert c.role == RoleEnum.EITHER


def test_either_requires_fill_targets():
    with pytest.raises(ValidationError, match="fill_target_leaders"):
        _root(_leader(), _member(id="c3", name="F1", role=RoleEnum.EITHER,
                                 fill_target_leaders=[]))


def test_leader_must_not_have_fill_targets():
    with pytest.raises(ValidationError, match="leader"):
        _root(_leader(fill_target_leaders=[FillLeader(instance="i1", name="X")]))


def test_instance_requires_leader_or_either():
    with pytest.raises(ValidationError, match="no leader"):
        _root(_member(id="c9", name="OnlyM"))


def test_instance_duplicate_names():
    with pytest.raises(ValidationError, match="duplicate"):
        _root(_leader(), _member(name="Hero"))


def test_mumu_and_adb_both_set_rejected():
    with pytest.raises(ValidationError, match="只能填一个"):
        RootConfig(instances=[InstanceConfig(
            id="i1", mumu_index=0, adb_address="127.0.0.1:16384",
            characters=[_leader()])])


def test_mumu_and_adb_both_empty_rejected():
    with pytest.raises(ValidationError, match="必须填一个"):
        RootConfig(instances=[InstanceConfig(id="i1", characters=[_leader()])])


def test_window_title_pattern_optional():
    inst = InstanceConfig(id="i1", mumu_index=0, characters=[_leader()])
    assert inst.window_title_pattern == ""


def test_fill_target_must_exist():
    with pytest.raises(ValidationError, match="不存在"):
        _root(_leader(),
              _member(fill_target_leaders=[FillLeader(instance="i1", name="Ghost")]))


def test_fill_target_must_be_leader_or_either():
    with pytest.raises(ValidationError, match="leader/either"):
        _root(_leader(), _member(),
              _member(id="c3", name="M2",
                      fill_target_leaders=[FillLeader(instance="i1", name="M1")]))


def test_cross_instance_fill_target_ok():
    a = InstanceConfig(id="i1", mumu_index=0, characters=[_leader()])
    b = InstanceConfig(id="i2", mumu_index=1,
                       characters=[_member(fill_target_leaders=[FillLeader(instance="i1", name="Hero")])])
    cfg = RootConfig(instances=[a, b])
    assert cfg.instances[1].characters[0].fill_target_leaders[0].instance == "i1"


def test_duplicate_instance_ids():
    with pytest.raises(ValidationError, match="Duplicate instance"):
        RootConfig(instances=[InstanceConfig(id="i1", mumu_index=0, characters=[_leader()]),
                              InstanceConfig(id="i1", mumu_index=1, characters=[_leader(id="c9", name="H2")])])


def test_duplicate_character_ids():
    with pytest.raises(ValidationError, match="Duplicate character"):
        RootConfig(instances=[InstanceConfig(id="i1", mumu_index=0, characters=[_leader()]),
                              InstanceConfig(id="i2", mumu_index=1, characters=[_leader(name="H2")])])


def test_app_config_mumu_fields():
    app = AppConfig()
    assert app.mumu_manager_path == ""
    assert app.adb_path == "adb"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/infra/test_config_models.py -q`
Expected: FAIL / ERROR（ImportError: cannot import name 'InstanceConfig'）

- [ ] **Step 3: 全量替换 `src/rok_assistant/infra/config.py`**

```python
from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from .anti_detection import AntiDetectionConfig


class RoleEnum(str, Enum):
    LEADER = "leader"
    MEMBER = "member"
    EITHER = "either"


class FillLeader(BaseModel):
    instance: str
    name: str


class CharacterConfig(BaseModel):
    id: str
    name: str
    role: RoleEnum
    target_level: int = Field(ge=1, le=10)
    march_preset: int = Field(ge=1, le=5)
    march_troop_types: list[Literal["infantry", "cavalry", "archer"]]
    fill_target_leaders: list[FillLeader] = []

    @field_validator("march_troop_types")
    @classmethod
    def _not_empty(cls, v):
        if not v:
            raise ValueError("march_troop_types must be non-empty")
        return v


class InstanceConfig(BaseModel):
    id: str
    name: str = ""
    mumu_index: int | None = None
    adb_address: str = ""
    window_title_pattern: str = ""  # Win32 备用路线；ADB 路线用不到
    characters: list[CharacterConfig]

    @model_validator(mode="after")
    def _instance_checks(self):
        if self.mumu_index is None and not self.adb_address:
            raise ValueError(f"Instance {self.id}: mumu_index 或 adb_address 必须填一个")
        if self.mumu_index is not None and self.adb_address:
            raise ValueError(f"Instance {self.id}: mumu_index 与 adb_address 只能填一个")
        if not any(c.role in (RoleEnum.LEADER, RoleEnum.EITHER) for c in self.characters):
            raise ValueError(f"Instance {self.id} has no leader/either character")
        names = [c.name for c in self.characters]
        if len(names) != len(set(names)):
            raise ValueError(f"Instance {self.id} has duplicate character names")
        return self


class AppConfig(BaseModel):
    screen_width: int = 1920
    screen_height: int = 1080
    locale: str = "zh-CN"
    mumu_manager_path: str = ""   # 全局；MuMuManager.exe 完整路径
    adb_path: str = "adb"         # 全局；adb.exe 完整路径
    log_dir: Path = Path("./logs")
    template_dir: Path = Path("./templates")
    anti_detection: AntiDetectionConfig = Field(default_factory=AntiDetectionConfig)


class RootConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    instances: list[InstanceConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _cross_checks(self):
        inst_ids = [i.id for i in self.instances]
        if len(inst_ids) != len(set(inst_ids)):
            raise ValueError("Duplicate instance ids")
        char_ids = [c.id for i in self.instances for c in i.characters]
        if len(char_ids) != len(set(char_ids)):
            raise ValueError("Duplicate character ids")
        by_key = {(i.id, c.name): c for i in self.instances for c in i.characters}
        for i in self.instances:
            for c in i.characters:
                if c.role == RoleEnum.LEADER and c.fill_target_leaders:
                    raise ValueError(
                        f"Character {c.name}: leader 不能配置 fill_target_leaders")
                if c.role in (RoleEnum.MEMBER, RoleEnum.EITHER):
                    if not c.fill_target_leaders:
                        raise ValueError(
                            f"Character {c.name}: member/either 必须配置 fill_target_leaders")
                    for t in c.fill_target_leaders:
                        target = by_key.get((t.instance, t.name))
                        if target is None:
                            raise ValueError(
                                f"Character {c.name}: fill target ({t.instance}, {t.name}) 不存在")
                        if target.role not in (RoleEnum.LEADER, RoleEnum.EITHER):
                            raise ValueError(
                                f"Character {c.name}: fill target {t.name} 不是 leader/either")
        return self


def load_config(path: Path) -> RootConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return RootConfig.model_validate(raw)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/infra/test_config_models.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 更新 fixtures 与 loader 测试**

`tests/fixtures/config_valid.yaml` 全量替换：

```yaml
app:
  screen_width: 1920
  screen_height: 1080
  mumu_manager_path: "C:\\模拟器\\MuMuPlayer\\nx_main\\MuMuManager.exe"
  adb_path: "adb"
instances:
  - id: inst0
    name: "阑珊号"
    mumu_index: 0
    characters:
      - id: leader1
        name: "Hero"
        role: leader
        target_level: 8
        march_preset: 1
        march_troop_types: [infantry, archer]
      - id: member1
        name: "M1"
        role: member
        target_level: 5
        march_preset: 2
        march_troop_types: [cavalry]
        fill_target_leaders:
          - { instance: inst0, name: "Hero" }
```

`tests/fixtures/config_no_leader.yaml` 全量替换：

```yaml
app: {}
instances:
  - id: bad
    mumu_index: 0
    characters:
      - id: m1
        name: "OnlyMember"
        role: member
        target_level: 5
        march_preset: 1
        march_troop_types: [infantry]
        fill_target_leaders:
          - { instance: bad, name: "Ghost" }
```

`tests/fixtures/config_invalid_level.yaml` 全量替换：

```yaml
app: {}
instances:
  - id: bad
    mumu_index: 0
    characters:
      - id: l1
        name: "Hero"
        role: leader
        target_level: 11
        march_preset: 1
        march_troop_types: [infantry]
```

`tests/unit/infra/test_config_loader.py` 全量替换：

```python
from pathlib import Path
import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import load_config, RootConfig

FIX = Path(__file__).parent.parent.parent / "fixtures"


def test_load_valid_config():
    cfg = load_config(FIX / "config_valid.yaml")
    assert isinstance(cfg, RootConfig)
    assert len(cfg.instances) == 1
    assert cfg.instances[0].id == "inst0"
    assert cfg.instances[0].name == "阑珊号"
    assert cfg.app.mumu_manager_path.endswith("MuMuManager.exe")


def test_load_no_leader_raises():
    with pytest.raises(ValidationError, match="no leader"):
        load_config(FIX / "config_no_leader.yaml")


def test_load_invalid_level_raises():
    with pytest.raises(ValidationError, match="target_level"):
        load_config(FIX / "config_invalid_level.yaml")
```

- [ ] **Step 6: 跑 infra 全部测试**

Run: `python -m pytest tests/unit/infra -q`
Expected: PASS（config_models / config_loader 新用例全过，anti_detection 等不受影响）

- [ ] **Step 7: Commit**

```bash
git add src/rok_assistant/infra/config.py tests/unit/infra/test_config_models.py tests/unit/infra/test_config_loader.py tests/fixtures/config_valid.yaml tests/fixtures/config_no_leader.yaml tests/fixtures/config_invalid_level.yaml
git commit -m "feat(config): instances schema, either role, explicit fill targets, global mumu fields"
```

---

### Task 2: MumuLocator（MuMu 实例自动发现）

**Files:**
- Create: `src/rok_assistant/infra/mumu.py`
- Create: `tests/unit/infra/test_mumu_locator.py`

- [ ] **Step 1: 写失败的测试 `tests/unit/infra/test_mumu_locator.py`**

```python
import json
import pytest
from rok_assistant.infra.mumu import MumuLocator, MumuLocatorError


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


def _json_bytes(d) -> bytes:
    return json.dumps(d).encode("utf-8")


def test_resolve_parses_nested_adb_port():
    out = _json_bytes({"index": 0, "adb": {"adb_port": 16384}})
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(FakeProc(stdout=out)))
    assert loc.resolve_adb_address(0) == "127.0.0.1:16384"


def test_resolve_accepts_top_level_port_key():
    out = _json_bytes({"port": 16385})
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(FakeProc(stdout=out)))
    assert loc.resolve_adb_address(1) == "127.0.0.1:16385"


def test_resolve_passes_index_to_manager():
    runner = FakeRunner(FakeProc(stdout=_json_bytes({"adb_port": 16384})))
    loc = MumuLocator("C:/mumu/MuMuManager.exe", _runner=runner)
    loc.resolve_adb_address(2)
    assert runner.calls[0][:4] == ["C:/mumu/MuMuManager.exe", "api", "-v", "2"]


def test_resolve_nonzero_returncode_raises():
    proc = FakeProc(stderr="instance not found".encode(), returncode=1)
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(proc))
    with pytest.raises(MumuLocatorError, match="失败"):
        loc.resolve_adb_address(9)


def test_resolve_non_json_output_raises():
    proc = FakeProc(stdout=b"not json at all")
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(proc))
    with pytest.raises(MumuLocatorError, match="JSON"):
        loc.resolve_adb_address(0)


def test_resolve_missing_port_raises():
    proc = FakeProc(stdout=_json_bytes({"foo": "bar"}))
    loc = MumuLocator("MuMuManager.exe", _runner=FakeRunner(proc))
    with pytest.raises(MumuLocatorError, match="端口"):
        loc.resolve_adb_address(0)


def test_is_running_true_and_false():
    ok = MumuLocator("m", _runner=FakeRunner(FakeProc(stdout=_json_bytes({"adb_port": 16384}))))
    assert ok.is_running(0) is True
    bad = MumuLocator("m", _runner=FakeRunner(FakeProc(returncode=1)))
    assert bad.is_running(0) is False
    crash = MumuLocator("m", _runner=FakeRunner(error=FileNotFoundError("no exe")))
    assert crash.is_running(0) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/infra/test_mumu_locator.py -q`
Expected: FAIL（ModuleNotFoundError: mumu）

- [ ] **Step 3: 实现 `src/rok_assistant/infra/mumu.py`**

```python
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
        proc = self._run([self._manager, "api", "-v", str(index)])
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/infra/test_mumu_locator.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 实机验证 MuMuManager 命令（一次性探针，可能需微调）**

Run: `"C:\模拟器\MuMuPlayer\nx_main\MuMuManager.exe" api -v 0; echo "exit=$?"`
Expected: JSON 输出，其中含实例 0 的 adb 端口（本机当前为 16384）。
若字段名不是 `adb_port`/`port` 或命令不是 `api -v <n>`：调整 `MumuLocator.resolve_adb_address` 中的命令/`_extract_port`，并同步改 FakeRunner 测试数据，再跑 Step 4。若 MuMu 关闭时才查不到端口，属预期（连接测试就是拿这个判离线的）。

- [ ] **Step 6: Commit**

```bash
git add src/rok_assistant/infra/mumu.py tests/unit/infra/test_mumu_locator.py
git commit -m "feat(infra): MumuLocator - resolve instance adb port via MuMuManager"
```

---

### Task 3: create_handle_source 支持 mumu_index

**Files:**
- Modify: `src/rok_assistant/core/handle_source.py`（仅 `create_handle_source`，51-60 行）
- Modify: `tests/unit/core/test_adb_handle_source.py`（替换 2 个 factory 测试，追加 2 个）

- [ ] **Step 1: 替换 factory 测试**

在 `tests/unit/core/test_adb_handle_source.py` 中，删除 `test_factory_prefers_adb_when_address_set` 和 `test_factory_falls_back_to_win32` 两个函数，原位置替换为：

```python
def test_factory_prefers_adb_when_address_set():
    from rok_assistant.core.handle_source import create_handle_source
    src = create_handle_source(adb_address="127.0.0.1:16384", window_title_pattern="MuMu")
    assert isinstance(src, AdbHandleSource)
    assert src._address == "127.0.0.1:16384"


def test_factory_falls_back_to_win32():
    from rok_assistant.core.handle_source import Win32HandleSource, create_handle_source
    src = create_handle_source(window_title_pattern="MuMu")
    assert isinstance(src, Win32HandleSource)


class FakeLocator:
    def __init__(self, manager_path, adb_path):
        self.manager_path = manager_path
        self.adb_path = adb_path

    def resolve_adb_address(self, index):
        return f"127.0.0.1:{17000 + index}"


def test_factory_resolves_mumu_index():
    from rok_assistant.core.handle_source import create_handle_source
    src = create_handle_source(mumu_index=3, mumu_manager_path="C:/mumu/MuMuManager.exe",
                               adb_path="adb", _locator=FakeLocator)
    assert isinstance(src, AdbHandleSource)
    assert src._address == "127.0.0.1:17003"
    assert src._adb_path == "adb"


def test_factory_manual_adb_still_works_without_mumu_fields():
    from rok_assistant.core.handle_source import create_handle_source
    src = create_handle_source(adb_address="127.0.0.1:16384", adb_path="adb")
    assert isinstance(src, AdbHandleSource)
```

注意：若文件顶部没有 `from rok_assistant.core.handle_source import AdbHandleSource` 导入，补上（现有测试可能已在函数内导入，保持文件现状风格，缺哪个补哪个）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/core/test_adb_handle_source.py -q`
Expected: `test_factory_resolves_mumu_index` FAIL（TypeError: unexpected keyword 'mumu_index'），其余 PASS

- [ ] **Step 3: 替换 `create_handle_source`**

`src/rok_assistant/core/handle_source.py` 中 51-60 行的函数整体替换为：

```python
def create_handle_source(mumu_index: int | None = None, mumu_manager_path: str = "",
                         adb_address: str = "", adb_path: str = "adb",
                         window_title_pattern: str = "", _locator=None):
    """Build the best HandleSource for an instance.

    mumu_index set -> resolve adb address via MuMuManager, then AdbHandleSource.
    adb_address set -> AdbHandleSource directly (manual mode / non-MuMu emulator).
    Otherwise fall back to Win32 capture.
    """
    if mumu_index is not None:
        from ..infra.mumu import MumuLocator
        locator = _locator if _locator is not None else MumuLocator(mumu_manager_path, adb_path)
        address = locator.resolve_adb_address(mumu_index)
        return AdbHandleSource(adb_address=address, adb_path=adb_path)
    if adb_address:
        return AdbHandleSource(adb_address=adb_address, adb_path=adb_path)
    return Win32HandleSource(window_title_pattern=window_title_pattern)
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `python -m pytest tests/unit/core/test_adb_handle_source.py tests/unit/infra -q`
Expected: 全部 PASS（`tools/record.py` 用的 `adb_address=` 关键字调用与新签名兼容，无需改）

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/core/handle_source.py tests/unit/core/test_adb_handle_source.py
git commit -m "feat(core): factory resolves mumu_index via MumuLocator"
```

---

### Task 4: EitherStateMachine + 角色状态机工厂

**Files:**
- Create: `src/rok_assistant/workers/either_sm.py`
- Create: `src/rok_assistant/workers/factory.py`
- Modify: `src/rok_assistant/workers/member_sm.py:62-67`（`_filter_rally` 去掉 nearest 分支）
- Modify: `tests/unit/workers/test_member_sm.py:18`
- Create: `tests/unit/workers/test_either_sm.py`
- Create: `tests/unit/workers/test_worker_factory.py`

- [ ] **Step 1: 写失败的测试 `tests/unit/workers/test_either_sm.py`**

```python
import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.either_sm import EitherStateMachine
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource


def _mock_rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec


def _make_sm(fill_targets=None, bus=None):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = _mock_rec()
    recs = {k: rec for k in ("search_icon", "level_plus", "search_btn",
                             "rally_attack_popup", "red_rally", "preset_1",
                             "march_btn", "alliance_btn", "war_btn",
                             "sort_nearest", "join_btn")}
    sm = EitherStateMachine(handle_source=handle, recognizers=recs,
                            target_level=8, march_preset=1,
                            march_troop_types=["infantry"],
                            fill_target_leaders=fill_targets or [],
                            event_bus=bus)
    return sm


def test_delegates_to_leader_then_member():
    sm = _make_sm(fill_targets=[{"instance": "i1", "name": "Boss"}])
    assert isinstance(sm._leader, LeaderStateMachine)
    assert isinstance(sm._member, MemberStateMachine)
    for _ in range(60):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.is_terminal()
    # leader 阶段完整走完（开集结），member 阶段接手到 END
    assert any("LEADER:LAUNCH" in h for h in sm.history)
    assert any(h.startswith("MEMBER:") for h in sm.history)
    # 开完集结不停留：member 收到了 launch 事件
    assert sm._member._pending_event is not None
    assert sm._member._pending_event["rally_id"].startswith("rally_")


def test_not_terminal_while_member_phase_running():
    sm = _make_sm()
    sm.step()  # IDLE -> SEARCH_FORTRESS
    assert not sm.is_terminal()
    assert sm.current.startswith("LEADER:")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/workers/test_either_sm.py -q`
Expected: FAIL（ModuleNotFoundError: either_sm）

- [ ] **Step 3: 实现 `src/rok_assistant/workers/either_sm.py`**

```python
from __future__ import annotations
from .leader_sm import LeaderStateMachine
from .member_sm import MemberStateMachine


class EitherStateMachine:
    """车头或成员（spec 2026-09-09 §4）。

    单次上场流程：搜寨 -> 开集结 -> 不停留，立即转成员流程去填指定车头的
    集结。自己的集结由成员填，满员或倒计时结束自动发车。实现上复用
    Leader/Member 两个状态机，按阶段委托 step()：leader 到 WAIT_MEMBERS
    即置 departed 直接收尾，随后把 launch 事件交给 member 状态机。
    """

    def __init__(self, handle_source, recognizers: dict, target_level: int,
                 march_preset: int, march_troop_types: list,
                 fill_target_leaders, event_bus=None):
        self._leader = LeaderStateMachine(handle_source, recognizers, target_level,
                                          march_preset, march_troop_types, event_bus)
        self._member = MemberStateMachine(handle_source, recognizers, march_preset,
                                          march_troop_types, fill_target_leaders)
        self._phase = "leader"
        self.current = "LEADER:IDLE"
        self.history: list[str] = [self.current]
        self._ctx: dict = {}

    def step(self, context: dict | None = None) -> None:
        if context is not None:
            self._ctx = context
        ctx = self._ctx
        if self._phase == "leader":
            self._leader.step(ctx)
            if self._leader.current == "WAIT_MEMBERS":
                ctx.setdefault("departed", True)  # 不等待，即刻交棒
            self.current = f"LEADER:{self._leader.current}"
            if self._leader.is_terminal():
                self._phase = "member"
                if self._leader.last_rally_event:
                    self._member.on_rally_launched(self._leader.last_rally_event)
        else:
            self._member.step(ctx)
            self.current = f"MEMBER:{self._member.current}"
        self.history.append(self.current)

    def is_terminal(self) -> bool:
        return self._phase == "member" and self._member.is_terminal()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/workers/test_either_sm.py -q`
Expected: 2 PASS。若 `test_delegates_to_leader_then_member` 卡 60 步未终态：检查 `LeaderStateMachine._launch` 是否发布 `last_rally_event`（事件名 rally_id 前缀 rally_），以及 member SM 的 FILTER→CLICK_JOIN guard 路径。

- [ ] **Step 5: 写失败的工厂测试 `tests/unit/workers/test_worker_factory.py`**

```python
import numpy as np
from rok_assistant.infra.config import CharacterConfig, RoleEnum
from rok_assistant.workers.factory import create_state_machine
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.workers.either_sm import EitherStateMachine
from rok_assistant.core.handle_source import MockHandleSource


def _char(role):
    return CharacterConfig(id="c1", name="H", role=role, target_level=8,
                           march_preset=1, march_troop_types=["infantry"],
                           fill_target_leaders=[{"instance": "i1", "name": "Boss"}]
                           if role != RoleEnum.LEADER else [])


def _handle():
    return MockHandleSource(screenshot=np.zeros((10, 10, 3), dtype=np.uint8))


def test_factory_builds_leader():
    sm = create_state_machine(_char(RoleEnum.LEADER), _handle(), {})
    assert isinstance(sm, LeaderStateMachine)


def test_factory_builds_member():
    sm = create_state_machine(_char(RoleEnum.MEMBER), _handle(), {})
    assert isinstance(sm, MemberStateMachine)


def test_factory_builds_either():
    sm = create_state_machine(_char(RoleEnum.EITHER), _handle(), {})
    assert isinstance(sm, EitherStateMachine)
```

- [ ] **Step 6: 跑测试确认失败**

Run: `python -m pytest tests/unit/workers/test_worker_factory.py -q`
Expected: FAIL（ModuleNotFoundError: factory）

- [ ] **Step 7: 实现 `src/rok_assistant/workers/factory.py`**

```python
from __future__ import annotations
from ..infra.config import CharacterConfig, RoleEnum
from .leader_sm import LeaderStateMachine
from .member_sm import MemberStateMachine
from .either_sm import EitherStateMachine


def create_state_machine(character: CharacterConfig, handle_source, recognizers: dict,
                         event_bus=None):
    """Build the state machine matching a character's configured role."""
    if character.role == RoleEnum.LEADER:
        return LeaderStateMachine(handle_source, recognizers, character.target_level,
                                  character.march_preset,
                                  character.march_troop_types, event_bus)
    if character.role == RoleEnum.MEMBER:
        return MemberStateMachine(handle_source, recognizers, character.march_preset,
                                  character.march_troop_types,
                                  character.fill_target_leaders)
    return EitherStateMachine(handle_source, recognizers, character.target_level,
                              character.march_preset, character.march_troop_types,
                              character.fill_target_leaders, event_bus)
```

- [ ] **Step 8: 跑测试确认通过**

Run: `python -m pytest tests/unit/workers/test_worker_factory.py -q`
Expected: 3 PASS

- [ ] **Step 9: member_sm 去掉 nearest 分支**

`src/rok_assistant/workers/member_sm.py` 中 `_filter_rally`（62-67 行）替换为：

```python
    def _filter_rally(self, ctx):
        # fill_target_leaders 现在永远是显式列表；按名字 OCR 匹配是后续里程碑
        # （ACCEPTANCE §3.7），当前简化为加入排序后的第一个集结。
        ctx["rally_found"] = True
```

`tests/unit/workers/test_member_sm.py:18` 的 `fill_target_leaders="nearest"` 替换为：

```python
        fill_target_leaders=[{"instance": "i1", "name": "Boss"}]
```

- [ ] **Step 10: workers 全量测试 + Commit**

Run: `python -m pytest tests/unit/workers -q`
Expected: 全部 PASS

```bash
git add src/rok_assistant/workers/either_sm.py src/rok_assistant/workers/factory.py src/rok_assistant/workers/member_sm.py tests/unit/workers/test_either_sm.py tests/unit/workers/test_worker_factory.py tests/unit/workers/test_member_sm.py
git commit -m "feat(workers): EitherStateMachine (launch then fill) + role-based factory"
```

---

### Task 5: GUI 配置对话框 — 骨架 + 全局页 + 保存

**Files:**
- Create: `src/rok_assistant/gui/config_dialog.py`
- Create: `tests/integration/test_config_dialog.py`

- [ ] **Step 1: 写失败的测试 `tests/integration/test_config_dialog.py`**

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import yaml
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from rok_assistant.gui.config_dialog import ConfigDialog


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _valid_config_dict() -> dict:
    return {
        "app": {"mumu_manager_path": "C:/mumu/MuMuManager.exe", "adb_path": "adb"},
        "instances": [
            {
                "id": "inst0", "name": "阑珊号", "mumu_index": 0,
                "characters": [
                    {"id": "c1", "name": "Hero", "role": "leader", "target_level": 8,
                     "march_preset": 1, "march_troop_types": ["infantry"]},
                    {"id": "c2", "name": "M1", "role": "member", "target_level": 5,
                     "march_preset": 2, "march_troop_types": ["cavalry"],
                     "fill_target_leaders": [{"instance": "inst0", "name": "Hero"}]},
                ],
            }
        ],
    }


def _write_config(tmp_path, data=None) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(data or _valid_config_dict()), encoding="utf-8")
    return cfg


def test_dialog_loads_and_builds_tree(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    labels = [dlg._tree.topLevelItem(i).text(0) for i in range(dlg._tree.topLevelItemCount())]
    assert any("阑珊号" in t for t in labels)
    assert any("全局设置" in t for t in labels)


def test_save_writes_yaml(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    cfg = _write_config(tmp_path)
    dlg = ConfigDialog(cfg)
    dlg._data["app"]["mumu_manager_path"] = "C:/other/MuMuManager.exe"
    assert dlg.save() is True
    loaded = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert loaded["app"]["mumu_manager_path"] == "C:/other/MuMuManager.exe"
    assert loaded["instances"][0]["characters"][1]["fill_target_leaders"][0]["name"] == "Hero"


def test_save_rejects_invalid_and_keeps_file(tmp_path, qapp, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: errors.append(k.get("text") or (a[2] if len(a) > 2 else "")))
    cfg = _write_config(tmp_path)
    dlg = ConfigDialog(cfg)
    dlg._data["instances"][0]["characters"][1]["fill_target_leaders"] = []
    assert dlg.save() is False
    assert any("fill_target_leaders" in e for e in errors)
    loaded = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert loaded["instances"][0]["characters"][1]["fill_target_leaders"] == [
        {"instance": "inst0", "name": "Hero"}]


def test_yaml_preview_reflects_data(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._refresh_yaml_preview()
    assert "阑珊号" in dlg._yaml_view.toPlainText()
    assert "fill_target_leaders" in dlg._yaml_view.toPlainText()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/integration/test_config_dialog.py -q`
Expected: FAIL（ModuleNotFoundError: config_dialog）

- [ ] **Step 3: 实现 `src/rok_assistant/gui/config_dialog.py`（本任务版本：骨架+全局页+YAML 页+保存）**

```python
"""可视化配置对话框：左树右表单（spec 2026-09-09 §5）。

数据模式：对话框持有 model_dump 出来的纯 dict（self._data），各表单写回
dict，保存时 RootConfig.model_validate 整体校验，避免编辑过程中产生
半合法的 pydantic 对象。self._widgets 记录 (路径元组)->控件，用于校验
错误时定位标红。
"""
from __future__ import annotations

from pathlib import Path

import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)
from pydantic import ValidationError

from rok_assistant.infra.config import RootConfig, load_config

ROLE_LABELS = {"leader": "车头", "member": "成员", "either": "车头或成员"}
LABEL_ROLES = {v: k for k, v in ROLE_LABELS.items()}
TROOP_LABELS = {"infantry": "步兵", "cavalry": "骑兵", "archer": "弓兵"}

ERR_STYLE = "border: 1px solid red;"


class ConfigDialog(QDialog):
    def __init__(self, config_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("rok-assistant 配置")
        self.resize(880, 620)
        self._path = Path(config_path)
        self._data = load_config(self._path).model_dump(mode="json")
        self._widgets: dict[tuple, QWidget] = {}
        self._build_ui()

    # ---------------- UI 骨架 ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        body = QHBoxLayout()
        root.addLayout(body, 1)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(190)
        self._tree.currentItemChanged.connect(self._on_tree_change)
        body.addWidget(self._tree)

        self._stack = QStackedWidget()
        body.addWidget(self._stack, 1)

        buttons = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)

        self._reload_tree()

    def _reload_tree(self):
        self._tree.clear()
        while self._stack.count():
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()

        g = QTreeWidgetItem(["全局设置"])
        g.setData(0, Qt.ItemDataRole.UserRole, ("page", "global"))
        self._tree.addTopLevelItem(g)
        self._stack.addWidget(self._make_global_page())

        y = QTreeWidgetItem(["YAML 源码"])
        y.setData(0, Qt.ItemDataRole.UserRole, ("page", "yaml"))
        self._tree.addTopLevelItem(y)
        self._yaml_view = QPlainTextEdit()
        self._yaml_view.setReadOnly(True)
        self._stack.addWidget(self._yaml_view)

        for idx, inst in enumerate(self._data["instances"]):
            label = inst.get("name") or inst["id"]
            item = QTreeWidgetItem([f"实例  {label}"])
            item.setData(0, Qt.ItemDataRole.UserRole, ("page", idx))
            self._tree.addTopLevelItem(item)
            self._stack.addWidget(self._make_instance_page(idx))

        self._tree.setCurrentItem(g)
        self._refresh_yaml_preview()

    def _on_tree_change(self, cur, _prev):
        if cur is None:
            return
        kind, key = cur.data(0, Qt.ItemDataRole.UserRole)
        if kind == "page" and isinstance(key, int):
            self._stack.setCurrentIndex(2 + key)
        elif key == "global":
            self._stack.setCurrentIndex(0)
        else:
            self._stack.setCurrentIndex(1)

    # ---------------- 小部件帮手 ----------------
    def _bind(self, path: tuple, widget: QWidget) -> QWidget:
        self._widgets[path] = widget
        return widget

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _spin(self, path: tuple, value, lo, hi, double=False) -> QWidget:
        w = QDoubleSpinBox() if double else QSpinBox()
        w.setRange(lo, hi)
        if double:
            w.setDecimals(2)
            w.setValue(float(value))
            w.valueChanged.connect(
                lambda v, p=path: self._data_set(p, round(v, 2)))
        else:
            w.setValue(int(value))
            w.valueChanged.connect(
                lambda v, p=path: self._data_set(p, int(v)))
        return self._bind(path, w)

    def _line(self, path: tuple, value) -> QLineEdit:
        w = QLineEdit(str(value))
        w.textChanged.connect(lambda t, p=path: self._data_set(p, t))
        return self._bind(path, w)

    def _data_set(self, path: tuple, value):
        """写回 self._data；路径形如 ("app","adb_path") 或 ("instances",0,"name")。"""
        obj = self._data
        for key in path[:-1]:
            obj = obj[key]
        obj[path[-1]] = value

    # ---------------- 全局页 ----------------
    def _make_global_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        form = QFormLayout()
        app = self._data["app"]

        mumu = self._line(("app", "mumu_manager_path"), app.get("mumu_manager_path", ""))
        mumu_btn = QPushButton("浏览…")
        mumu_btn.clicked.connect(lambda: self._pick_file(mumu, "选择 MuMuManager.exe"))
        mumu_row = QHBoxLayout()
        mumu_row.addWidget(mumu, 1)
        mumu_row.addWidget(mumu_btn)
        form.addRow("MuMuManager 路径", self._wrap(mumu_row))

        adb = self._line(("app", "adb_path"), app.get("adb_path", "adb"))
        adb_btn = QPushButton("浏览…")
        adb_btn.clicked.connect(lambda: self._pick_file(adb, "选择 adb.exe"))
        adb_row = QHBoxLayout()
        adb_row.addWidget(adb, 1)
        adb_row.addWidget(adb_btn)
        form.addRow("adb 路径", self._wrap(adb_row))
        outer.addLayout(form)

        anti = self._data["app"]["anti_detection"]
        group = QGroupBox("防检测参数")
        af = QFormLayout(group)
        af.addRow("点击偏移(px)", self._spin(("app", "anti_detection", "click_offset_px"),
                                             anti["click_offset_px"], 0, 50))
        af.addRow("动作延迟下限(s)", self._spin(("app", "anti_detection", "action_delay_min"),
                                                anti["action_delay_min"], 0.0, 10.0, double=True))
        af.addRow("动作延迟上限(s)", self._spin(("app", "anti_detection", "action_delay_max"),
                                                anti["action_delay_max"], 0.0, 10.0, double=True))
        af.addRow("状态延迟下限(s)", self._spin(("app", "anti_detection", "state_delay_min"),
                                                anti["state_delay_min"], 0.0, 30.0, double=True))
        af.addRow("状态延迟上限(s)", self._spin(("app", "anti_detection", "state_delay_max"),
                                                anti["state_delay_max"], 0.0, 30.0, double=True))
        af.addRow("抖动比例", self._spin(("app", "anti_detection", "jitter_ratio"),
                                         anti["jitter_ratio"], 0.0, 1.0, double=True))
        dbg = QCheckBox("调试模式（关闭随机化）")
        dbg.setChecked(anti["debug_no_jitter"])
        dbg.toggled.connect(lambda v: self._data_set(("app", "anti_detection", "debug_no_jitter"), bool(v)))
        self._bind(("app", "anti_detection", "debug_no_jitter"), dbg)
        af.addRow(dbg)
        outer.addWidget(group)
        outer.addStretch(1)
        return page

    def _pick_file(self, line_edit: QLineEdit, title: str):
        f, _ = QFileDialog.getOpenFileName(self, title, line_edit.text(), "All files (*.*)")
        if f:
            line_edit.setText(f)

    # ---------------- YAML 预览页 ----------------
    def _refresh_yaml_preview(self):
        self._yaml_view.setPlainText(
            yaml.safe_dump(self._data, allow_unicode=True, sort_keys=False))

    # ---------------- 实例页占位（Task 6 实现） ----------------
    def _make_instance_page(self, idx: int) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel(f"实例 {self._data['instances'][idx].get('name') or self._data['instances'][idx]['id']}"
                           "（实例/角色编辑在下一个任务实现）"))
        v.addStretch(1)
        return page

    # ---------------- 保存 ----------------
    def _on_save(self):
        if self.save():
            self.accept()

    def save(self) -> bool:
        try:
            RootConfig.model_validate(self._data)
        except ValidationError as e:
            self._show_errors(e)
            return False
        self._path.write_text(
            yaml.safe_dump(self._data, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        self._refresh_yaml_preview()
        QMessageBox.information(self, "配置", "保存成功")
        return True

    def _show_errors(self, e: ValidationError):
        for path in self._widgets:
            self._widgets[path].setStyleSheet("")
        lines = []
        for err in e.errors():
            loc = tuple(err["loc"])
            lines.append(" / ".join(str(x) for x in loc) + f": {err['msg']}")
            w = self._widgets.get(loc)
            if w is not None:
                w.setStyleSheet(ERR_STYLE)
        QMessageBox.critical(self, "校验失败", "\n".join(lines) or str(e))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/integration/test_config_dialog.py -q`
Expected: 4 PASS。若 `test_save_rejects_invalid_and_keeps_file` 中 `errors` 为空：`_show_errors` 的 `QMessageBox.critical` monkeypatch 签名是 `lambda *a, **k`，断言改用 `a` 兜底（测试已写好兜底）。

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/gui/config_dialog.py tests/integration/test_config_dialog.py
git commit -m "feat(gui): config dialog skeleton - tree nav, global page, yaml preview, validated save"
```

---

### Task 6: GUI 实例页 + 角色编辑

**Files:**
- Modify: `src/rok_assistant/gui/config_dialog.py`（替换 `_make_instance_page` 占位，新增实例/角色方法与 `CharacterEditDialog`）
- Modify: `tests/integration/test_config_dialog.py`（追加测试）

- [ ] **Step 1: 追加失败测试到 `tests/integration/test_config_dialog.py`**

文件顶部 `from rok_assistant.gui.config_dialog import ConfigDialog` 之后补导入：

```python
from rok_assistant.gui.config_dialog import CharacterEditDialog
```

文件末尾追加：

```python
def test_add_instance_generates_unique_id(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._add_instance()
    assert len(dlg._data["instances"]) == 2
    assert dlg._data["instances"][1]["id"] == "inst1"
    assert dlg._data["instances"][1]["characters"] == []
    # 新实例不合法（无角色），保存必须被拒
    assert dlg.save() is False


def test_add_and_edit_character_roundtrip(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    char = {"id": "c9", "name": "New", "role": "either", "target_level": 7,
            "march_preset": 3, "march_troop_types": ["archer"],
            "fill_target_leaders": [{"instance": "inst0", "name": "Hero"}]}
    dlg._save_character(0, None, char)
    chars = dlg._data["instances"][0]["characters"]
    assert len(chars) == 3
    assert chars[2]["role"] == "either"
    assert dlg.save() is True
    loaded = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert loaded["instances"][0]["characters"][2]["name"] == "New"


def test_character_edit_dialog_rejects_member_without_fills(qapp):
    dlg = CharacterEditDialog(None, None, [{"instance": "inst0", "name": "Hero"}])
    dlg.name_edit.setText("X")
    dlg.role_combo.setCurrentText(ROLE_LABELS["member"])
    assert dlg.validate() is not None  # 返回错误信息（非 None）


def test_delete_character(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._delete_character(0, 1)  # 删 M1（有 fill target 引用，删除后 leader 无妨）
    assert [c["name"] for c in dlg._data["instances"][0]["characters"]] == ["Hero"]
    assert dlg.save() is True


def test_delete_character_with_incoming_reference_blocks_save(tmp_path, qapp, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: errors.append(str(a)))
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._delete_character(0, 0)  # 删 Hero；M1 的填兵目标悬空
    assert dlg.save() is False
```

并补常量导入（追加到测试文件 import 区）：

```python
from rok_assistant.gui.config_dialog import ROLE_LABELS
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/integration/test_config_dialog.py -q`
Expected: 新增 5 个 FAIL（AttributeError: _add_instance 等），原 4 个 PASS

- [ ] **Step 3: 实现实例页与角色编辑**

3a. `config_dialog.py` 顶部 import 区补：

```python
import uuid
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QListWidget
```

3b. 文件末尾（`ConfigDialog` 类外）追加 `CharacterEditDialog`：

```python
class CharacterEditDialog(QDialog):
    """单个角色的编辑表单（spec 2026-09-09 §5 角色编辑表单）。"""

    def __init__(self, parent, character: dict | None, candidates: list[dict]):
        super().__init__(parent)
        self.setWindowTitle("角色编辑")
        self.resize(460, 520)
        self._character = dict(character) if character else None
        self._candidates = candidates
        form = QFormLayout(self)

        self.name_edit = QLineEdit((character or {}).get("name", ""))
        form.addRow("角色名（须与游戏内一致）", self.name_edit)

        self.role_combo = QComboBox()
        for r in ("leader", "member", "either"):
            self.role_combo.addItem(ROLE_LABELS[r])
        if (character or {}).get("role"):
            self.role_combo.setCurrentText(ROLE_LABELS[character["role"]])
        form.addRow("分工", self.role_combo)

        self.level_spin = QSpinBox()
        self.level_spin.setRange(1, 10)
        self.level_spin.setValue((character or {}).get("target_level", 7))
        form.addRow("目标城寨等级", self.level_spin)

        self.preset_spin = QSpinBox()
        self.preset_spin.setRange(1, 5)
        self.preset_spin.setValue((character or {}).get("march_preset", 1))
        form.addRow("行军预设", self.preset_spin)

        troop_row = QHBoxLayout()
        self.troop_checks = {}
        for key, label in TROOP_LABELS.items():
            cb = QCheckBox(label)
            cb.setChecked(key in (character or {}).get("march_troop_types", ["infantry"]))
            self.troop_checks[key] = cb
            troop_row.addWidget(cb)
        form.addRow("兵种", ConfigDialog._wrap(troop_row))

        form.addRow(QLabel("填兵目标（成员 / 车头或成员 必选，可多选）："))
        lists = QHBoxLayout()
        self.cand_list = QListWidget()
        self.sel_list = QListWidget()
        selected = {(f["instance"], f["name"])
                    for f in (character or {}).get("fill_target_leaders", [])}
        for c in candidates:
            item = QListWidgetItem(f"{c['instance']} / {c['name']}")
            item.setData(Qt.ItemDataRole.UserRole, (c["instance"], c["name"]))
            if (c["instance"], c["name"]) in selected:
                self.sel_list.addItem(item)
            else:
                self.cand_list.addItem(item)
        lists.addWidget(self.cand_list)
        moves = QVBoxLayout()
        add_btn = QPushButton("→")
        add_btn.clicked.connect(self._move_to_selected)
        rm_btn = QPushButton("←")
        rm_btn.clicked.connect(self._move_to_candidates)
        moves.addStretch(1)
        moves.addWidget(add_btn)
        moves.addWidget(rm_btn)
        moves.addStretch(1)
        lists.addLayout(moves)
        lists.addWidget(self.sel_list)
        form.addRow(self._wrap(lists))

        ok = QPushButton("确定")
        ok.clicked.connect(self._on_ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        form.addRow(self._wrap(btns))

        self.role_combo.currentTextChanged.connect(
            lambda _t: self.sel_list.setEnabled(
                self.role_combo.currentText() != ROLE_LABELS["leader"]))
        self.sel_list.setEnabled(self.role_combo.currentText() != ROLE_LABELS["leader"])

    def _move_to_selected(self):
        for item in self.cand_list.selectedItems():
            self.cand_list.takeItem(self.cand_list.row(item))
            self.sel_list.addItem(item)

    def _move_to_candidates(self):
        for item in self.sel_list.selectedItems():
            self.sel_list.takeItem(self.sel_list.row(item))
            self.cand_list.addItem(item)

    def _selected_fills(self) -> list[dict]:
        out = []
        for i in range(self.sel_list.count()):
            inst, name = self.sel_list.item(i).data(Qt.ItemDataRole.UserRole)
            out.append({"instance": inst, "name": name})
        return out

    def validate(self) -> str | None:
        """返回错误说明；None 表示可保存。"""
        if not self.name_edit.text().strip():
            return "角色名不能为空"
        troops = [k for k, cb in self.troop_checks.items() if cb.isChecked()]
        if not troops:
            return "至少选择一个兵种"
        role = LABEL_ROLES[self.role_combo.currentText()]
        if role in ("member", "either") and not self._selected_fills():
            return f"分工为 {ROLE_LABELS[role]} 时必须选择填兵目标"
        return None

    def _on_ok(self):
        err = self.validate()
        if err:
            QMessageBox.warning(self, "角色编辑", err)
            return
        self.accept()

    def get_result(self) -> dict:
        role = LABEL_ROLES[self.role_combo.currentText()]
        return {
            "id": (self._character or {}).get("id") or f"char-{uuid.uuid4().hex[:8]}",
            "name": self.name_edit.text().strip(),
            "role": role,
            "target_level": self.level_spin.value(),
            "march_preset": self.preset_spin.value(),
            "march_troop_types": [k for k, cb in self.troop_checks.items() if cb.isChecked()],
            "fill_target_leaders": [] if role == "leader" else self._selected_fills(),
        }
```

3c. `ConfigDialog` 类内，替换整个占位 `_make_instance_page` 为：

```python
    # ---------------- 实例页 ----------------
    def _make_instance_page(self, idx: int) -> QWidget:
        inst = self._data["instances"][idx]
        page = QWidget()
        outer = QVBoxLayout(page)
        form = QFormLayout()

        outer.addWidget(QLabel(f"实例 ID：{inst['id']}"))
        name = self._line(("instances", idx, "name"), inst.get("name", ""))
        form.addRow("显示名", name)

        mode = QComboBox()
        mode.addItems(["MuMu 实例号", "手动 adb 地址"])
        stack = QStackedWidget()
        spin = QSpinBox()
        spin.setRange(0, 64)
        spin.setValue(inst.get("mumu_index") or 0)
        spin.valueChanged.connect(lambda v, i=idx: self._set_mumu_index(i, int(v)))
        self._bind(("instances", idx, "mumu_index"), spin)
        addr = self._line(("instances", idx, "adb_address"), inst.get("adb_address", ""))
        stack.addWidget(spin)
        stack.addWidget(addr)
        is_manual = inst.get("mumu_index") is None
        mode.setCurrentIndex(1 if is_manual else 0)
        stack.setCurrentIndex(1 if is_manual else 0)

        def _on_mode(i, i2=idx):
            inst2 = self._data["instances"][i2]
            if i == 0:
                inst2["mumu_index"] = int(spin.value())
                inst2["adb_address"] = ""
            else:
                inst2["mumu_index"] = None
                inst2["adb_address"] = addr.text()
        mode.currentIndexChanged.connect(_on_mode)
        mode.currentIndexChanged.connect(stack.setCurrentIndex)
        form.addRow("接入方式", mode)
        form.addRow("MuMu 实例号", stack)
        outer.addLayout(form)

        outer.addWidget(QLabel("角色阵容（双击行编辑）"))
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["名字", "分工", "目标等级", "预设", "兵种 / 填兵目标"])
        for c in inst["characters"]:
            self._append_char_row(table, c)
        table.doubleClicked.connect(
            lambda _mi, i=idx, t=table: self._edit_character(i, t.currentRow()))
        outer.addWidget(table, 1)

        btns = QHBoxLayout()
        add_btn = QPushButton("＋ 添加角色")
        add_btn.clicked.connect(lambda _c, i=idx, t=table: self._edit_character(i, -1))
        del_btn = QPushButton("删除选中角色")
        del_btn.clicked.connect(lambda _c, i=idx, t=table: self._delete_character(i, t.currentRow()))
        add_inst_btn = QPushButton("＋ 添加实例")
        add_inst_btn.clicked.connect(lambda _c: self._add_instance())
        del_inst_btn = QPushButton("删除本实例")
        del_inst_btn.clicked.connect(lambda _c, i=idx: self._delete_instance(i))
        for b in (add_btn, del_btn, add_inst_btn, del_inst_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        outer.addLayout(btns)
        return page

    @staticmethod
    def _append_char_row(table: QTableWidget, c: dict):
        row = table.rowCount()
        table.insertRow(row)
        fills = ", ".join(f"{f['instance']}/{f['name']}" for f in c.get("fill_target_leaders", []))
        troops = "、".join(TROOP_LABELS[t] for t in c["march_troop_types"])
        summary = troops + (f" ｜ 填: {fills}" if fills else "")
        for col, text in enumerate([c["name"], ROLE_LABELS[c["role"]],
                                    str(c["target_level"]), str(c["march_preset"]), summary]):
            table.setItem(row, col, QTableWidgetItem(text))

    def _leader_candidates(self, exclude=None) -> list[dict]:
        out = []
        for i, inst in enumerate(self._data["instances"]):
            for j, c in enumerate(inst["characters"]):
                if c["role"] in ("leader", "either") and (i, j) != exclude:
                    out.append({"instance": inst["id"], "name": c["name"]})
        return out

    def _edit_character(self, idx: int, row: int):
        inst = self._data["instances"][idx]
        existing = inst["characters"][row] if 0 <= row < len(inst["characters"]) else None
        dlg = CharacterEditDialog(self, existing, self._leader_candidates(
            exclude=(idx, row) if existing else None))
        if dlg.exec() and dlg.get_result():
            self._save_character(idx, existing, dlg.get_result())

    def _save_character(self, idx: int, existing: dict | None, result: dict):
        chars = self._data["instances"][idx]["characters"]
        if existing is not None:
            pos = next(i for i, c in enumerate(chars) if c["id"] == existing["id"])
            chars[pos] = result
        else:
            chars.append(result)
        self._reload_tree()

    def _delete_character(self, idx: int, row: int):
        chars = self._data["instances"][idx]["characters"]
        if 0 <= row < len(chars):
            chars.pop(row)
            self._reload_tree()

    def _add_instance(self):
        used = {i["id"] for i in self._data["instances"]}
        n = 0
        while f"inst{n}" in used:
            n += 1
        self._data["instances"].append({
            "id": f"inst{n}", "name": f"实例{n}", "mumu_index": None,
            "adb_address": "", "window_title_pattern": "", "characters": []})
        self._reload_tree()

    def _delete_instance(self, idx: int):
        self._data["instances"].pop(idx)
        self._reload_tree()
```

注意 `_save_character` / `_delete_character` / `_add_instance` / `_delete_instance` 里的 `self._reload_tree()` 会重建全部页面（本地变量 `table` 失效属预期，操作后树与页面已刷新）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/integration/test_config_dialog.py -q`
Expected: 9 PASS。若 `test_delete_character_with_incoming_reference_blocks_save` 失败于 `QMessageBox.critical` 断言格式，直接断言 `dlg.save() is False` 即可（保留 errors 断言可删）。

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/gui/config_dialog.py tests/integration/test_config_dialog.py
git commit -m "feat(gui): instance pages, character editor, fill-target picker"
```

---

### Task 7: 测试连接 + 主窗口集成 + 移除 YAML 文本编辑器

**Files:**
- Modify: `src/rok_assistant/gui/config_dialog.py`（连接测试 + 全局页检测按钮）
- Modify: `src/rok_assistant/gui/main_window.py`
- Delete: `src/rok_assistant/gui/config_editor.py`, `tests/integration/test_config_editor.py`

- [ ] **Step 1: 追加失败测试到 `tests/integration/test_config_dialog.py`**

```python
def test_test_connection_reports_error(tmp_path, qapp, monkeypatch):
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._status_labels[0] = QLabel()
    dlg._preview_labels[0] = QLabel()

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("no adb")

    monkeypatch.setattr("rok_assistant.gui.config_dialog.create_handle_source", Boom)
    dlg._test_connection(0)
    assert "连接失败" in dlg._status_labels[0].text()


def test_detect_all_instances_lists_status(tmp_path, qapp, monkeypatch):
    dlg = ConfigDialog(_write_config(tmp_path))
    dlg._detect_all_instances()
    assert "inst0" in dlg._detect_output.toPlainText()


def test_main_window_has_config_button(qapp, monkeypatch):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow()
    assert w.config_btn.text().endswith("配置")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/integration/test_config_dialog.py -q`
Expected: 新增 3 FAIL，其余 PASS

- [ ] **Step 3: 实现连接测试**

3a. `config_dialog.py` import 区补：

```python
from PyQt6.QtGui import QImage, QPixmap
from rok_assistant.core.handle_source import create_handle_source
```

3b. `_make_instance_page` 中 `btns.addStretch(1)` 之前插入：

```python
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(lambda _c, i=idx: self._test_connection(i))
        btns.addWidget(test_btn)
```

并在 `outer.addLayout(btns)` 之后追加状态与预览区：

```python
        self._status_labels[idx] = QLabel("○ 未测试")
        outer.addWidget(self._status_labels[idx])
        self._preview_labels[idx] = QLabel()
        outer.addWidget(self._preview_labels[idx])
```

`__init__` 里 `self._widgets` 声明后补两个成员：`self._status_labels: dict[int, QLabel] = {}`、`self._preview_labels: dict[int, QLabel] = {}`。

3c. `ConfigDialog` 类内追加方法：

```python
    def _test_connection(self, idx: int):
        """spec §5：查实例在线 -> adb 截一帧显示缩略图，确认连的是这台。"""
        import cv2
        inst = self._data["instances"][idx]
        try:
            handle = create_handle_source(
                mumu_index=inst.get("mumu_index"),
                mumu_manager_path=self._data["app"].get("mumu_manager_path", ""),
                adb_address=inst.get("adb_address", ""),
                adb_path=self._data["app"].get("adb_path", "adb"))
            img = handle.capture()
        except Exception as e:  # 连不上/截图失败都要给非程序员能读懂的提示
            self._status_labels[idx].setText(f"○ 连接失败：{e}")
            self._preview_labels[idx].clear()
            return
        self._status_labels[idx].setText(
            f"● 已连接，截图 {img.shape[1]}x{img.shape[0]}")
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self._preview_labels[idx].setPixmap(QPixmap.fromImage(qimg).scaled(
            320, 180, Qt.AspectRatioMode.KeepAspectRatio))

    def _detect_all_instances(self):
        """spec §5：全局页「检测全部实例」，列出各实例在线状态。"""
        from rok_assistant.infra.mumu import MumuLocator
        lines = []
        for inst in self._data["instances"]:
            if inst.get("mumu_index") is not None:
                loc = MumuLocator(self._data["app"].get("mumu_manager_path", ""),
                                  self._data["app"].get("adb_path", "adb"))
                state = "● 在线" if loc.is_running(inst["mumu_index"]) else "○ 离线/未启动"
                lines.append(f"{inst['id']} (mumu{inst['mumu_index']}): {state}")
            else:
                lines.append(f"{inst['id']}: 手动 adb 模式，用实例页「测试连接」检查")
        self._detect_output.setPlainText("\n".join(lines) or "尚无实例")
```

3d. 全局页 `_make_global_page` 的 `outer.addWidget(group)` 之后、`outer.addStretch(1)` 之前插入：

```python
        detect_btn = QPushButton("检测全部实例")
        detect_btn.clicked.connect(self._detect_all_instances)
        outer.addWidget(detect_btn)
        self._detect_output = QPlainTextEdit()
        self._detect_output.setReadOnly(True)
        self._detect_output.setMaximumHeight(120)
        outer.addWidget(self._detect_output)
```

- [ ] **Step 4: 主窗口集成 + 删除旧编辑器**

4a. `src/rok_assistant/gui/main_window.py`：`_build_ui` 里 `top.addWidget(self.refresh_btn)` 之后加：

```python
        self.config_btn = QPushButton("⚙ 配置")
        self.config_btn.clicked.connect(self._open_config)
        top.addWidget(self.config_btn)
```

类内追加方法（`import QMessageBox` 需加入 PyQt6.QtWidgets 的现有 import 列表）：

```python
    def _open_config(self):
        from pathlib import Path
        from .config_dialog import ConfigDialog
        path = Path("config.yaml")
        if not path.exists():
            QMessageBox.warning(self, "配置", f"未找到 {path}（请先在项目根目录准备 config.yaml）")
            return
        dlg = ConfigDialog(path, self)
        dlg.exec()
```

4b. 删除文件：

```bash
git rm src/rok_assistant/gui/config_editor.py tests/integration/test_config_editor.py
```

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS（原 config_editor 的 4 个测试随文件删除；新增 12 个 dialog 测试；总量 > 91）

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(gui): connection test + main window wiring, remove yaml text editor"
```

---

### Task 8: 文档与示例配置收尾

**Files:**
- Replace: `config.example.yaml`
- Modify: `docs/ACCEPTANCE.md`（§2 配置示例 + 状态表）
- Modify: `docs/superpowers/specs/2026-07-15-rok-assistant-design.md` 不动（历史设计，不加后见之明）

- [ ] **Step 1: 全量替换 `config.example.yaml`**

```yaml
# rok-assistant 配置示例
# 推荐用 GUI 配置：python -m rok_assistant.gui.main_window → 「⚙ 配置」
# 手动编辑后校验：
#   python -c "from rok_assistant.infra.config import load_config; from pathlib import Path; print(load_config(Path('config.yaml')))"

app:
  screen_width: 1920        # 模板按 1920x1080 中文 UI 采集，勿改
  screen_height: 1080
  locale: zh-CN
  mumu_manager_path: "C:\\模拟器\\MuMuPlayer\\nx_main\\MuMuManager.exe"  # MuMu 安装目录下
  adb_path: "C:\\模拟器\\MuMuPlayer\\nx_main\\adb.exe"
  anti_detection:
    click_offset_px: 8
    action_delay_min: 0.1
    action_delay_max: 0.5
    state_delay_min: 0.3
    state_delay_max: 1.2
    jitter_ratio: 0.3
    debug_no_jitter: false  # 调试时改 true 看真实点击坐标

# 1 个模拟器实例 = 1 个账号 = 1 组角色（同实例多账号切换暂不支持）
# 接入方式二选一：mumu_index（推荐，adb 地址自动发现）或 adb_address（手动）
instances:
  - id: mumu0
    name: "阑珊号"
    mumu_index: 0
    characters:
      # 每个实例至少 1 个 leader/either；角色名不能重复
      - id: char_leader
        name: "阑珊寨子号"      # 必须和游戏内显示名一致（OCR 验证用）
        role: leader            # leader=车头 | member=成员 | either=车头或成员
        target_level: 7         # 打的寨子等级，1-10
        march_preset: 1         # 组建部队弹窗里的预设槽位，1-5
        march_troop_types: [infantry]

      - id: char_either
        name: "阑珊种地"
        role: either            # 先自己开寨集结，随即去填 fill_target_leaders 的集结
        target_level: 7
        march_preset: 1
        march_troop_types: [infantry]
        fill_target_leaders:    # member/either 必填；leader 不能填
          - { instance: mumu0, name: "阑珊寨子号" }

      - id: char_member
        name: "阑珊挖矿"
        role: member
        target_level: 7
        march_preset: 1
        march_troop_types: [infantry]
        fill_target_leaders:    # 可跨实例：指向其他 instances 里 leader/either 的角色
          - { instance: mumu0, name: "阑珊寨子号" }

  # 第二个实例（多开 MuMu 实例 1）示例骨架：
  # - id: mumu1
  #   name: "二号机"
  #   mumu_index: 1
  #   characters: []
```

- [ ] **Step 2: 更新 `docs/ACCEPTANCE.md`**

`## 当前状态` 表中「用户 config」行改为：

```markdown
| 用户 config | ❌ 待写 | 阵容待用户确认；schema 已升级为 instances（GUI「⚙ 配置」可直接编辑） |
```

`## §2 写你的 config.yaml` 整节替换为：

```markdown
## §2 写你的 config.yaml

**推荐方式：** 启动 GUI（`python -m rok_assistant.gui.main_window`），点「⚙ 配置」，在左树右表单界面里配置全局路径、实例（MuMu 实例号）与角色阵容（分工/等级/预设/兵种/填兵目标），保存时自动校验。配置前先用实例页「测试连接」确认连对了模拟器。

**手动方式：** 复制 `config.example.yaml` 为 `config.yaml` 修改。要点：
- `instances` 取代旧 `accounts`；1 实例 = 1 账号；`mumu_index` 与 `adb_address` 二选一
- `role`: `leader`（车头，自己开寨）/ `member`（成员，只填兵）/ `either`（先开寨再填兵）
- `member`/`either` 必填 `fill_target_leaders`（显式列表，可跨实例）；`leader` 不能配
- `target_level` / `march_preset` / `march_troop_types` 对每个角色必填
- 校验命令见 `config.example.yaml` 头部注释
```

- [ ] **Step 3: 全量回归 + Commit**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS

```bash
git add config.example.yaml docs/ACCEPTANCE.md
git commit -m "docs: instances-format config example + acceptance guide for GUI config"
```

---

## Self-Review 记录

1. **Spec 覆盖**：§2 schema→Task 1；§3 MumuLocator→Task 2；工厂→Task 3；§4 either→Task 4；§5 GUI（骨架/全局/YAML→Task 5，实例/角色→Task 6，测试连接/集成/移除旧编辑器→Task 7）；§6 测试策略→各任务内嵌；§7 交付物→Task 8 文档收尾。无缺口。
2. **占位符扫描**：无 TBD/TODO；Task 4 Step 9 的 member_sm OCR 简化沿用现有代码的既定 TODO 语义并已注明（非本次范围）。
3. **类型一致性**：`FillLeader{instance, name}` 贯穿 schema（Task 1）、member_sm 测试数据（Task 4 Step 9）、GUI 填兵选择器（Task 6）；`create_handle_source(mumu_index=..., mumu_manager_path=...)` 签名在 Task 3 定义、Task 7 调用一致；`EitherStateMachine` 构造参数在 Task 4 定义与测试一致。
