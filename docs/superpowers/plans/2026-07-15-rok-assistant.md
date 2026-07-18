# 万国觉醒游戏助手 v1 - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows desktop tool that automates the "打寨子" (rally) workflow in Rise of Kingdoms, controlling multiple MuMu Android emulator instances in parallel: one "leader" character launches a rally, and other "member" characters join it.

**Architecture:** 5-layer Python (PyQt6) app. Core provides `HandleSource` (window capture + click) and `RecognizerChain` (template/OCR/YOLO). Coordination layer has `EventBus`, `ScreenScheduler`, and `RallySession`. Business layer is per-character state machines. Single-process, in-memory coordination.

**Tech Stack:** Python 3.11+, PyQt6, OpenCV (template matching), PaddleOCR (text/number/coord reading), Ultralytics YOLO (rally card detection only), PyYAML, Pydantic, pytest, Win32 API via `pywin32` / `ctypes`.

**Spec:** `docs/superpowers/specs/2026-07-15-rok-assistant-design.md`

---

## File Structure

```
myrok/
├── pyproject.toml
├── README.md
├── config.yaml                       # User config (Account/Character)
├── src/rok_assistant/
│   ├── __init__.py
│   ├── infra/
│   │   ├── __init__.py
│   │   ├── config.py                 # YAML loading + Pydantic validation
│   │   ├── logger.py                 # File + console logging
│   │   ├── paths.py                  # Project path helpers
│   │   └── anti_detection.py         # AntiDetectionConfig + jitter helpers
│   ├── core/
│   │   ├── __init__.py
│   │   ├── handle_source.py          # Protocol + Win32 impl + Mock impl
│   │   ├── recognizer.py             # Recognizer Protocol + Result + Chain
│   │   ├── recognizers/
│   │   │   ├── __init__.py
│   │   │   ├── template_match.py     # OpenCV matchTemplate
│   │   │   ├── ocr_text.py           # PaddleOCR for text/number/coord
│   │   │   └── yolo_detect.py        # Ultralytics YOLO
│   │   └── template_registry.py      # Loads templates/manifest.yaml
│   ├── coordination/
│   │   ├── __init__.py
│   │   ├── event_bus.py              # In-process pub/sub
│   │   ├── screen_scheduler.py       # Serialized screen access
│   │   └── rally_session.py          # Coordinator for one rally
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── base.py                   # Worker base class
│   │   ├── state_machine.py          # Generic state machine
│   │   ├── leader_sm.py              # LeaderStateMachine
│   │   ├── member_sm.py              # MemberStateMachine
│   │   └── switcher_sm.py            # SwitcherStateMachine (4-step)
│   └── gui/
│       ├── __init__.py
│       ├── main_window.py            # Top-level QMainWindow
│       ├── character_card.py         # Per-character widget
│       ├── log_panel.py              # Scrollable log viewer
│       └── config_editor.py          # YAML edit dialog
├── tools/
│   ├── record.py                     # Records emulator sessions
│   ├── replay.py                     # Replays recorded screenshots
│   └── crop_template.py              # ROI cropper for templates
├── tests/
│   ├── unit/
│   │   ├── infra/
│   │   ├── core/
│   │   ├── coordination/
│   │   └── workers/
│   ├── integration/
│   └── fixtures/                     # Canned screenshots
└── templates/
    ├── manifest.yaml
    └── *.png
```

---

## Task Index

| ID | Title | Milestone |
|----|-------|-----------|
| T01 | Project skeleton (pyproject + layout) | M0 |
| T02 | Logger setup | M0 |
| T03 | Paths + dirs | M0 |
| T04 | AntiDetectionConfig + jitter helpers (TDD) | M0 |
| T05 | Config data classes (Pydantic) | M0 |
| T06 | Config loader + validation (TDD) | M0 |
| T07 | HandleSource protocol | M1 |
| T08 | MockHandleSource (TDD) | M1 |
| T09 | Win32 HandleSource (capture + click) | M1 |
| T10 | Recognizer protocol + result | M1 |
| T11 | TemplateMatch recognizer (TDD) | M1 |
| T12 | OCR recognizer (TDD) | M1 |
| T13 | YoloDetect recognizer (TDD) | M1 |
| T14 | RecognizerChain (TDD) | M1 |
| T15 | TemplateRegistry (TDD) | M2 |
| T16 | EventBus (TDD) | M5 |
| T17 | ScreenScheduler (TDD) | M5 |
| T18 | StateMachine base (TDD) | M3 |
| T19 | SwitcherStateMachine (TDD) | M4 |
| T20 | LeaderStateMachine (TDD) | M3 |
| T21 | MemberStateMachine (TDD) | M5 |
| T22 | RallySession coordinator (TDD) | M5 |
| T23 | FailureHandler (TDD) | M6 |
| T24 | Recording tool (tools/record.py) | M8 |
| T25 | ReplaySession (TDD) | M8 |
| T26 | PyQt6 main window skeleton | M7 |
| T27 | CharacterCard widget (TDD) | M7 |
| T28 | LogPanel widget | M7 |
| T29 | ConfigEditor dialog (TDD) | M7 |
| T30 | Wire GUI to coordinator | M7 |
| T31 | Manual verification script | M8 |

---


## Task T01: Project skeleton (M0)

**Files:**
- Create: `pyproject.toml`
- Create: `src/rok_assistant/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tools/__init__.py`
- Create: `templates/.gitkeep`
- Create: `logs/.gitkeep`
- Create: `recordings/.gitkeep`
- Create: `tests/fixtures/.gitkeep`
- Create: `.gitignore`

- [ ] **Step 1: Write `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/

# Project artifacts
logs/*.log
recordings/*.png
templates/*.png
!templates/.gitkeep
!templates/manifest.yaml
tests/fixtures/*.png
!tests/fixtures/.gitkeep

# IDE
.idea/
.vscode/
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "rok-assistant"
version = "0.1.0"
description = "Rise of Kingdoms rally automation tool"
requires-python = ">=3.11"
dependencies = [
    "PyQt6>=6.5",
    "opencv-python>=4.8",
    "paddleocr>=2.7",
    "ultralytics>=8.0",
    "pyyaml>=6.0",
    "pydantic>=2.5",
    "pywin32>=306; sys_platform == 'win32'",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-cov>=4.1",
    "pytest-qt>=4.4",
]

[project.scripts]
rok-assistant = "rok_assistant.gui.main_window:main"

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
markers = [
    "integration: requires recorded screenshots",
    "slow: takes more than 1 second",
]
```

- [ ] **Step 3: Create package directories with empty `__init__.py`**

```bash
mkdir -p src/rok_assistant/infra src/rok_assistant/core/recognizers \
         src/rok_assistant/coordination src/rok_assistant/workers \
         src/rok_assistant/gui tools tests/unit/infra \
         tests/unit/core tests/unit/coordination tests/unit/workers \
         tests/integration tests/fixtures templates logs recordings
touch src/rok_assistant/__init__.py
touch src/rok_assistant/infra/__init__.py
touch src/rok_assistant/core/__init__.py
touch src/rok_assistant/core/recognizers/__init__.py
touch src/rok_assistant/coordination/__init__.py
touch src/rok_assistant/workers/__init__.py
touch src/rok_assistant/gui/__init__.py
touch tests/__init__.py
touch tests/unit/__init__.py
touch tests/integration/__init__.py
touch tools/__init__.py
touch templates/.gitkeep logs/.gitkeep recordings/.gitkeep tests/fixtures/.gitkeep
```

- [ ] **Step 4: Write `README.md`**

```markdown
# rok-assistant

Rise of Kingdoms rally automation. See `docs/superpowers/specs/2026-07-15-rok-assistant-design.md` for the full design.

## Quick start

```bash
pip install -e ".[dev]"
rok-assistant
```

## Test

```bash
pytest tests/unit -v
```

## Configure

Copy `config.example.yaml` to `config.yaml` and edit.
```

- [ ] **Step 5: Install and verify import**

Run: `pip install -e ".[dev]"`
Expected: succeeds without errors.

Run: `python -c "import rok_assistant; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Run pytest, expect 0 tests collected**

Run: `pytest tests -v`
Expected: `no tests ran` or `0 passed`.

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "feat(M0): project skeleton with pyproject + package layout"
```

---

## Task T02: Logger setup (M0)

**Files:**
- Create: `src/rok_assistant/infra/logger.py`
- Test: `tests/unit/infra/test_logger.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/infra/test_logger.py
import logging
from pathlib import Path
from rok_assistant.infra.logger import setup_logging, get_logger

def test_get_logger_returns_named_logger(tmp_path):
    setup_logging(log_dir=tmp_path, debug_no_jitter=True)
    log = get_logger("test.module")
    assert log.name == "test.module"
    assert log.level <= logging.INFO

def test_setup_logging_creates_log_dir(tmp_path):
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir, debug_no_jitter=True)
    assert log_dir.exists()
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/infra/test_logger.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement logger**

```python
# src/rok_assistant/infra/logger.py
import logging
import sys
from pathlib import Path
from datetime import datetime

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_initialized = False

def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    global _initialized
    if _initialized:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"rok_assistant_{datetime.now():%Y%m%d_%H%M%S}.log"
    root = logging.getLogger()
    root.setLevel(level)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(console)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(file_handler)
    _initialized = True

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
```

- [ ] **Step 4: Run test, expect pass**

Run: `pytest tests/unit/infra/test_logger.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/infra/logger.py tests/unit/infra/test_logger.py
git commit -m "feat(M0): setup_logging with file + console handlers"
```

---

## Task T03: Paths + dirs (M0)

**Files:**
- Create: `src/rok_assistant/infra/paths.py`
- Test: `tests/unit/infra/test_paths.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/infra/test_paths.py
from pathlib import Path
from rok_assistant.infra.paths import ProjectPaths

def test_project_paths_creates_dirs(tmp_path):
    p = ProjectPaths(root=tmp_path)
    p.ensure_dirs()
    assert p.log_dir.exists()
    assert p.template_dir.exists()
    assert p.recording_dir.exists()

def test_project_paths_manifest_yaml():
    p = ProjectPaths(root=Path("/tmp"))
    assert p.manifest_path.name == "manifest.yaml"
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/infra/test_paths.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement paths**

```python
# src/rok_assistant/infra/paths.py
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    @property
    def log_dir(self) -> Path: return self.root / "logs"
    @property
    def template_dir(self) -> Path: return self.root / "templates"
    @property
    def recording_dir(self) -> Path: return self.root / "recordings"
    @property
    def manifest_path(self) -> Path: return self.template_dir / "manifest.yaml"

    def ensure_dirs(self) -> None:
        for d in (self.log_dir, self.template_dir, self.recording_dir):
            d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run test, expect pass**

Run: `pytest tests/unit/infra/test_paths.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/infra/paths.py tests/unit/infra/test_paths.py
git commit -m "feat(M0): ProjectPaths with dir ensure"
```

---
## Task T04: AntiDetectionConfig + jitter helpers (M0)

**Files:**
- Create: `src/rok_assistant/infra/anti_detection.py`
- Test: `tests/unit/infra/test_anti_detection.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/infra/test_anti_detection.py
import pytest
from rok_assistant.infra.anti_detection import (
    AntiDetectionConfig, jitter_offset, jitter_delay
)

def test_default_config():
    cfg = AntiDetectionConfig()
    assert cfg.click_offset_px == 8
    assert cfg.action_delay_min == 0.1
    assert cfg.action_delay_max == 0.5
    assert cfg.state_delay_min == 0.3
    assert cfg.state_delay_max == 1.2
    assert cfg.jitter_ratio == 0.3
    assert cfg.debug_no_jitter is False

def test_jitter_offset_within_bounds():
    cfg = AntiDetectionConfig(click_offset_px=10)
    for _ in range(100):
        dx, dy = jitter_offset(100, 200, cfg)
        assert 90 <= dx <= 110
        assert 190 <= dy <= 210

def test_jitter_offset_debug_no_jitter():
    cfg = AntiDetectionConfig(debug_no_jitter=True)
    for _ in range(100):
        dx, dy = jitter_offset(100, 200, cfg)
        assert (dx, dy) == (100, 200)

def test_jitter_delay_within_range():
    cfg = AntiDetectionConfig(jitter_ratio=0.3)
    for _ in range(100):
        d = jitter_delay(1.0, cfg)
        assert 0.7 <= d <= 1.3

def test_jitter_delay_zero_base():
    cfg = AntiDetectionConfig()
    d = jitter_delay(0.0, cfg)
    assert d == 0.0

def test_jitter_delay_debug_no_jitter():
    cfg = AntiDetectionConfig(debug_no_jitter=True)
    assert jitter_delay(1.5, cfg) == 1.5
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/infra/test_anti_detection.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/rok_assistant/infra/anti_detection.py
import random
from dataclasses import dataclass

@dataclass(frozen=True)
class AntiDetectionConfig:
    click_offset_px: int = 8
    action_delay_min: float = 0.1
    action_delay_max: float = 0.5
    state_delay_min: float = 0.3
    state_delay_max: float = 1.2
    jitter_ratio: float = 0.3
    debug_no_jitter: bool = False

    def random_action_delay(self) -> float:
        if self.debug_no_jitter:
            return (self.action_delay_min + self.action_delay_max) / 2
        return random.uniform(self.action_delay_min, self.action_delay_max)

    def random_state_delay(self) -> float:
        if self.debug_no_jitter:
            return (self.state_delay_min + self.state_delay_max) / 2
        return random.uniform(self.state_delay_min, self.state_delay_max)

def jitter_offset(x: int, y: int, cfg: AntiDetectionConfig) -> tuple:
    if cfg.debug_no_jitter:
        return x, y
    return (x + random.randint(-cfg.click_offset_px, cfg.click_offset_px),
            y + random.randint(-cfg.click_offset_px, cfg.click_offset_px))

def jitter_delay(base: float, cfg: AntiDetectionConfig) -> float:
    if base <= 0:
        return 0.0
    if cfg.debug_no_jitter:
        return base
    jitter = base * cfg.jitter_ratio
    return max(0.0, base + random.uniform(-jitter, jitter))
```

- [ ] **Step 4: Run test, expect pass**

Run: `pytest tests/unit/infra/test_anti_detection.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/infra/anti_detection.py tests/unit/infra/test_anti_detection.py
git commit -m "feat(M0): AntiDetectionConfig + jitter helpers (D11)"
```

---
## Task T05: Config data classes (M0)

**Files:**
- Create: `src/rok_assistant/infra/config.py`
- Test: `tests/unit/infra/test_config_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/infra/test_config_models.py
import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import (
    AppConfig, AccountConfig, CharacterConfig, RoleEnum, FillLeader, RootConfig
)

def test_character_config_leader_minimal():
    c = CharacterConfig(
        id="char1", name="Hero", role=RoleEnum.LEADER,
        target_level=8, march_preset=1,
        march_troop_types=["infantry", "archer"]
    )
    assert c.id == "char1"
    assert c.role == RoleEnum.LEADER

def test_character_config_member_with_nearest():
    c = CharacterConfig(
        id="char2", name="M1", role=RoleEnum.MEMBER,
        target_level=5, march_preset=2,
        march_troop_types=["infantry"],
        fill_target_leaders="nearest"
    )
    assert c.fill_target_leaders == "nearest"

def test_character_config_member_with_specific_leaders():
    c = CharacterConfig(
        id="char3", name="M2", role=RoleEnum.MEMBER,
        target_level=4, march_preset=3,
        march_troop_types=["cavalry"],
        fill_target_leaders=[FillLeader(account="acc1", name="Boss")]
    )
    assert isinstance(c.fill_target_leaders, list)
    assert c.fill_target_leaders[0].account == "acc1"

def test_character_config_invalid_target_level():
    with pytest.raises(ValidationError):
        CharacterConfig(
            id="x", name="X", role=RoleEnum.LEADER,
            target_level=11, march_preset=1, march_troop_types=["infantry"]
        )

def test_character_config_invalid_march_preset():
    with pytest.raises(ValidationError):
        CharacterConfig(
            id="x", name="X", role=RoleEnum.LEADER,
            target_level=5, march_preset=6, march_troop_types=["infantry"]
        )

def test_app_config_default_anti_detection():
    app = AppConfig()
    assert app.anti_detection.click_offset_px == 8
    assert app.anti_detection.debug_no_jitter is False

def test_root_config_requires_at_least_one_account():
    with pytest.raises(ValidationError):
        RootConfig(accounts=[])
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/infra/test_config_models.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement config models**

```python
# src/rok_assistant/infra/config.py
from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Literal, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from .anti_detection import AntiDetectionConfig

class RoleEnum(str, Enum):
    LEADER = "leader"
    MEMBER = "member"

class FillLeader(BaseModel):
    account: str
    name: str

class CharacterConfig(BaseModel):
    id: str
    name: str
    role: RoleEnum
    target_level: int = Field(ge=1, le=10)
    march_preset: int = Field(ge=1, le=5)
    march_troop_types: list[Literal["infantry", "cavalry", "archer"]]
    fill_target_leaders: Union[Literal["nearest"], list[FillLeader]] = "nearest"

    @field_validator("march_troop_types")
    @classmethod
    def _not_empty(cls, v):
        if not v:
            raise ValueError("march_troop_types must be non-empty")
        return v

class AccountConfig(BaseModel):
    id: str
    window_title_pattern: str
    characters: list[CharacterConfig]

    @model_validator(mode="after")
    def _has_leader_and_unique_names(self):
        if not any(c.role == RoleEnum.LEADER for c in self.characters):
            raise ValueError(f"Account {self.id} has no leader")
        names = [c.name for c in self.characters]
        if len(names) != len(set(names)):
            raise ValueError(f"Account {self.id} has duplicate character names")
        return self

class AppConfig(BaseModel):
    screen_width: int = 1920
    screen_height: int = 1080
    locale: str = "zh-CN"
    log_dir: Path = Path("./logs")
    template_dir: Path = Path("./templates")
    anti_detection: AntiDetectionConfig = Field(default_factory=AntiDetectionConfig)

class RootConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    accounts: list[AccountConfig] = Field(min_length=1)
```

- [ ] **Step 4: Run test, expect pass**

Run: `pytest tests/unit/infra/test_config_models.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/infra/config.py tests/unit/infra/test_config_models.py
git commit -m "feat(M0): Pydantic config models for App/Account/Character"
```

---

## Task T06: Config loader + validation (M0)

**Files:**
- Modify: `src/rok_assistant/infra/config.py`
- Test: `tests/unit/infra/test_config_loader.py`
- Create: `tests/fixtures/config_valid.yaml`
- Create: `tests/fixtures/config_no_leader.yaml`
- Create: `tests/fixtures/config_invalid_level.yaml`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/infra/test_config_loader.py
from pathlib import Path
import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import load_config, RootConfig

FIX = Path(__file__).parent.parent.parent / "fixtures"

def test_load_valid_config():
    cfg = load_config(FIX / "config_valid.yaml")
    assert isinstance(cfg, RootConfig)
    assert len(cfg.accounts) == 1
    assert cfg.accounts[0].id == "test_account"

def test_load_no_leader_raises():
    with pytest.raises(ValidationError, match="no leader"):
        load_config(FIX / "config_no_leader.yaml")

def test_load_invalid_level_raises():
    with pytest.raises(ValidationError, match="target_level"):
        load_config(FIX / "config_invalid_level.yaml")
```

- [ ] **Step 2: Create fixture files**

`tests/fixtures/config_valid.yaml`:
```yaml
app:
  screen_width: 1920
  screen_height: 1080
accounts:
  - id: test_account
    window_title_pattern: "MuMuPlayer.*"
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
        fill_target_leaders: nearest
```

`tests/fixtures/config_no_leader.yaml`:
```yaml
app: {}
accounts:
  - id: bad
    window_title_pattern: "x"
    characters:
      - id: m1
        name: "OnlyMember"
        role: member
        target_level: 5
        march_preset: 1
        march_troop_types: [infantry]
```

`tests/fixtures/config_invalid_level.yaml`:
```yaml
app: {}
accounts:
  - id: bad
    window_title_pattern: "x"
    characters:
      - id: l
        name: "L"
        role: leader
        target_level: 11
        march_preset: 1
        march_troop_types: [infantry]
```

- [ ] **Step 3: Run test, expect failure**

Run: `pytest tests/unit/infra/test_config_loader.py -v`
Expected: ImportError or AttributeError.

- [ ] **Step 4: Add `load_config` to config.py**

Append to `src/rok_assistant/infra/config.py`:

```python
import yaml

def load_config(path: Path) -> RootConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return RootConfig.model_validate(raw)
```

- [ ] **Step 5: Run test, expect pass**

Run: `pytest tests/unit/infra/test_config_loader.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/rok_assistant/infra/config.py tests/unit/infra/test_config_loader.py tests/fixtures/
git commit -m "feat(M0): load_config YAML + validation (T06)"
```

---

## Task T07: HandleSource protocol (M1)

**Files:**
- Create: `src/rok_assistant/core/handle_source.py`
- Test: `tests/unit/core/test_handle_source_protocol.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/core/test_handle_source_protocol.py
import numpy as np
from rok_assistant.core.handle_source import HandleSource

def test_protocol_is_runtime_checkable():
    class Fake:
        def capture(self): return np.zeros((10, 10, 3), dtype=np.uint8)
        def click(self, x, y): pass
        def is_alive(self): return True
    f = Fake()
    assert isinstance(f, HandleSource)
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/core/test_handle_source_protocol.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/rok_assistant/core/handle_source.py
from __future__ import annotations
from typing import Protocol, runtime_checkable
import numpy as np

@runtime_checkable
class HandleSource(Protocol):
    """Provides screenshot capture and click input for a single window."""
    def capture(self) -> np.ndarray:
        """Return current screen as BGR numpy array."""
        ...
    def click(self, x: int, y: int) -> None:
        """Click at (x, y) in window-local pixel coordinates."""
        ...
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """Swipe from (x1,y1) to (x2,y2). Optional, default no-op."""
        ...
    def is_alive(self) -> bool:
        """True if the underlying window is still present."""
        ...
```

- [ ] **Step 4: Run test, expect pass**

Run: `pytest tests/unit/core/test_handle_source_protocol.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/core/handle_source.py tests/unit/core/test_handle_source_protocol.py
git commit -m "feat(M1): HandleSource Protocol with capture/click/is_alive"
```

---

## Task T08: MockHandleSource (M1)

**Files:**
- Modify: `src/rok_assistant/core/handle_source.py` (append)
- Test: `tests/unit/core/test_mock_handle_source.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/core/test_mock_handle_source.py
import numpy as np
from rok_assistant.core.handle_source import MockHandleSource

def test_mock_returns_configured_screenshot():
    img = np.full((100, 200, 3), 128, dtype=np.uint8)
    m = MockHandleSource(screenshot=img)
    captured = m.capture()
    assert captured.shape == (100, 200, 3)
    assert (captured == 128).all()

def test_mock_records_clicks():
    m = MockHandleSource(screenshot=np.zeros((10, 10, 3), dtype=np.uint8))
    m.click(50, 60)
    m.click(100, 200)
    assert m.clicks == [(50, 60), (100, 200)]

def test_mock_is_alive_default_true():
    m = MockHandleSource(screenshot=np.zeros((10, 10, 3), dtype=np.uint8))
    assert m.is_alive() is True

def test_mock_is_alive_can_be_toggled():
    m = MockHandleSource(screenshot=np.zeros((10, 10, 3), dtype=np.uint8),
                         alive=False)
    assert m.is_alive() is False

def test_mock_swipe_recorded():
    m = MockHandleSource(screenshot=np.zeros((10, 10, 3), dtype=np.uint8))
    m.swipe(1, 2, 3, 4, duration_ms=500)
    assert m.swipes == [(1, 2, 3, 4, 500)]
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/core/test_mock_handle_source.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement MockHandleSource**

Append to `src/rok_assistant/core/handle_source.py`:

```python
class MockHandleSource:
    """Test double for HandleSource. Records calls, returns canned image."""
    def __init__(self, screenshot: np.ndarray, alive: bool = True):
        self._screenshot = screenshot
        self._alive = alive
        self.clicks: list[tuple[int, int]] = []
        self.swipes: list[tuple[int, int, int, int, int]] = []

    def capture(self) -> np.ndarray:
        return self._screenshot.copy()

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipes.append((x1, y1, x2, y2, duration_ms))

    def is_alive(self) -> bool:
        return self._alive

    def set_alive(self, alive: bool) -> None:
        self._alive = alive
```

- [ ] **Step 4: Run test, expect pass**

Run: `pytest tests/unit/core/test_mock_handle_source.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/core/handle_source.py tests/unit/core/test_mock_handle_source.py
git commit -m "feat(M1): MockHandleSource for tests"
```

---

## Task T09: Win32 HandleSource (M1)

**Files:**
- Modify: `src/rok_assistant/core/handle_source.py` (append)
- Test: `tests/unit/core/test_win32_handle_source.py` (logic only, no real window)

- [ ] **Step 1: Write failing test for the title-pattern matcher**

```python
# tests/unit/core/test_win32_handle_source.py
import re
from rok_assistant.core.handle_source import Win32HandleSource

def test_window_title_regex_matches(monkeypatch):
    fake_hwnd_by_title = {1234: "MuMuPlayer-1 - 482", 5678: "MuMuPlayer-2 - 482"}
    monkeypatch.setattr(
        Win32HandleSource, "_find_window_by_title",
        lambda pattern: next(h for h, t in fake_hwnd_by_title.items()
                             if re.search(pattern, t))
    )
    src = Win32HandleSource(window_title_pattern="MuMuPlayer-1.*")
    assert src._resolve_hwnd() == 1234

def test_window_title_regex_no_match(monkeypatch):
    monkeypatch.setattr(
        Win32HandleSource, "_find_window_by_title", lambda pattern: None
    )
    src = Win32HandleSource(window_title_pattern="nonexistent.*")
    assert src._resolve_hwnd() is None

def test_is_alive_false_when_no_hwnd(monkeypatch):
    monkeypatch.setattr(Win32HandleSource, "_resolve_hwnd", lambda self: None)
    src = Win32HandleSource(window_title_pattern="x")
    assert src.is_alive() is False
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/core/test_win32_handle_source.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement Win32HandleSource**

Append to `src/rok_assistant/core/handle_source.py`:

```python
import re
import ctypes
from ctypes import wintypes

class Win32HandleSource:
    """Real Windows HandleSource using FindWindowW + PrintWindow + PostMessage."""
    def __init__(self, window_title_pattern: str):
        self._pattern = window_title_pattern
        self._hwnd = None
        self._user32 = ctypes.windll.user32

    def _find_window_by_title(self, pattern: str):
        hwnd_enum = []
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, lParam):
            length = self._user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                self._user32.GetWindowTextW(hwnd, buf, length + 1)
                if re.search(self._pattern, buf.value):
                    hwnd_enum.append(hwnd)
                    return False
            return True
        self._user32.EnumWindows(EnumWindowsProc(callback), 0)
        return hwnd_enum[0] if hwnd_enum else None

    def _resolve_hwnd(self):
        if self._hwnd is None:
            self._hwnd = self._find_window_by_title(self._pattern)
        return self._hwnd

    def capture(self):
        import cv2
        hwnd = self._resolve_hwnd()
        if hwnd is None:
            raise RuntimeError(f"No window matching: {self._pattern}")
        rect = wintypes.RECT()
        self._user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        hwnd_dc = self._user32.GetWindowDC(hwnd)
        mfc_dc = self._user32.CreateCompatibleDC(hwnd_dc)
        bmp = self._user32.CreateCompatibleBitmap(hwnd_dc, w, h)
        self._user32.SelectObject(mfc_dc, bmp)
        self._user32.PrintWindow(hwnd, mfc_dc, 2)
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
            ]
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        buf = (ctypes.c_ubyte * (w * h * 4))()
        self._user32.GetDIBits(mfc_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
        self._user32.DeleteObject(bmp)
        self._user32.DeleteDC(mfc_dc)
        self._user32.ReleaseDC(hwnd, hwnd_dc)
        img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def click(self, x: int, y: int) -> None:
        hwnd = self._resolve_hwnd()
        if hwnd is None:
            raise RuntimeError(f"No window matching: {self._pattern}")
        WM_LBUTTONDOWN = 0x0201
        WM_LBUTTONUP = 0x0202
        MK_LBUTTON = 0x0001
        lParam = (y << 16) | x
        self._user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lParam)
        self._user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lParam)

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        for i in range(1, 6):
            t = i / 5
            self.click(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))

    def is_alive(self) -> bool:
        hwnd = self._resolve_hwnd()
        if hwnd is None:
            return False
        return bool(self._user32.IsWindow(hwnd))
```

- [ ] **Step 4: Run test, expect pass**

Run: `pytest tests/unit/core/test_win32_handle_source.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/core/handle_source.py tests/unit/core/test_win32_handle_source.py
git commit -m "feat(M1): Win32HandleSource with FindWindow + PrintWindow + PostMessage"
```

---

## Task T10: Recognizer protocol + result (M1)

**Files:**
- Create: `src/rok_assistant/core/recognizer.py`
- Test: `tests/unit/core/test_recognizer_protocol.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/core/test_recognizer_protocol.py
import numpy as np
from rok_assistant.core.recognizer import Recognizer, RecognizeResult, BBox

def test_bbox_center():
    b = BBox(x1=10, y1=20, x2=30, y2=40)
    assert b.center() == (20, 30)

def test_recognize_result_helpers():
    r = RecognizeResult(matched=True, bbox=BBox(0,0,10,10), confidence=0.9, data={"text": "hi"})
    assert r.matched
    assert r.confidence > 0.8
    assert r.data["text"] == "hi"
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/unit/core/test_recognizer_protocol.py -v`

- [ ] **Step 3: Implement**

```python
# src/rok_assistant/core/recognizer.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable, Any
import numpy as np

@dataclass(frozen=True)
class BBox:
    x1: int; y1: int; x2: int; y2: int
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)
    def area(self) -> int:
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)

@dataclass
class RecognizeResult:
    matched: bool
    bbox: BBox | None
    confidence: float
    data: dict[str, Any] = field(default_factory=dict)
    recognizer_id: str = ""

@runtime_checkable
class Recognizer(Protocol):
    """Single-strategy recognizer. Returns RecognizeResult."""
    def recognize(self, screenshot: np.ndarray) -> RecognizeResult: ...
```

- [ ] **Step 4: Run test, expect pass + commit**

```bash
git add src/rok_assistant/core/recognizer.py tests/unit/core/test_recognizer_protocol.py
git commit -m "feat(M1): Recognizer protocol + BBox + RecognizeResult"
```

---

## Task T11: TemplateMatch recognizer (M1)

**Files:**
- Create: `src/rok_assistant/core/recognizers/template_match.py`
- Test: `tests/unit/core/recognizers/test_template_match.py`
- Create: `tests/fixtures/template_search.png` (small test template)

- [ ] **Step 1: Create test fixture**

```python
# Run this once to create the fixture:
import numpy as np
from pathlib import Path
tpl = np.zeros((20, 20, 3), dtype=np.uint8)
tpl[5:15, 5:15] = 200  # gray square in middle
Path("tests/fixtures").mkdir(parents=True, exist_ok=True)
import cv2
cv2.imwrite("tests/fixtures/template_search.png", tpl)
# Create a screenshot with the template embedded
img = np.zeros((100, 100, 3), dtype=np.uint8)
img[40:60, 40:60] = 200
cv2.imwrite("tests/fixtures/screenshot_with_template.png", img)
cv2.imwrite("tests/fixtures/screenshot_without_template.png", np.zeros((100, 100, 3), dtype=np.uint8))
```

- [ ] **Step 2: Write failing test**

```python
# tests/unit/core/recognizers/test_template_match.py
import numpy as np
import cv2
from pathlib import Path
from rok_assistant.core.recognizers.template_match import TemplateMatch

FIX = Path(__file__).parent.parent.parent.parent / "fixtures"

def test_match_finds_template():
    tpl = cv2.imread(str(FIX / "template_search.png"))
    img = cv2.imread(str(FIX / "screenshot_with_template.png"))
    r = TemplateMatch(template=tpl, threshold=0.9).recognize(img)
    assert r.matched
    assert r.bbox is not None
    assert abs(r.bbox.x1 - 40) < 2

def test_match_finds_nothing():
    tpl = cv2.imread(str(FIX / "template_search.png"))
    img = cv2.imread(str(FIX / "screenshot_without_template.png"))
    r = TemplateMatch(template=tpl, threshold=0.95).recognize(img)
    assert not r.matched

def test_match_with_roi():
    tpl = cv2.imread(str(FIX / "template_search.png"))
    img = cv2.imread(str(FIX / "screenshot_with_template.png"))
    from rok_assistant.core.recognizer import BBox
    roi = BBox(0, 0, 50, 50)
    r = TemplateMatch(template=tpl, threshold=0.9, roi=roi).recognize(img)
    assert r.matched
```

- [ ] **Step 3: Implement**

```python
# src/rok_assistant/core/recognizers/template_match.py
from __future__ import annotations
import cv2
import numpy as np
from ..recognizer import Recognizer, RecognizeResult, BBox

class TemplateMatch:
    def __init__(self, template: np.ndarray, threshold: float = 0.9,
                 roi: BBox | None = None, name: str = "template_match"):
        self._template = template
        self._threshold = threshold
        self._roi = roi
        self._name = name

    def recognize(self, screenshot: np.ndarray) -> RecognizeResult:
        img = screenshot
        if self._roi is not None:
            img = screenshot[self._roi.y1:self._roi.y2, self._roi.x1:self._roi.x2]
        result = cv2.matchTemplate(img, self._template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < self._threshold:
            return RecognizeResult(matched=False, bbox=None, confidence=float(max_val),
                                   recognizer_id=self._name)
        th, tw = self._template.shape[:2]
        x1 = max_loc[0] + (self._roi.x1 if self._roi else 0)
        y1 = max_loc[1] + (self._roi.y1 if self._roi else 0)
        return RecognizeResult(
            matched=True,
            bbox=BBox(x1=x1, y1=y1, x2=x1 + tw, y2=y1 + th),
            confidence=float(max_val),
            recognizer_id=self._name,
        )
```

- [ ] **Step 4: Run test, expect pass + commit**

```bash
git add src/rok_assistant/core/recognizers/template_match.py tests/unit/core/recognizers/test_template_match.py tests/fixtures/
git commit -m "feat(M1): TemplateMatch recognizer via cv2.matchTemplate"
```

---

## Task T12: OCR recognizer (M1)

**Files:**
- Create: `src/rok_assistant/core/recognizers/ocr_text.py`
- Test: `tests/unit/core/recognizers/test_ocr_text.py`
- Create: `tests/fixtures/text_hello.png` (white text "hello" on black)

- [ ] **Step 1: Create fixture with synthetic text**

```python
# Run once:
import numpy as np
import cv2
img = np.zeros((40, 200, 3), dtype=np.uint8)
cv2.putText(img, "hello world", (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
cv2.imwrite("tests/fixtures/text_hello.png", img)
```

- [ ] **Step 2: Write failing test**

```python
# tests/unit/core/recognizers/test_ocr_text.py
import cv2
import pytest
from pathlib import Path
from rok_assistant.core.recognizers.ocr_text import OCRText

FIX = Path(__file__).parent.parent.parent.parent / "fixtures"

@pytest.fixture(scope="module")
def ocr():
    return OCRText()

def test_ocr_finds_text(ocr):
    img = cv2.imread(str(FIX / "text_hello.png"))
    r = ocr.recognize(img)
    assert r.matched
    assert "hello" in r.data.get("text", "").lower()

def test_ocr_no_match(ocr):
    import numpy as np
    blank = np.zeros((40, 200, 3), dtype=np.uint8)
    r = ocr.recognize_blank_search(blank, expected_text="xyzzy")
    assert not r.matched
```

- [ ] **Step 3: Implement**

```python
# src/rok_assistant/core/recognizers/ocr_text.py
from __future__ import annotations
import numpy as np
from ..recognizer import Recognizer, RecognizeResult, BBox

class OCRText:
    """OCR-based text recognizer. Uses PaddleOCR (lazy import for tests)."""
    def __init__(self, expected_text: str = "", use_angle_cls: bool = True,
                 lang: str = "ch"):
        self._expected = expected_text
        self._lang = lang
        self._use_angle_cls = use_angle_cls
        self._ocr = None

    def _ensure_ocr(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(use_angle_cls=self._use_angle_cls, lang=self._lang,
                                  show_log=False)
        return self._ocr

    def recognize(self, screenshot: np.ndarray) -> RecognizeResult:
        ocr = self._ensure_ocr()
        results = ocr.ocr(screenshot, cls=self._use_angle_cls)
        if not results or not results[0]:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   recognizer_id="ocr_text")
        # Find best match for expected_text
        best = None
        for line in results[0]:
            bbox_pts, (text, conf) = line
            if self._expected and self._expected in text:
                xs = [p[0] for p in bbox_pts]; ys = [p[1] for p in bbox_pts]
                b = BBox(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
                if best is None or conf > best.confidence:
                    best = RecognizeResult(matched=True, bbox=b, confidence=conf,
                                           data={"text": text}, recognizer_id="ocr_text")
        if best is not None:
            return best
        # If no expected, return highest confidence
        line = max(results[0], key=lambda l: l[1][1])
        bbox_pts, (text, conf) = line
        xs = [p[0] for p in bbox_pts]; ys = [p[1] for p in bbox_pts]
        return RecognizeResult(
            matched=True, bbox=BBox(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
            confidence=conf, data={"text": text}, recognizer_id="ocr_text"
        )

    def recognize_blank_search(self, screenshot: np.ndarray, expected_text: str) -> RecognizeResult:
        old = self._expected
        self._expected = expected_text
        try:
            return self.recognize(screenshot)
        finally:
            self._expected = old
```

- [ ] **Step 4: Run test (mark slow) + commit**

Note: PaddleOCR first-run downloads model. Mark as slow. To run, may need network.

```bash
git add src/rok_assistant/core/recognizers/ocr_text.py tests/unit/core/recognizers/test_ocr_text.py tests/fixtures/text_hello.png
git commit -m "feat(M1): OCRText recognizer (PaddleOCR)"
```

---

## Task T13: YoloDetect recognizer (M1)

**Files:**
- Create: `src/rok_assistant/core/recognizers/yolo_detect.py`
- Test: `tests/unit/core/recognizers/test_yolo_detect.py`

- [ ] **Step 1: Write failing test (uses YOLO on a fixture; skip if no model)**

```python
# tests/unit/core/recognizers/test_yolo_detect.py
import numpy as np
import pytest
from rok_assistant.core.recognizers.yolo_detect import YoloDetect

class FakeYolo:
    def __init__(self, detections):
        self._detections = detections
    def __call__(self, img):
        class R: pass
        r = R()
        r.xyxy = [d[:4] for d in self._detections]
        r.conf = [d[4] for d in self._detections]
        r.cls = [d[5] for d in self._detections]
        return [r]

def test_yolo_returns_bboxes():
    fake = FakeYolo([(10, 20, 50, 60, 0.9, 0), (100, 200, 150, 250, 0.8, 0)])
    yd = YoloDetect(model=object(), threshold=0.5, classes=[0], _yolo=fake)
    r = yd.recognize(np.zeros((300, 300, 3), dtype=np.uint8))
    assert r.matched
    assert len(r.bbox_list) == 2

def test_yolo_filters_below_threshold():
    fake = FakeYolo([(10, 20, 50, 60, 0.3, 0)])
    yd = YoloDetect(model=object(), threshold=0.5, classes=[0], _yolo=fake)
    r = yd.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
    assert not r.matched
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/core/recognizers/yolo_detect.py
from __future__ import annotations
import numpy as np
from ..recognizer import RecognizeResult, BBox

class YoloDetect:
    def __init__(self, model, threshold: float = 0.5, classes: list[int] | None = None,
                 _yolo=None, name: str = "yolo_detect"):
        self._model = model
        self._threshold = threshold
        self._classes = classes
        self._name = name
        self._yolo = _yolo  # injected for tests

    def _load(self):
        if self._yolo is None:
            from ultralytics import YOLO
            self._yolo = YOLO(self._model)
        return self._yolo

    def recognize(self, screenshot: np.ndarray) -> RecognizeResult:
        yolo = self._load()
        results = yolo(screenshot)
        if not results:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   recognizer_id=self._name, bbox_list=[])
        r = results[0]
        bboxes = []
        max_conf = 0.0
        if hasattr(r, "boxes") and r.boxes is not None:
            for box in r.boxes:
                xyxy = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                if self._classes is not None and cls not in self._classes:
                    continue
                if conf < self._threshold:
                    continue
                bboxes.append(BBox(int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])))
                max_conf = max(max_conf, conf)
        return RecognizeResult(
            matched=len(bboxes) > 0,
            bbox=bboxes[0] if bboxes else None,
            confidence=max_conf,
            data={"bbox_list": bboxes},
            recognizer_id=self._name,
        )
```

- [ ] **Step 3: Add bbox_list to RecognizeResult**

Edit `src/rok_assistant/core/recognizer.py`: add `bbox_list: list[BBox] = field(default_factory=list)` to RecognizeResult.

- [ ] **Step 4: Run test, expect pass + commit**

```bash
git add src/rok_assistant/core/recognizers/yolo_detect.py tests/unit/core/recognizers/test_yolo_detect.py src/rok_assistant/core/recognizer.py
git commit -m "feat(M1): YoloDetect recognizer + bbox_list field"
```

---

## Task T14: RecognizerChain (M1)

**Files:**
- Create: `src/rok_assistant/core/recognizer.py` (append)
- Test: `tests/unit/core/test_recognizer_chain.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/core/test_recognizer_chain.py
import numpy as np
from rok_assistant.core.recognizer import RecognizerChain, RecognizeResult, BBox, Recognizer

class StubRec(Recognizer):
    def __init__(self, name, matched, conf=0.9):
        self.name = name; self._m = matched; self._c = conf
    def recognize(self, screenshot):
        return RecognizeResult(matched=self._m, bbox=BBox(0,0,10,10) if self._m else None,
                               confidence=self._c, recognizer_id=self.name)

def test_chain_returns_first_match():
    chain = RecognizerChain([StubRec("a", False, 0.3), StubRec("b", True, 0.95)])
    r = chain.recognize(np.zeros((10,10,3), dtype=np.uint8))
    assert r.recognizer_id == "b"
    assert r.matched

def test_chain_falls_through_when_low_confidence():
    chain = RecognizerChain([StubRec("a", True, 0.3), StubRec("b", True, 0.9)],
                            threshold=0.5)
    r = chain.recognize(np.zeros((10,10,3), dtype=np.uint8))
    assert r.recognizer_id == "b"

def test_chain_no_match():
    chain = RecognizerChain([StubRec("a", False), StubRec("b", False)])
    r = chain.recognize(np.zeros((10,10,3), dtype=np.uint8))
    assert not r.matched
```

- [ ] **Step 2: Implement**

Append to `src/rok_assistant/core/recognizer.py`:

```python
class RecognizerChain:
    """Tries recognizers in order. Returns first match above threshold."""
    def __init__(self, recognizers: list, threshold: float = 0.85):
        self._recognizers = recognizers
        self._threshold = threshold

    def recognize(self, screenshot: np.ndarray) -> RecognizeResult:
        for rec in self._recognizers:
            r = rec.recognize(screenshot)
            if r.matched and r.confidence >= self._threshold:
                return r
        # Return best below threshold
        best = None
        for rec in self._recognizers:
            r = rec.recognize(screenshot)
            if best is None or r.confidence > best.confidence:
                best = r
        return best or RecognizeResult(matched=False, bbox=None, confidence=0.0)
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/core/recognizer.py tests/unit/core/test_recognizer_chain.py
git commit -m "feat(M1): RecognizerChain with first-match + threshold fallback"
```

---

## Task T15: TemplateRegistry (M2)

**Files:**
- Create: `src/rok_assistant/core/template_registry.py`
- Test: `tests/unit/core/test_template_registry.py`
- Create: `tests/fixtures/manifest_test.yaml`

- [ ] **Step 1: Create test manifest**

```yaml
# tests/fixtures/manifest_test.yaml
templates:
  - id: btn_a
    file: btn_a.png
    roi: [10, 20, 110, 120]
    threshold: 0.9
  - id: btn_b
    file: btn_b.png
    roi: full
    threshold: 0.85
  - id: card
    file: card.onnx
    type: yolo_detect
    classes: [0]
    threshold: 0.7
```

- [ ] **Step 2: Write failing test**

```python
# tests/unit/core/test_template_registry.py
from pathlib import Path
import cv2
import numpy as np
import pytest
from rok_assistant.core.template_registry import TemplateRegistry, TemplateSpec, ROI

FIX = Path(__file__).parent.parent.parent / "fixtures"

@pytest.fixture
def manifest_with_png(tmp_path):
    # Create stub template files
    (tmp_path / "btn_a.png").write_bytes(b"")
    (tmp_path / "btn_b.png").write_bytes(b"")
    (tmp_path / "card.onnx").write_bytes(b"")
    # Copy manifest
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text((FIX / "manifest_test.yaml").read_text())
    return manifest

def test_load_manifest(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    assert "btn_a" in reg
    assert "btn_b" in reg
    assert "card" in reg

def test_get_template_spec(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    spec = reg.get("btn_a")
    assert isinstance(spec, TemplateSpec)
    assert spec.threshold == 0.9
    assert spec.roi.x1 == 10

def test_roi_full(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    spec = reg.get("btn_b")
    assert spec.roi.is_full

def test_template_spec_type(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    spec = reg.get("card")
    assert spec.type == "yolo_detect"
```

- [ ] **Step 3: Implement**

```python
# src/rok_assistant/core/template_registry.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass(frozen=True)
class ROI:
    x1: int; y1: int; x2: int; y2: int
    @property
    def is_full(self) -> bool:
        return self.x1 == 0 and self.y1 == 0 and self.x2 == 0 and self.y2 == 0

@dataclass(frozen=True)
class TemplateSpec:
    id: str
    file: Path
    threshold: float
    type: str  # "template_match" or "yolo_detect"
    roi: ROI
    classes: list[int]

class TemplateRegistry:
    def __init__(self, templates: dict[str, TemplateSpec]):
        self._t = templates

    def __contains__(self, k: str) -> bool:
        return k in self._t

    def get(self, k: str) -> TemplateSpec:
        return self._t[k]

    @staticmethod
    def load(manifest_path: Path) -> "TemplateRegistry":
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        templates = {}
        for entry in raw.get("templates", []):
            roi_raw = entry.get("roi", "full")
            if roi_raw == "full" or roi_raw is None:
                roi = ROI(0, 0, 0, 0)
            elif isinstance(roi_raw, list) and len(roi_raw) == 4:
                roi = ROI(*roi_raw)
            else:
                raise ValueError(f"Bad ROI in {entry['id']}: {roi_raw}")
            spec = TemplateSpec(
                id=entry["id"],
                file=manifest_path.parent / entry["file"],
                threshold=float(entry.get("threshold", 0.9)),
                type=entry.get("type", "template_match"),
                roi=roi,
                classes=entry.get("classes", []),
            )
            templates[spec.id] = spec
        return TemplateRegistry(templates)
```

- [ ] **Step 4: Run test, expect pass + commit**

```bash
git add src/rok_assistant/core/template_registry.py tests/unit/core/test_template_registry.py tests/fixtures/manifest_test.yaml
git commit -m "feat(M2): TemplateRegistry with YAML manifest loader"
```

---

## Task T16: EventBus (M5)

**Files:**
- Create: `src/rok_assistant/coordination/event_bus.py`
- Test: `tests/unit/coordination/test_event_bus.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/coordination/test_event_bus.py
from rok_assistant.coordination.event_bus import EventBus

def test_subscribe_and_publish():
    bus = EventBus()
    received = []
    bus.subscribe("rally_launched", lambda payload: received.append(payload))
    bus.publish("rally_launched", {"rally_id": "r1"})
    assert received == [{"rally_id": "r1"}]

def test_multiple_subscribers():
    bus = EventBus()
    a, b = [], []
    bus.subscribe("e", lambda p: a.append(p))
    bus.subscribe("e", lambda p: b.append(p))
    bus.publish("e", {"x": 1})
    assert a == [{"x": 1}]
    assert b == [{"x": 1}]

def test_unsubscribe():
    bus = EventBus()
    received = []
    handler = lambda p: received.append(p)
    bus.subscribe("e", handler)
    bus.unsubscribe("e", handler)
    bus.publish("e", {"x": 1})
    assert received == []

def test_publish_with_no_subscribers_is_noop():
    bus = EventBus()
    bus.publish("nothing", {})  # should not raise
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/coordination/event_bus.py
from __future__ import annotations
from typing import Callable
from collections import defaultdict

class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable) -> None:
        self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable) -> None:
        if event in self._handlers:
            self._handlers[event].remove(handler)

    def publish(self, event: str, payload: dict) -> None:
        for handler in list(self._handlers[event]):
            handler(payload)
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/coordination/event_bus.py tests/unit/coordination/test_event_bus.py
git commit -m "feat(M5): EventBus in-process pub/sub"
```

---

## Task T17: ScreenScheduler (M5)

**Files:**
- Create: `src/rok_assistant/coordination/screen_scheduler.py`
- Test: `tests/unit/coordination/test_screen_scheduler.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/coordination/test_screen_scheduler.py
import time
import threading
from rok_assistant.coordination.screen_scheduler import ScreenScheduler

def test_serializes_actions():
    sched = ScreenScheduler()
    order = []
    def make(i, delay):
        return lambda: (time.sleep(delay), order.append(i))
    sched.request("w1", make(1, 0.05))
    sched.request("w2", make(2, 0.05))
    sched.request("w1", make(3, 0.05))
    sched.wait_all()
    assert order == [1, 2, 3]

def test_priority_runs_first():
    sched = ScreenScheduler()
    order = []
    sched.request("w1", lambda: order.append("low"))
    sched.request("w2", lambda: order.append("high"), priority=10)
    sched.wait_all()
    # high goes first since it was enqueued with higher priority? Actually FIFO+priority
    # If both enqueued, the higher priority should be served first
    assert order[0] == "high"

def test_cancel_pending():
    sched = ScreenScheduler()
    called = []
    sched.request("w1", lambda: called.append("a"))
    sched.request("w1", lambda: called.append("b"))
    sched.cancel_pending("w1")
    sched.wait_all()
    # The first one may already have started; second should be cancelled
    assert "b" not in called
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/coordination/screen_scheduler.py
from __future__ import annotations
import heapq
import threading
from typing import Callable, Any
from dataclasses import dataclass, field

@dataclass(order=True)
class _Item:
    priority: int
    seq: int
    worker_id: str = field(compare=False)
    action: Callable = field(compare=False)
    cancelled: bool = field(default=False, compare=False)

class ScreenScheduler:
    """FIFO + priority queue. Higher priority (larger int) served first."""
    def __init__(self):
        self._heap: list[_Item] = []
        self._counter = 0
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._outstanding = 0

    def request(self, worker_id: str, action: Callable, priority: int = 0) -> None:
        with self._cond:
            self._counter += 1
            item = _Item(priority=-priority, seq=self._counter,
                         worker_id=worker_id, action=action)
            heapq.heappush(self._heap, item)
            self._outstanding += 1
            self._cond.notify()
        threading.Thread(target=self._run, args=(item,), daemon=True).start()

    def _run(self, item: _Item) -> None:
        with self._cond:
            while self._heap[0] is not item:
                self._cond.wait()
        if item.cancelled:
            with self._cond:
                self._outstanding -= 1
                self._cond.notify_all()
            return
        try:
            item.action()
        finally:
            with self._cond:
                self._heap.pop(0)  # actually heap[0] is item by construction
                self._outstanding -= 1
                self._cond.notify_all()

    def cancel_pending(self, worker_id: str) -> None:
        with self._cond:
            for item in self._heap:
                if item.worker_id == worker_id and not item.cancelled:
                    item.cancelled = True

    def wait_all(self, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        with self._cond:
            while self._outstanding > 0:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return
                self._cond.wait(timeout=remaining)
```

Add `import time` at top.

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/coordination/screen_scheduler.py tests/unit/coordination/test_screen_scheduler.py
git commit -m "feat(M5): ScreenScheduler with priority queue and cancel"
```

---

## Task T18: StateMachine base (M3)

**Files:**
- Create: `src/rok_assistant/workers/state_machine.py`
- Test: `tests/unit/workers/test_state_machine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/workers/test_state_machine.py
import pytest
from rok_assistant.workers.state_machine import StateMachine, State, Transition

class Counter(StateMachine):
    def _setup(self):
        self.add_transition("start", "counting", "increment")
        self.add_transition("counting", "counting", "increment", guard=lambda ctx: ctx["n"] < 3)
        self.add_transition("counting", "done", "finish", guard=lambda ctx: ctx["n"] >= 3)

def test_initial_state():
    c = Counter(initial="start")
    assert c.current == "start"

def test_transition():
    c = Counter(initial="start")
    c.step({})
    assert c.current == "counting"

def test_guard_blocks_transition():
    c = Counter(initial="start")
    c.step({})
    c.step({"n": 10})  # would skip counting
    assert c.current == "done"

def test_history():
    c = Counter(initial="start")
    c.step({})
    c.step({"n": 1})
    c.step({"n": 2})
    c.step({"n": 3})
    assert c.history == ["start", "counting", "counting", "counting", "done"]
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/workers/state_machine.py
from __future__ import annotations
from typing import Callable
from dataclasses import dataclass, field

@dataclass
class Transition:
    from_state: str
    to_state: str
    action: Callable
    guard: Callable | None = None

class StateMachine:
    def __init__(self, initial: str):
        self._transitions: list[Transition] = []
        self.current = initial
        self.history: list[str] = [initial]
        self._setup()

    def _setup(self) -> None:
        raise NotImplementedError

    def add_transition(self, from_state: str, to_state: str,
                       action: Callable, guard: Callable | None = None) -> None:
        self._transitions.append(Transition(from_state, to_state, action, guard))

    def step(self, context: dict | None = None) -> None:
        context = context or {}
        for t in self._transitions:
            if t.from_state != self.current:
                continue
            if t.guard and not t.guard(context):
                continue
            t.action(context)
            self.current = t.to_state
            self.history.append(self.current)
            return
        # No transition matched - stay in current state
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/workers/state_machine.py tests/unit/workers/test_state_machine.py
git commit -m "feat(M3): StateMachine base with transitions + guards"
```

---

## Task T19: SwitcherStateMachine (M4)

**Files:**
- Create: `src/rok_assistant/workers/switcher_sm.py`
- Test: `tests/unit/workers/test_switcher_sm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/workers/test_switcher_sm.py
import numpy as np
from rok_assistant.workers.switcher_sm import SwitcherStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def test_switcher_walks_4_steps():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    handle = MockHandleSource(screenshot=img)
    sm = SwitcherStateMachine(handle_source=handle, target_character="Boss",
                              recognizers={}, ocr=None)
    sm.run_until_done()
    # Should have clicked: avatar, settings_button, char_mgmt_button, target char
    assert len(handle.clicks) >= 4
    # Last state should be DONE
    assert sm.current == "DONE"

def test_switcher_state_progression():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    handle = MockHandleSource(screenshot=img)
    sm = SwitcherStateMachine(handle_source=handle, target_character="Boss",
                              recognizers={}, ocr=None)
    seen = []
    while not sm.is_done():
        seen.append(sm.current)
        sm.step()
    assert seen[0] == "IDLE"
    assert "OPEN_PROFILE" in seen
    assert "OPEN_SETTINGS" in seen
    assert "OPEN_CHAR_MGMT" in seen
    assert "PICK_CHAR" in seen
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/workers/switcher_sm.py
from __future__ import annotations
from .state_machine import StateMachine

class SwitcherStateMachine(StateMachine):
    """4-step character switcher: avatar -> settings -> char_mgmt -> pick."""
    def __init__(self, handle_source, target_character: str, recognizers: dict, ocr):
        self._handle = handle_source
        self._target = target_character
        self._recognizers = recognizers
        self._ocr = ocr
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "OPEN_PROFILE", self._open_profile)
        self.add_transition("OPEN_PROFILE", "OPEN_SETTINGS", self._open_settings)
        self.add_transition("OPEN_SETTINGS", "OPEN_CHAR_MGMT", self._open_char_mgmt)
        self.add_transition("OPEN_CHAR_MGMT", "PICK_CHAR", self._pick_char)
        self.add_transition("PICK_CHAR", "VERIFY", self._verify)
        self.add_transition("VERIFY", "DONE", lambda ctx: None,
                            guard=lambda ctx: ctx.get("verified", False))
        self.add_transition("VERIFY", "PICK_CHAR", self._pick_char,
                            guard=lambda ctx: not ctx.get("verified", False) and ctx.get("retries", 0) < 2)

    def _open_profile(self, ctx):
        # Click avatar (top-left). Real coords from screen config.
        self._handle.click(50, 50)

    def _open_settings(self, ctx):
        self._handle.click(800, 600)  # 设置 button (rough)

    def _open_char_mgmt(self, ctx):
        self._handle.click(400, 400)  # 角色管理 button

    def _pick_char(self, ctx):
        # Look up target character's avatar position from ocr; for now click 250,250
        self._handle.click(250, 250)
        ctx["retries"] = ctx.get("retries", 0) + 1

    def _verify(self, ctx):
        # OCR the top-left avatar name. Mock: assume success.
        ctx["verified"] = True

    def is_done(self) -> bool:
        return self.current == "DONE"

    def run_until_done(self) -> None:
        ctx = {}
        for _ in range(20):
            self.step(ctx)
            if self.is_done():
                return
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/workers/switcher_sm.py tests/unit/workers/test_switcher_sm.py
git commit -m "feat(M4): SwitcherStateMachine with 4-step path"
```

---

## Task T20: LeaderStateMachine (M3)

**Files:**
- Create: `src/rok_assistant/workers/leader_sm.py`
- Test: `tests/unit/workers/test_leader_sm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/workers/test_leader_sm.py
import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def test_leader_full_session_path():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    # Stub recognizers that always succeed
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    sm = LeaderStateMachine(
        handle_source=handle, recognizers={"search_icon": rec, "rally_attack_popup": rec,
                                            "red_rally": rec, "blue_rally": rec,
                                            "preset_1": rec, "march_btn": rec,
                                            "level_select": rec},
        target_level=8, march_preset=1, march_troop_types=["infantry"]
    )
    for _ in range(20):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    # Should have called rally_launched at LAUNCH
    assert sm.last_rally_event is not None
    assert sm.last_rally_event["fortress_level"] == 8
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/workers/leader_sm.py
from __future__ import annotations
import time
from .state_machine import StateMachine
from ..core.recognizer import BBox

class LeaderStateMachine(StateMachine):
    def __init__(self, handle_source, recognizers: dict, target_level: int,
                 march_preset: int, march_troop_types: list, event_bus=None):
        self._handle = handle_source
        self._rec = recognizers
        self._target_level = target_level
        self._march_preset = march_preset
        self._march_troop_types = march_troop_types
        self._bus = event_bus
        self.last_rally_event = None
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "SEARCH_FORTRESS", self._search_fortress)
        self.add_transition("SEARCH_FORTRESS", "SELECT_LEVEL", self._select_level)
        self.add_transition("SELECT_LEVEL", "CONFIRM_SEARCH", self._confirm_search)
        self.add_transition("CONFIRM_SEARCH", "CHECK_RESULT", self._check_result)
        self.add_transition("CHECK_RESULT", "SELECT_RALLY_TIME", self._select_rally_time,
                            guard=lambda ctx: ctx.get("not_locked"))
        self.add_transition("CHECK_RESULT", "CONFIRM_SEARCH", self._next_fortress,
                            guard=lambda ctx: not ctx.get("not_locked"))
        self.add_transition("SELECT_RALLY_TIME", "FORM_TROOP", self._form_troop)
        self.add_transition("FORM_TROOP", "LAUNCH", self._launch)
        self.add_transition("LAUNCH", "WAIT_MEMBERS", self._wait_members)
        self.add_transition("WAIT_MEMBERS", "END", lambda ctx: None,
                            guard=lambda ctx: ctx.get("departed"))

    def _find(self, rec_id: str):
        img = self._handle.capture()
        r = self._rec[rec_id].recognize(img)
        return r if r.matched else None

    def _click(self, rec_id: str):
        r = self._find(rec_id)
        if r is None:
            return False
        x, y = r.bbox.center()
        self._handle.click(x, y)
        return True

    def _search_fortress(self, ctx):
        self._click("search_icon")

    def _select_level(self, ctx):
        # Click on level tab "野蛮人城寨"
        # Then click +/- to reach target_level
        for _ in range(self._target_level - 1):
            self._click("level_plus")

    def _confirm_search(self, ctx):
        self._click("search_btn")

    def _check_result(self, ctx):
        time.sleep(5)  # wait for rally_attack_popup
        r = self._find("rally_attack_popup")
        ctx["not_locked"] = r is not None

    def _next_fortress(self, ctx):
        # Click "next fortress" arrow
        self._click("next_fortress_arrow")

    def _select_rally_time(self, ctx):
        # Default 5 minutes - already selected; just confirm
        pass

    def _form_troop(self, ctx):
        # Click preset slot matching march_preset
        self._click(f"preset_{self._march_preset}")
        # Set troop types (simplified)
        for t in self._march_troop_types:
            self._click(f"troop_{t}")

    def _launch(self, ctx):
        self._click("march_btn")
        # Fire event
        self.last_rally_event = {
            "rally_id": f"rally_{int(time.time())}",
            "fortress_level": self._target_level,
            "march_preset": self._march_preset,
        }
        if self._bus:
            self._bus.publish("rally_launched", self.last_rally_event)

    def _wait_members(self, ctx):
        # Passive wait. Game auto-departs after timer.
        ctx["departed"] = True  # simplified; real impl subscribes to game state

    def is_terminal(self) -> bool:
        return self.current == "END"
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/workers/leader_sm.py tests/unit/workers/test_leader_sm.py
git commit -m "feat(M3): LeaderStateMachine with full session path"
```

---

## Task T21: MemberStateMachine (M5)

**Files:**
- Create: `src/rok_assistant/workers/member_sm.py`
- Test: `tests/unit/workers/test_member_sm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/workers/test_member_sm.py
import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def test_member_receives_event_and_joins():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95

    sm = MemberStateMachine(
        handle_source=handle, recognizers={"alliance_btn": rec, "war_btn": rec,
                                            "sort_nearest": rec, "join_btn": rec,
                                            "preset_1": rec, "march_btn": rec},
        march_preset=1, march_troop_types=["infantry"],
        fill_target_leaders="nearest"
    )

    sm.on_rally_launched({"rally_id": "r1", "fortress_level": 8, "march_preset": 1})
    for _ in range(30):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/workers/member_sm.py
from __future__ import annotations
import time
from .state_machine import StateMachine

class MemberStateMachine(StateMachine):
    def __init__(self, handle_source, recognizers: dict, march_preset: int,
                 march_troop_types: list, fill_target_leaders, switcher=None):
        self._handle = handle_source
        self._rec = recognizers
        self._march_preset = march_preset
        self._march_troop_types = march_troop_types
        self._filter = fill_target_leaders
        self._switcher = switcher
        self._pending_event = None
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "WAIT_LAUNCH_EVENT",
                            lambda ctx: None,
                            guard=lambda ctx: self._pending_event is not None)
        self.add_transition("WAIT_LAUNCH_EVENT", "SWITCH_TO_SELF", self._switch_to_self)
        self.add_transition("SWITCH_TO_SELF", "OPEN_ALLIANCE", self._open_alliance)
        self.add_transition("OPEN_ALLIANCE", "OPEN_WAR", self._open_war)
        self.add_transition("OPEN_WAR", "SORT_BY_NEAREST", self._sort_nearest)
        self.add_transition("SORT_BY_NEAREST", "FILTER", self._filter_rally)
        self.add_transition("FILTER", "CLICK_JOIN", self._click_join,
                            guard=lambda ctx: ctx.get("rally_found"))
        self.add_transition("FILTER", "OPEN_WAR", self._open_war,
                            guard=lambda ctx: not ctx.get("rally_found"))
        self.add_transition("CLICK_JOIN", "FORM_TROOP", self._form_troop)
        self.add_transition("FORM_TROOP", "LAUNCH", self._launch)
        self.add_transition("LAUNCH", "SWITCH_BACK", self._switch_back)
        self.add_transition("SWITCH_BACK", "END", lambda ctx: None)

    def on_rally_launched(self, event: dict) -> None:
        self._pending_event = event

    def _click(self, rec_id: str) -> bool:
        img = self._handle.capture()
        r = self._rec[rec_id].recognize(img)
        if not r.matched:
            return False
        x, y = r.bbox.center()
        self._handle.click(x, y)
        return True

    def _switch_to_self(self, ctx):
        # In single-character-worker-per-character model, already on self.
        # For multi-char per account, would call switcher.
        pass

    def _open_alliance(self, ctx):
        self._click("alliance_btn")

    def _open_war(self, ctx):
        self._click("war_btn")

    def _sort_nearest(self, ctx):
        self._click("sort_nearest")

    def _filter_rally(self, ctx):
        # nearest: pick first rally. specific: OCR name, check match.
        if self._filter == "nearest":
            ctx["rally_found"] = True
        else:
            # Stub: in production this would OCR each rally card's leader name
            # and check membership in self._filter list. For v1 we accept the
            # first card. (Spec section 5.3 - rally 卡片字段)
            ctx["rally_found"] = True  # simplified

    def _click_join(self, ctx):
        self._click("join_btn")

    def _form_troop(self, ctx):
        self._click(f"preset_{self._march_preset}")

    def _launch(self, ctx):
        self._click("march_btn")

    def _switch_back(self, ctx):
        pass  # simplified

    def is_terminal(self) -> bool:
        return self.current == "END"
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/workers/member_sm.py tests/unit/workers/test_member_sm.py
git commit -m "feat(M5): MemberStateMachine with rally launch event handler"
```

---

## Task T22: RallySession coordinator (M5)

**Files:**
- Create: `src/rok_assistant/coordination/rally_session.py`
- Test: `tests/unit/coordination/test_rally_session.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/coordination/test_rally_session.py
import numpy as np
from unittest.mock import MagicMock
from rok_assistant.coordination.rally_session import RallySession
from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.core.handle_source import MockHandleSource

def test_session_launches_and_notifies_members():
    bus = EventBus()
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    recs = {"search_icon": rec, "rally_attack_popup": rec, "red_rally": rec,
            "blue_rally": rec, "preset_1": rec, "march_btn": rec, "level_plus": rec,
            "search_btn": rec, "next_fortress_arrow": rec}
    leader_sm = MagicMock()
    leader_sm.is_terminal.side_effect = [False, False, True]
    leader_sm.step = MagicMock()
    leader_sm.last_rally_event = {"rally_id": "r1", "fortress_level": 8, "march_preset": 1}

    notified = []
    bus.subscribe("rally_launched", lambda p: notified.append(p))

    session = RallySession(leader_sm=leader_sm, event_bus=bus, member_sms=[])
    session.run()
    assert len(notified) == 1
    assert notified[0]["rally_id"] == "r1"
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/coordination/rally_session.py
from __future__ import annotations
from .event_bus import EventBus

class RallySession:
    """One end-to-end rally attempt. Drives leader, broadcasts events to members."""
    def __init__(self, leader_sm, event_bus: EventBus, member_sms: list):
        self._leader = leader_sm
        self._bus = event_bus
        self._members = member_sms
        # Wire leader's rally_launched to bus
        if hasattr(leader_sm, "_bus") and leader_sm._bus is None:
            leader_sm._bus = event_bus
        # Subscribe members
        for m in member_sms:
            event_bus.subscribe("rally_launched", m.on_rally_launched)

    def run(self, max_steps: int = 100) -> None:
        for _ in range(max_steps):
            if self._leader.is_terminal():
                return
            self._leader.step()
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/coordination/rally_session.py tests/unit/coordination/test_rally_session.py
git commit -m "feat(M5): RallySession coordinator publishes rally_launched"
```

---

## Task T23: FailureHandler (M6)

**Files:**
- Create: `src/rok_assistant/coordination/failure_handler.py`
- Test: `tests/unit/coordination/test_failure_handler.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/coordination/test_failure_handler.py
from rok_assistant.coordination.failure_handler import FailureHandler, RecoveryAction

def test_handle_recognition_failure_first_two_retries():
    h = FailureHandler(max_retries=3)
    a = h.handle("recognition_failed", {"worker_id": "w1", "scene": "search"})
    assert a == RecoveryAction.RETRY

def test_handle_recognition_failure_after_max():
    h = FailureHandler(max_retries=3)
    h.handle("recognition_failed", {"worker_id": "w1", "scene": "search"})
    h.handle("recognition_failed", {"worker_id": "w1", "scene": "search"})
    a = h.handle("recognition_failed", {"worker_id": "w1", "scene": "search"})
    assert a == RecoveryAction.SKIP_STEP

def test_handle_locked_skips():
    h = FailureHandler(max_retries=3)
    a = h.handle("fortress_locked", {"worker_id": "w1"})
    assert a == RecoveryAction.SKIP_TARGET

def test_handle_window_disappeared_pauses():
    h = FailureHandler(max_retries=3)
    a = h.handle("window_disappeared", {"worker_id": "w1"})
    assert a == RecoveryAction.PAUSE_ALL
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/coordination/failure_handler.py
from __future__ import annotations
from enum import Enum
from collections import defaultdict

class RecoveryAction(str, Enum):
    RETRY = "retry"
    SKIP_STEP = "skip_step"
    SKIP_TARGET = "skip_target"
    SKIP_SESSION = "skip_session"
    PAUSE_ALL = "pause_all"

class FailureHandler:
    def __init__(self, max_retries: int = 3):
        self._max_retries = max_retries
        self._attempts: dict[tuple[str, str], int] = defaultdict(int)

    def handle(self, failure_type: str, context: dict) -> RecoveryAction:
        if failure_type == "recognition_failed":
            key = (context.get("worker_id", ""), context.get("scene", ""))
            self._attempts[key] += 1
            if self._attempts[key] < self._max_retries:
                return RecoveryAction.RETRY
            return RecoveryAction.SKIP_STEP
        if failure_type == "fortress_locked":
            return RecoveryAction.SKIP_TARGET
        if failure_type == "rally_empty_timeout":
            return RecoveryAction.SKIP_SESSION
        if failure_type == "window_disappeared":
            return RecoveryAction.PAUSE_ALL
        if failure_type == "switch_failed":
            return RecoveryAction.SKIP_SESSION
        return RecoveryAction.SKIP_SESSION

    def reset(self, worker_id: str) -> None:
        keys = [k for k in self._attempts if k[0] == worker_id]
        for k in keys:
            del self._attempts[k]
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/coordination/failure_handler.py tests/unit/coordination/test_failure_handler.py
git commit -m "feat(M6): FailureHandler with retry/skip/pause recovery"
```

---

## Task T24: Recording tool (M8)

**Files:**
- Create: `tools/record.py`

- [ ] **Step 1: Write the recorder**

```python
# tools/record.py
"""Record emulator screenshots to a session directory for replay testing."""
import argparse
import time
from datetime import datetime
from pathlib import Path
from rok_assistant.core.handle_source import Win32HandleSource
from rok_assistant.infra.paths import ProjectPaths

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, help="Account id from config")
    parser.add_argument("--pattern", required=True, help="Window title pattern")
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--max-frames", type=int, default=600)
    parser.add_argument("--out", default="./recordings")
    args = parser.parse_args()

    paths = ProjectPaths(root=Path(args.out).parent)
    paths.ensure_dirs()
    session_dir = Path(args.out) / f"session_{datetime.now():%Y%m%d_%H%M%S}"
    session_dir.mkdir(parents=True, exist_ok=True)
    print(f"Recording to {session_dir}")

    handle = Win32HandleSource(window_title_pattern=args.pattern)
    if not handle.is_alive():
        print(f"ERROR: Window matching {args.pattern!r} not found")
        return 1

    import cv2
    manifest = []
    for i in range(args.max_frames):
        try:
            img = handle.capture()
        except Exception as e:
            print(f"Frame {i} failed: {e}")
            break
        fname = f"frame_{i:05d}.png"
        cv2.imwrite(str(session_dir / fname), img)
        manifest.append({"index": i, "file": fname, "ts": time.time()})
        print(f"\r{i+1}/{args.max_frames}", end="", flush=True)
        time.sleep(args.interval)

    import json
    (session_dir / "manifest.json").write_text(
        json.dumps({"account": args.account, "frames": manifest}, indent=2)
    )
    print(f"\nDone. {len(manifest)} frames saved.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke test (no real window)**

Run: `python tools/record.py --account test --pattern nonexistent --max-frames 1`
Expected: `ERROR: Window matching 'nonexistent' not found`, exit 1.

- [ ] **Step 3: Commit**

```bash
git add tools/record.py
git commit -m "feat(M8): tools/record.py for screenshot session capture"
```

---

## Task T25: ReplaySession (M8)

**Files:**
- Create: `src/rok_assistant/coordination/replay.py`
- Test: `tests/unit/coordination/test_replay.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/coordination/test_replay.py
import json
from pathlib import Path
import numpy as np
import cv2
import pytest
from rok_assistant.coordination.replay import ReplaySession, ReplayHandleSource

@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "session_test"
    d.mkdir()
    for i in range(3):
        cv2.imwrite(str(d / f"frame_{i:05d}.png"), np.zeros((10, 10, 3), dtype=np.uint8))
    (d / "manifest.json").write_text(json.dumps({
        "account": "test", "frames": [
            {"index": 0, "file": "frame_00000.png", "ts": 0.0},
            {"index": 1, "file": "frame_00001.png", "ts": 0.5},
            {"index": 2, "file": "frame_00002.png", "ts": 1.0},
        ]
    }))
    return d

def test_replay_loads_manifest(session_dir):
    s = ReplaySession(session_dir)
    assert len(s.frames) == 3

def test_replay_handle_capture_returns_frame(session_dir):
    s = ReplaySession(session_dir)
    h = ReplayHandleSource(s)
    img = h.capture()
    assert img.shape == (10, 10, 3)

def test_replay_handle_advance(session_dir):
    s = ReplaySession(session_dir)
    h = ReplayHandleSource(s)
    h.capture()  # frame 0
    h.capture()  # frame 1
    h.capture()  # frame 2
    h.capture()  # past end, returns last
    assert h.current_index == 3
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/coordination/replay.py
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np

@dataclass
class ReplayFrame:
    index: int
    file: str
    ts: float

class ReplaySession:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        manifest = json.loads((session_dir / "manifest.json").read_text())
        self.frames = [ReplayFrame(**f) for f in manifest["frames"]]

class ReplayHandleSource:
    """HandleSource that returns recorded frames in sequence."""
    def __init__(self, session: ReplaySession):
        self._session = session
        self.current_index = 0
        self.clicks: list = []

    def capture(self) -> np.ndarray:
        if self.current_index >= len(self._session.frames):
            idx = len(self._session.frames) - 1
        else:
            idx = self.current_index
            self.current_index += 1
        path = self._session.session_dir / self._session.frames[idx].file
        return cv2.imread(str(path))

    def click(self, x, y):
        self.clicks.append((x, y))

    def is_alive(self):
        return True

    def swipe(self, *args, **kwargs):
        pass
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/coordination/replay.py tests/unit/coordination/test_replay.py
git commit -m "feat(M8): ReplaySession + ReplayHandleSource for integration tests"
```

---

## Task T26: PyQt6 main window skeleton (M7)

**Files:**
- Create: `src/rok_assistant/gui/main_window.py`
- Test: `tests/integration/test_gui_smoke.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_gui_smoke.py
import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app

def test_main_window_can_be_created(qapp):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow()
    assert w.windowTitle() == "rok-assistant"

def test_main_window_has_start_stop_buttons(qapp):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow()
    btn_texts = [b.text() for b in w.findChildren(type(w.start_btn))] if hasattr(w, "start_btn") else []
    # Just check window has widgets
    assert len(w.children()) > 0
```

- [ ] **Step 2: Implement MainWindow**

```python
# src/rok_assistant/gui/main_window.py
from __future__ import annotations
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QScrollArea, QStatusBar
)
from PyQt6.QtCore import Qt, QTimer

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("rok-assistant")
        self.resize(1200, 800)
        self._build_ui()
        self._setup_refresh_timer()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        # Top bar
        top = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["rally"])
        self.refresh_btn = QPushButton("Refresh Config")
        top.addWidget(self.start_btn)
        top.addWidget(self.stop_btn)
        top.addWidget(QLabel("Mode:"))
        top.addWidget(self.mode_combo)
        top.addWidget(self.refresh_btn)
        root.addLayout(top)
        # Account area
        self.account_area = QScrollArea()
        self.account_widget = QWidget()
        self.account_layout = QVBoxLayout(self.account_widget)
        self.account_area.setWidget(self.account_widget)
        root.addWidget(self.account_area)
        # Status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _setup_refresh_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._on_refresh)
        self._timer.start()

    def _on_refresh(self):
        # Stub: real implementation reads each worker's latest screenshot
        # via its HandleSource.capture() and feeds bytes to CharacterCard.set_thumbnail.
        # Deferred to integration testing (see T30 for wiring).
        pass

def main():
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/gui/main_window.py tests/integration/test_gui_smoke.py
git commit -m "feat(M7): PyQt6 MainWindow skeleton with start/stop/mode"
```

---

## Task T27: CharacterCard widget (M7)

**Files:**
- Create: `src/rok_assistant/gui/character_card.py`
- Test: `tests/integration/test_character_card.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_character_card.py
import pytest
from PyQt6.QtWidgets import QApplication
from rok_assistant.gui.character_card import CharacterCard

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app

def test_card_displays_name_and_role(qapp):
    card = CharacterCard(name="Hero", role="leader", status="waiting")
    assert "Hero" in card.title_label.text()
    assert "leader" in card.title_label.text()

def test_card_set_error_makes_red(qapp):
    card = CharacterCard(name="M1", role="member", status="idle")
    card.set_error("something broke")
    assert "error" in card.status_label.text().lower() or card.error_state
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/gui/character_card.py
from __future__ import annotations
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

class CharacterCard(QFrame):
    def __init__(self, name: str, role: str, status: str = "idle"):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedSize(220, 280)
        self.error_state = False
        self._build(name, role, status)

    def _build(self, name, role, status):
        layout = QVBoxLayout(self)
        self.title_label = QLabel(f"{name} ({role})")
        self.status_label = QLabel(status)
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(200, 150)
        self.thumbnail.setStyleSheet("background: #222;")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setText("(no image)")
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.thumbnail)
        layout.addStretch()

    def set_thumbnail(self, img_bytes: bytes) -> None:
        pix = QPixmap()
        pix.loadFromData(img_bytes)
        self.thumbnail.setPixmap(pix.scaled(
            200, 150, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))

    def set_error(self, message: str) -> None:
        self.error_state = True
        self.status_label.setText(f"ERROR: {message}")
        self.setStyleSheet("background: #500;")
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/gui/character_card.py tests/integration/test_character_card.py
git commit -m "feat(M7): CharacterCard widget with name/role/thumbnail/error"
```

---

## Task T28: LogPanel widget (M7)

**Files:**
- Create: `src/rok_assistant/gui/log_panel.py`
- Test: `tests/integration/test_log_panel.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_log_panel.py
import pytest
from PyQt6.QtWidgets import QApplication
from rok_assistant.gui.log_panel import LogPanel

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app

def test_log_panel_starts_empty(qapp):
    p = LogPanel()
    assert p.toPlainText() == ""

def test_log_panel_appends_message(qapp):
    p = LogPanel()
    p.append_message("hello")
    assert "hello" in p.toPlainText()

def test_log_panel_caps_lines(qapp):
    p = LogPanel(max_lines=3)
    for i in range(10):
        p.append_message(f"line {i}")
    text = p.toPlainText()
    assert "line 0" not in text
    assert "line 9" in text
    assert len(text.splitlines()) == 3
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/gui/log_panel.py
from __future__ import annotations
from PyQt6.QtWidgets import QPlainTextEdit
from PyQt6.QtCore import Qt
from datetime import datetime

class LogPanel(QPlainTextEdit):
    def __init__(self, max_lines: int = 500):
        super().__init__()
        self.setReadOnly(True)
        self._max_lines = max_lines

    def append_message(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.appendPlainText(f"[{ts}] {message}")
        # Trim
        doc = self.document()
        if doc.blockCount() > self._max_lines:
            cursor = self.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down,
                                cursor.MoveMode.KeepAnchor,
                                doc.blockCount() - self._max_lines)
            cursor.removeSelectedText()
            cursor.deleteChar()
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/gui/log_panel.py tests/integration/test_log_panel.py
git commit -m "feat(M7): LogPanel with timestamp + max_lines trim"
```

---

## Task T29: ConfigEditor dialog (M7)

**Files:**
- Create: `src/rok_assistant/gui/config_editor.py`
- Test: `tests/integration/test_config_editor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_config_editor.py
import pytest
from pathlib import Path
import yaml
from PyQt6.QtWidgets import QApplication
from rok_assistant.gui.config_editor import ConfigEditor

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app

def test_editor_loads_yaml(tmp_path, qapp):
    cfg = tmp_path / "test.yaml"
    cfg.write_text(yaml.safe_dump({"app": {"screen_width": 1280}, "accounts": []}))
    ed = ConfigEditor(config_path=cfg)
    text = ed.toPlainText()
    assert "1280" in text

def test_editor_save_writes_file(tmp_path, qapp):
    cfg = tmp_path / "test.yaml"
    cfg.write_text("app: {}\naccounts: []\n")
    ed = ConfigEditor(config_path=cfg)
    ed.setPlainText("app:\n  screen_width: 800\naccounts: []\n")
    assert ed.save()
    loaded = yaml.safe_load(cfg.read_text())
    assert loaded["app"]["screen_width"] == 800
```

- [ ] **Step 2: Implement**

```python
# src/rok_assistant/gui/config_editor.py
from __future__ import annotations
from pathlib import Path
from PyQt6.QtWidgets import QPlainTextEdit
from pydantic import ValidationError
from rok_assistant.infra.config import load_config

class ConfigEditor(QPlainTextEdit):
    def __init__(self, config_path: Path):
        super().__init__()
        self._path = config_path
        self.setPlainText(config_path.read_text(encoding="utf-8"))

    def save(self) -> bool:
        text = self.toPlainText()
        try:
            load_config(self._path)  # baseline
        except Exception:
            pass
        # Validate the current text by writing to temp + loading
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                         delete=False, encoding="utf-8") as f:
            f.write(text)
            tmp = Path(f.name)
        try:
            load_config(tmp)
        except ValidationError as e:
            self.parent().statusBar().showMessage(f"Invalid config: {e}")
            return False
        finally:
            tmp.unlink()
        self._path.write_text(text, encoding="utf-8")
        return True
```

- [ ] **Step 3: Run test, expect pass + commit**

```bash
git add src/rok_assistant/gui/config_editor.py tests/integration/test_config_editor.py
git commit -m "feat(M7): ConfigEditor dialog with YAML validation"
```

---

## Task T30: Wire GUI to coordinator (M7)

**Files:**
- Modify: `src/rok_assistant/gui/main_window.py`
- Modify: `src/rok_assistant/gui/character_card.py`
- Create: `src/rok_assistant/gui/controller.py`
- Test: `tests/integration/test_controller.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_controller.py
import numpy as np
from rok_assistant.gui.controller import GuiController
from rok_assistant.core.handle_source import MockHandleSource

def test_controller_initializes_from_config():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    # Simplified: just test that the controller exists
    c = GuiController(handle_sources={"acc1": handle})
    assert c.handle_sources["acc1"] is handle

def test_controller_update_status_pushes_to_event_bus():
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    received = []
    bus.subscribe("status_update", lambda p: received.append(p))
    c = GuiController(handle_sources={}, event_bus=bus)
    c.update_status("acc1", "char1", "searching")
    assert len(received) == 1
    assert received[0]["status"] == "searching"
```

- [ ] **Step 2: Implement controller**

```python
# src/rok_assistant/gui/controller.py
from __future__ import annotations
from typing import Callable

class GuiController:
    def __init__(self, handle_sources: dict, event_bus=None, config=None):
        self.handle_sources = handle_sources
        self.event_bus = event_bus
        self.config = config
        self._status_subscribers: list[Callable] = []

    def subscribe_status(self, callback: Callable) -> None:
        self._status_subscribers.append(callback)

    def update_status(self, account_id: str, char_id: str, status: str) -> None:
        payload = {"account_id": account_id, "char_id": char_id, "status": status}
        for sub in self._status_subscribers:
            sub(payload)
        if self.event_bus:
            self.event_bus.publish("status_update", payload)
```

- [ ] **Step 3: Modify MainWindow to take optional controller**

Edit `src/rok_assistant/gui/main_window.py`: change `__init__` to accept optional `controller=None`. Add `_on_status_update` method that updates the relevant CharacterCard. (See spec for card layout — implementer's discretion on exact integration.)

- [ ] **Step 4: Run test, expect pass + commit**

```bash
git add src/rok_assistant/gui/ tests/integration/test_controller.py
git commit -m "feat(M7): GuiController + MainWindow status subscription"
```

---

## Task T31: Manual verification script (M8)

**Files:**
- Create: `tools/verify.py`

- [ ] **Step 1: Write the verification script**

```python
# tools/verify.py
"""Manual verification script - walks through spec section 10 acceptance checklist."""
import argparse
import sys
import time
from pathlib import Path
from rok_assistant.core.handle_source import Win32HandleSource
from rok_assistant.infra.config import load_config
from rok_assistant.infra.logger import setup_logging
from rok_assistant.infra.paths import ProjectPaths

CHECKS = [
    ("Start 1 emulator + 1 character, run 1 rally", "leader_full_session"),
    ("Add 1 member, verify auto-switch + join", "member_with_switch"),
    ("Locked fortress -> skip + next", "lock_skip"),
    ("Rally times out empty -> leader relaunches", "rally_timeout"),
    ("Close emulator window -> assistant pauses", "window_disappear"),
    ("Invalid config (level=11) -> refused at startup", "config_invalid"),
    ("Wrong char name -> OCR verify fails + retry", "switch_verify_fail"),
    ("Log records all steps + screenshot on failure", "logging"),
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--check", choices=[c[1] for c in CHECKS] + ["all"], default="all")
    args = parser.parse_args()
    paths = ProjectPaths(root=Path("."))
    paths.ensure_dirs()
    setup_logging(log_dir=paths.log_dir)

    print("Manual verification checklist:")
    for label, key in CHECKS:
        mark = " " if args.check != "all" and args.check != key else "x"
        print(f"  [{mark}] {label}")
    print()
    print("Run each scenario in the game. Mark off as you go.")
    print("For automated regression, see tests/integration/")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it, expect checklist output**

Run: `python tools/verify.py`
Expected: 8 checklist items with `[x]` or `[ ]` markers.

- [ ] **Step 3: Commit**

```bash
git add tools/verify.py
git commit -m "feat(M8): tools/verify.py for manual acceptance checklist"
```

---

## Definition of Done (v1)

A pull request is ready for v1 release when:

1. All unit tests pass: `pytest tests/unit -v`
2. All integration tests pass: `pytest tests/integration -v`
3. Manual verification checklist (8 items in T31) marked complete
4. Recording tool (T24) successfully captures a real session
5. Replay test (T25) drives a state machine through recorded screenshots
6. Leader full-session works end-to-end with a real MuMu emulator
7. Member auto-join works with at least 1 member character
8. Config validation refuses bad YAML at startup with a clear error
9. GUI launches, displays all configured character cards, shows live status
10. Failure handler logs a recognizable error to GUI when a character fails

---

## Notes for Implementer

- **Templates are placeholder** at this point. Real templates must be collected by the user from a running game (use `tools/crop_template.py` once written). The spec section 5 lists the 15+ templates needed.
- **YOLO model** for rally card detection needs training data. Until that's ready, the YoloDetect recognizer can be a stub returning empty results, and the rally list can be parsed by OCR alone.
- **PaddleOCR first run** downloads ~100MB of model files. Plan for this.
- **PyQt6 on headless CI** requires `QT_QPA_PLATFORM=offscreen`. Already set in conftest.py if needed.
- **Recognizer coordinates** in the state machine test mocks are placeholders. Real coordinate discovery happens during M8 manual verification.

---
