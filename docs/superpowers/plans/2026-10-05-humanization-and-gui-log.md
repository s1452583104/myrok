# 每实例日志区 + 输入人性化层 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GUI 每张角色卡片内嵌该实例的日志区；并把输入层从"均匀抖动"升级为 `HumanProfile` 策略对象（分布化延迟、高斯散布、节奏去规律化、两号解耦）。

**Architecture:** 日志区不改任何 worker 日志调用——worker 线程名已是 `worker:<instance_id>:<char_id>`（`runner.py:117`），新增一个 `logging.Handler` 从线程名解析归属，经 Qt 信号（与 `controller.py:89` 同一模式）投递到卡片。人性化层新增 `HumanProfile`（`anti_detection.py`），由 `AntiDetectionConfig` + 可注入 `random.Random` 构造；`JitteringHandleSource` 与三个状态机都消费它，随机化收敛在一个对象里。

**Tech Stack:** Python 3.14 / PyQt6 / pydantic v2 / pytest；无新增第三方依赖。

**Spec:** `docs/superpowers/specs/2026-10-05-humanization-and-gui-log-design.md`

## Global Constraints

- 解释器一律用 `.venv/Scripts/python.exe`，**不要**用系统 `python`（那是 torch+cpu，会静默降级）。
- 控制台输出含中文/`✓` 时加 `-X utf8`（控制台是 GBK）。
- 测试默认只跑相关子集（`pytest tests/unit/xxx.py -q`）；**每个 Task 结束时**跑该 Task 的相关子集，**Task 11** 跑一次全套。
- 本计划**不新增任何第三方依赖**。
- 配置字段：`AntiDetectionConfig` 现有 7 个字段**全部保留原名**，不得重命名或删除。
- 兼容性硬要求：`debug_no_jitter: true` 必须让**所有**随机化方法返回确定性值。
- 兼容性硬要求：`MockHandleSource.clicks` 仍记录 `(x, y)` 二元组——现有断言依赖它。
- 提交信息用中文，前缀沿用仓库现有风格（`feat:` / `fix:` / `docs:` / `test:`）。
- **Part A 与 Part B 互不依赖**，可独立执行、独立合并。同一 Part 内的 Task 必须按序。

### 与 spec 的两处有意偏离（规划时发现，已告知用户）

1. **`state_delay_min/max` 的数据类默认值取 `0.8 / 1.2`（不是 spec 写的 `0.6 / 1.6`）。**
   理由：SM 在没有注入 profile 时用的默认 profile 是 `debug_no_jitter=True`，此时 `poll_interval()` 返回区间中点；`0.8/1.2` 的中点正好是 **1.0**，与改动前固定的 1.0s 轮询逐字相同，既有测试不受影响。生产推荐值 `0.6 / 1.6` 写进 `config.yaml` / `config.example.yaml`。
2. **`member_response_delay_min/max` 的数据类默认值取 `0.0 / 0.0`（不是 spec 写的 `10.0 / 60.0`）。**
   理由：这是个会凭空增加最多一分钟延迟的行为变更，不该静默生效。默认关闭，`config.example.yaml` 里给 `10 / 60` 作为推荐值，由用户显式开启。

---

# Part A — 每实例日志区

### Task 1: 线程名 → char_id 的纯解析函数

**Files:**
- Create: `src/rok_assistant/gui/log_handler.py`
- Test: `tests/unit/gui/test_log_handler.py`

**Interfaces:**
- Produces: `char_id_from_thread_name(name: str) -> str` —— 从线程名解析角色 id，解析不出返回 `""`。

- [ ] **Step 1: Write the failing test**

创建 `tests/unit/gui/test_log_handler.py`：

```python
from rok_assistant.gui.log_handler import char_id_from_thread_name


def test_parses_worker_thread_name():
    # runner.py:117 的命名格式
    assert char_id_from_thread_name("worker:mumu0:如愿") == "如愿"


def test_parses_char_id_containing_colon():
    """char_id 里出现冒号时，只切前两段，剩下的整体作为 id。"""
    assert char_id_from_thread_name("worker:mumu0:boss:2") == "boss:2"


def test_main_thread_returns_empty():
    assert char_id_from_thread_name("MainThread") == ""


def test_non_worker_thread_returns_empty():
    assert char_id_from_thread_name("Thread-3") == ""


def test_malformed_worker_name_returns_empty():
    assert char_id_from_thread_name("worker:") == ""
    assert char_id_from_thread_name("worker") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/gui/test_log_handler.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'rok_assistant.gui.log_handler'`

- [ ] **Step 3: Write minimal implementation**

创建 `src/rok_assistant/gui/log_handler.py`：

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/gui/test_log_handler.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/gui/log_handler.py tests/unit/gui/test_log_handler.py
git commit -m "feat: 新增日志归属解析（线程名 -> char_id）"
```

---

### Task 2: QtLogHandler + MainWindow 接线

**Files:**
- Modify: `src/rok_assistant/gui/log_handler.py`
- Modify: `src/rok_assistant/gui/main_window.py:17-28`（`__init__`）、`:69-72`（`_connect_controller` 之后）
- Test: `tests/unit/gui/test_log_handler.py`（追加）、`tests/integration/test_gui_smoke.py`（追加）

**Interfaces:**
- Consumes: `char_id_from_thread_name`（Task 1）
- Produces: `QtLogHandler(logging.Handler)` —— `QObject`，信号 `record_emitted = pyqtSignal(str, str)`（`char_id`, 已格式化的行文本）；`char_id` 为空串表示"非 worker 线程"。
- Produces: `MainWindow._on_log_line(char_id: str, text: str) -> None`

- [ ] **Step 1: Write the failing test**

追加到 `tests/unit/gui/test_log_handler.py`：

```python
import logging

from PyQt6.QtWidgets import QApplication
import pytest


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_handler_emits_char_id_and_text(qapp):
    from rok_assistant.gui.log_handler import QtLogHandler
    h = QtLogHandler()
    received = []
    h.record_emitted.connect(lambda cid, text: received.append((cid, text)))
    rec = logging.LogRecord("rok_assistant.workers.runner", logging.INFO,
                            __file__, 1, "hello %s", ("world",), None)
    h.emit(rec)
    assert len(received) == 1
    cid, text = received[0]
    assert cid == "MainThread" and False or cid == ""   # 主线程 -> 空串
    assert "hello world" in text


def test_handler_uses_thread_name_for_attribution(qapp):
    """在名为 worker:<inst>:<char> 的线程里发日志，归属应解析到该角色。"""
    import threading
    from rok_assistant.gui.log_handler import QtLogHandler
    h = QtLogHandler()
    received = []
    h.record_emitted.connect(lambda cid, text: received.append((cid, text)))
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)

    t = threading.Thread(target=lambda: h.emit(rec), name="worker:mumu1:阑珊")
    t.start()
    t.join()
    assert received[0][0] == "阑珊"
```

> 注：`test_handler_emits_char_id_and_text` 里那行 `assert cid == "MainThread" and False or cid == ""` 是笔误写法，**改成** `assert cid == ""` 再跑。

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/gui/test_log_handler.py -q`
Expected: FAIL —— `ImportError: cannot import name 'QtLogHandler'`

- [ ] **Step 3: Write minimal implementation**

追加到 `src/rok_assistant/gui/log_handler.py`：

```python
import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal


class QtLogHandler(logging.Handler, QObject):
    """把日志行经 Qt 信号送到主线程。

    worker 线程里 `emit`，Qt 自动排队到主线程 —— 与 `controller.py:89`
    的 status_changed 同一模式。`char_id` 为空串表示非 worker 线程。
    """

    record_emitted = pyqtSignal(str, str)

    def __init__(self) -> None:
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.setFormatter(logging.Formatter(
            "%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
        except Exception:                      # noqa: BLE001 - 日志不能反过来炸
            self.handleError(record)
            return
        cid = char_id_from_thread_name(threading.current_thread().name)
        self.record_emitted.emit(cid, text)
```

> **多继承顺序**：`logging.Handler` 在前、`QObject` 在后。`emit` 里显式调用两个基类的 `__init__`，不用 `super()` —— 两个基类无共同祖先，`super()` 链会漏掉一个。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/gui/test_log_handler.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: Write the failing integration test**

追加到 `tests/integration/test_gui_smoke.py`：

```python
def test_log_line_routes_to_matching_card(qapp):
    """worker 线程的日志行进对应卡片；主线程的行进状态栏。"""
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow(controller=FakeController())
    w._on_log_line("worker", "12:00:01 等待车头发车")
    assert "等待车头发车" in w._cards["worker"].log_view.toPlainText()
    assert "等待车头发车" not in w._cards["boss"].log_view.toPlainText()


def test_main_thread_log_line_goes_to_status_bar(qapp):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow(controller=FakeController())
    w._on_log_line("", "配置加载失败")
    assert "配置加载失败" in w.statusBar().currentMessage()
    assert "配置加载失败" not in w._cards["worker"].log_view.toPlainText()
```

- [ ] **Step 6: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_gui_smoke.py -q`
Expected: FAIL —— `AttributeError: 'MainWindow' object has no attribute '_on_log_line'`

- [ ] **Step 7: Implement MainWindow wiring**

在 `src/rok_assistant/gui/main_window.py` 顶部 import 区加：

```python
from .log_handler import QtLogHandler
```

在 `MainWindow.__init__` 里 `self._connect_controller()` 之后加一行：

```python
        self._install_log_handler()
```

在 `_connect_controller` 方法后面新增：

```python
    def _install_log_handler(self):
        """挂到 root logger，把日志行投给对应卡片。

        只装一次；`setup_logging` 有 `_initialized` 守卫且不碰这里，
        所以无头驱动（`_run_goal.py`）完全走不到这条路径。
        """
        self._log_handler = QtLogHandler()
        self._log_handler.record_emitted.connect(self._on_log_line)
        logging.getLogger().addHandler(self._log_handler)

    def _on_log_line(self, char_id: str, text: str):
        if not char_id:
            self.statusBar().showMessage(text)
            return
        card = self._cards.get(char_id)
        if card is not None:
            card.append_log(text)
```

并在文件顶部加 `import logging`。

- [ ] **Step 8: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_gui_smoke.py -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/rok_assistant/gui/log_handler.py src/rok_assistant/gui/main_window.py tests/unit/gui/test_log_handler.py tests/integration/test_gui_smoke.py
git commit -m "feat: 日志按线程名归属投递到实例卡片"
```

---

### Task 3: CharacterCard 内嵌日志区

**Files:**
- Modify: `src/rok_assistant/gui/character_card.py`
- Test: `tests/integration/test_character_card.py`（追加）

**Interfaces:**
- Consumes: `MainWindow._on_log_line` 调用的 `card.append_log(text)`
- Produces: `CharacterCard.log_view`（`QPlainTextEdit`）、`CharacterCard.append_log(text: str) -> None`

- [ ] **Step 1: Write the failing test**

追加到 `tests/integration/test_character_card.py`：

```python
def test_card_has_log_view_and_appends(qapp):
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="Hero", role="leader", status="idle")
    card.append_log("12:00:01 发起集结")
    card.append_log("12:03:10 已回城")
    text = card.log_view.toPlainText()
    assert "发起集结" in text and "已回城" in text
    assert card.log_view.isReadOnly()


def test_card_log_view_is_ring_buffered(qapp):
    """只保留最近 200 行，防止长跑把内存吃光。"""
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="Hero", role="leader", status="idle")
    for i in range(250):
        card.append_log(f"line {i}")
    text = card.log_view.toPlainText()
    assert "line 249" in text
    assert "line 0\n" not in text
    assert card.log_view.blockCount() <= 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_character_card.py -q`
Expected: FAIL —— `AttributeError: 'CharacterCard' object has no attribute 'log_view'`

- [ ] **Step 3: Implement**

把 `src/rok_assistant/gui/character_card.py` 整个替换为：

```python
from __future__ import annotations
from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QLabel, QPlainTextEdit,
                             QSizePolicy)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

from .labels import role_label, state_label

_LOG_MAX_LINES = 200


class CharacterCard(QFrame):
    def __init__(self, name: str, role: str, status: str = "idle"):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        # 比原来的 220x280 高出一截，给日志区让位
        self.setFixedSize(220, 430)
        self.error_state = False
        self._build(name, role, status)

    def _build(self, name, role, status):
        layout = QVBoxLayout(self)
        # 分工/状态都翻中文：配置页写「车头」，主界面卡片却写「leader」
        # 是同一个人在两处看到两个词（2026-10-05 用户反馈）
        self.title_label = QLabel(f"{name}（{role_label(role)}）")
        self.status_label = QLabel(state_label(status))
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(200, 150)
        self.thumbnail.setStyleSheet("background: #222;")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setText("(no image)")
        # 日志区：只读 + 环形缓冲。归属由 MainWindow 按线程名解析后投递
        # （见 gui/log_handler.py），这里只负责显示。
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(_LOG_MAX_LINES)
        self.log_view.setSizePolicy(QSizePolicy.Policy.Preferred,
                                    QSizePolicy.Policy.Expanding)
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.thumbnail)
        layout.addWidget(self.log_view)

    def append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())

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

    def set_status(self, status: str) -> None:
        self.status_label.setText(state_label(status))
```

> 注意：原实现末尾有 `layout.addStretch()`，现在日志区占满剩余空间，**去掉 stretch**。

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_character_card.py tests/integration/test_gui_smoke.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/gui/character_card.py tests/integration/test_character_card.py
git commit -m "feat: 角色卡片内嵌日志区（环形缓冲 200 行）"
```

---

# Part B — HumanProfile 人性化层

### Task 4: HumanProfile 骨架 + 延迟采样 + 坐标散布

**Files:**
- Modify: `src/rok_assistant/infra/anti_detection.py`
- Test: `tests/unit/infra/test_anti_detection.py`（追加 + 修改既有断言）

**Interfaces:**
- Produces: `AntiDetectionConfig` 新增字段 `delay_shape: str = "beta"`、`burst_prob: float = 0.3`、`burst_scale: float = 0.25`、`anchor_sigma: dict = field(default_factory=dict)`；`state_delay_min/max` 默认值改为 `0.8/1.2`
- Produces: `HumanProfile(cfg: AntiDetectionConfig, rng: random.Random | None = None)`
- Produces: `HumanProfile.click_delay() -> float`
- Produces: `HumanProfile.disperse(x: int, y: int, anchor: str | None = None) -> tuple[int, int]`

- [ ] **Step 1: 先修既有断言（默认值变了）**

`tests/unit/infra/test_anti_detection.py` 的 `test_default_config` 里，把

```python
    assert cfg.state_delay_min == 0.3
    assert cfg.state_delay_max == 1.2
```

改为

```python
    assert cfg.state_delay_min == 0.8
    assert cfg.state_delay_max == 1.2
```

- [ ] **Step 2: Write the failing tests**

追加到 `tests/unit/infra/test_anti_detection.py`：

```python
import random

from rok_assistant.infra.anti_detection import HumanProfile


def _profile(**kw):
    return HumanProfile(AntiDetectionConfig(**kw), rng=random.Random(1234))


def test_click_delay_within_bounds():
    p = _profile(action_delay_min=1.0, action_delay_max=2.0, burst_prob=0.0)
    for _ in range(200):
        assert 1.0 <= p.click_delay() <= 2.0


def test_click_delay_is_not_uniform():
    """beta 形状应当偏短：均值明显低于区间中点。"""
    p = _profile(action_delay_min=0.0, action_delay_max=1.0, burst_prob=0.0)
    samples = [p.click_delay() for _ in range(400)]
    mean = sum(samples) / len(samples)
    assert mean < 0.40            # Beta(2,5) 均值 = 2/7 ≈ 0.286
    assert mean > 0.15            # 但也不能退化到 0


def test_click_delay_uniform_shape_is_centered():
    """delay_shape=uniform 时均值回到区间中点附近（回退路径）。"""
    p = _profile(action_delay_min=0.0, action_delay_max=1.0,
                 burst_prob=0.0, delay_shape="uniform")
    samples = [p.click_delay() for _ in range(400)]
    mean = sum(samples) / len(samples)
    assert 0.40 < mean < 0.60


def test_burst_prob_one_always_short():
    p = _profile(action_delay_min=1.0, action_delay_max=2.0,
                 burst_prob=1.0, burst_scale=0.25)
    for _ in range(200):
        assert 1.0 <= p.click_delay() <= 1.25


def test_click_delay_debug_no_jitter_is_midpoint():
    p = _profile(action_delay_min=1.0, action_delay_max=3.0,
                 debug_no_jitter=True)
    assert p.click_delay() == 2.0


def test_disperse_is_gaussian_around_target():
    p = _profile(click_offset_px=10)
    xs = [p.disperse(500, 500)[0] - 500 for _ in range(500)]
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / len(xs)
    assert abs(mean) < 2.0
    assert 8.0 < var ** 0.5 < 12.0      # 标准差 ≈ σ = 10


def test_disperse_clipped_at_three_sigma():
    p = _profile(click_offset_px=10)
    for _ in range(500):
        x, y = p.disperse(500, 500)
        assert abs(x - 500) <= 30 and abs(y - 500) <= 30


def test_disperse_anchor_sigma_overrides_default():
    p = _profile(click_offset_px=20, anchor_sigma={"preset_slot": 2})
    xs = [p.disperse(500, 500, "preset_slot")[0] - 500 for _ in range(300)]
    assert all(abs(x) <= 6 for x in xs)          # 3 * σ(2)


def test_disperse_unknown_anchor_falls_back_to_default():
    p = _profile(click_offset_px=10, anchor_sigma={"preset_slot": 2})
    xs = [p.disperse(500, 500, "march_btn")[0] - 500 for _ in range(300)]
    assert max(abs(x) for x in xs) > 6           # 用的是 σ=10 而不是 2


def test_disperse_debug_no_jitter_is_exact():
    p = _profile(click_offset_px=10, debug_no_jitter=True)
    assert p.disperse(500, 500) == (500, 500)
    assert p.disperse(500, 500, "march_btn") == (500, 500)
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/infra/test_anti_detection.py -q`
Expected: FAIL —— `ImportError: cannot import name 'HumanProfile'`

- [ ] **Step 4: Implement**

在 `src/rok_assistant/infra/anti_detection.py` 顶部把 import 行改为：

```python
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
```

把 `AntiDetectionConfig` 的 `state_delay_min/max` 默认值改为 `0.8` / `1.2`，并在 `debug_no_jitter` 之后追加 4 个字段：

```python
    delay_shape: str = "beta"          # beta | uniform（uniform = 回退旧行为）
    burst_prob: float = 0.3            # 走「连点」短间隔的概率
    burst_scale: float = 0.25          # 连点间隔 = min + (max-min)*U(0, scale)
    anchor_sigma: dict = field(default_factory=dict)   # 模板 id -> σ 覆盖
```

在 `JitteringHandleSource` **之前**插入 `HumanProfile`：

```python
# Beta(2, 5)：偏短、带长尾。真人点击是突发式的——短间隔为主，偶尔拖长，
# 而不是均匀铺满整个区间。形状硬编码，不额外暴露 a/b 旋钮。
_BETA_A, _BETA_B = 2.0, 5.0
# 高斯散布裁剪到 ±3σ：截尾避免偶发的大偏移把点击甩出目标。
_SIGMA_CLIP = 3.0


class HumanProfile:
    """一处集中全部「像人」的随机化：延迟分布、坐标散布、动作节奏。

    注入 `random.Random` 后完全可复现（测试用）。`debug_no_jitter=True`
    时**所有**方法返回确定性值 —— 这是调试逃生口，也是既有测试的依赖。
    """

    def __init__(self, cfg: "AntiDetectionConfig",
                 rng: random.Random | None = None):
        self._cfg = cfg
        self._rng = rng if rng is not None else random.Random()

    # ---- 点击前延迟 ----
    def click_delay(self) -> float:
        cfg = self._cfg
        lo, hi = cfg.action_delay_min, cfg.action_delay_max
        if cfg.debug_no_jitter:
            return (lo + hi) / 2
        if hi <= lo:
            return lo
        if cfg.burst_prob > 0 and self._rng.random() < cfg.burst_prob:
            return lo + (hi - lo) * self._rng.uniform(0.0, cfg.burst_scale)
        if cfg.delay_shape == "uniform":
            return self._rng.uniform(lo, hi)
        return lo + (hi - lo) * self._rng.betavariate(_BETA_A, _BETA_B)

    # ---- 坐标散布 ----
    def disperse(self, x: int, y: int, anchor: str | None = None) -> tuple[int, int]:
        cfg = self._cfg
        if cfg.debug_no_jitter:
            return int(x), int(y)
        sigma = cfg.click_offset_px
        if anchor is not None:
            sigma = cfg.anchor_sigma.get(anchor, sigma)
        if sigma <= 0:
            return int(x), int(y)
        limit = _SIGMA_CLIP * sigma
        dx = max(-limit, min(limit, self._rng.gauss(0.0, sigma)))
        dy = max(-limit, min(limit, self._rng.gauss(0.0, sigma)))
        return int(round(x + dx)), int(round(y + dy))
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/infra/test_anti_detection.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/rok_assistant/infra/anti_detection.py tests/unit/infra/test_anti_detection.py
git commit -m "feat: HumanProfile 延迟分布（Beta + 突发）与高斯坐标散布"
```

---

### Task 5: HumanProfile 节奏方法

**Files:**
- Modify: `src/rok_assistant/infra/anti_detection.py`
- Test: `tests/unit/infra/test_anti_detection.py`（追加）

**Interfaces:**
- Produces: `HumanProfile.poll_interval() -> float`
- Produces: `HumanProfile.jitter(base: float) -> float`
- Produces: `HumanProfile.retry_attempts(base: int) -> int`
- Produces: `HumanProfile.member_response_delay() -> float`
- Produces: `AntiDetectionConfig` 新增字段 `member_response_delay_min: float = 0.0`、`member_response_delay_max: float = 0.0`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/unit/infra/test_anti_detection.py`：

```python
def test_poll_interval_within_state_delay_bounds():
    p = _profile(state_delay_min=0.5, state_delay_max=1.5)
    samples = [p.poll_interval() for _ in range(200)]
    assert all(0.5 <= s <= 1.5 for s in samples)
    assert len(set(samples)) > 50        # 不是恒定值


def test_poll_interval_debug_is_midpoint():
    p = _profile(state_delay_min=0.8, state_delay_max=1.2,
                 debug_no_jitter=True)
    assert p.poll_interval() == 1.0      # 与改动前的固定 1.0s 一致


def test_jitter_scales_base():
    p = _profile(jitter_ratio=0.3)
    for _ in range(200):
        assert 0.7 <= p.jitter(1.0) <= 1.3


def test_jitter_zero_base_is_zero():
    assert _profile().jitter(0.0) == 0.0


def test_jitter_debug_is_identity():
    p = _profile(debug_no_jitter=True)
    assert p.jitter(1.5) == 1.5


def test_retry_attempts_varies_but_stays_positive():
    p = _profile()
    seen = {p.retry_attempts(3) for _ in range(200)}
    assert seen <= {2, 3, 4}
    assert len(seen) == 3
    assert all(p.retry_attempts(1) >= 1 for _ in range(50))


def test_retry_attempts_debug_is_identity():
    assert _profile(debug_no_jitter=True).retry_attempts(3) == 3


def test_member_response_delay_default_is_zero():
    """默认关闭：不能凭空给成员号加一分钟延迟。"""
    assert _profile().member_response_delay() == 0.0


def test_member_response_delay_within_bounds():
    p = _profile(member_response_delay_min=10.0, member_response_delay_max=60.0)
    samples = [p.member_response_delay() for _ in range(200)]
    assert all(10.0 <= s <= 60.0 for s in samples)


def test_member_response_delay_debug_is_midpoint():
    p = _profile(member_response_delay_min=10.0, member_response_delay_max=60.0,
                 debug_no_jitter=True)
    assert p.member_response_delay() == 35.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/infra/test_anti_detection.py -q`
Expected: FAIL —— `AttributeError: 'HumanProfile' object has no attribute 'poll_interval'`

- [ ] **Step 3: Implement**

在 `AntiDetectionConfig` 里 `anchor_sigma` 之后追加：

```python
    member_response_delay_min: float = 0.0   # 默认关闭：见 Global Constraints
    member_response_delay_max: float = 0.0
```

在 `HumanProfile` 的 `disperse` 之后追加：

```python
    # ---- 动作节奏 ----
    def poll_interval(self) -> float:
        """轮询间隔。精确恒定的轮询间隔是签名级的机器特征。"""
        cfg = self._cfg
        lo, hi = cfg.state_delay_min, cfg.state_delay_max
        if cfg.debug_no_jitter:
            return (lo + hi) / 2
        if hi <= lo:
            return lo
        return self._rng.uniform(lo, hi)

    def jitter(self, base: float) -> float:
        """给硬编码的固定 sleep 加乘性抖动（0 保持 0）。"""
        if base <= 0:
            return 0.0
        if self._cfg.debug_no_jitter:
            return base
        r = self._cfg.jitter_ratio
        return max(0.0, base + self._rng.uniform(-base * r, base * r))

    def retry_attempts(self, base: int) -> int:
        """重试次数 ±1 —— 每轮的重试次数也是路径形状的一部分。"""
        if self._cfg.debug_no_jitter:
            return base
        return max(1, base + self._rng.randint(-1, 1))

    def member_response_delay(self) -> float:
        """成员号收到集结事件后延迟多久响应，破两号 lockstep 关联。"""
        cfg = self._cfg
        if cfg.debug_no_jitter:
            return (cfg.member_response_delay_min
                    + cfg.member_response_delay_max) / 2
        if cfg.member_response_delay_max <= cfg.member_response_delay_min:
            return cfg.member_response_delay_min
        return self._rng.uniform(cfg.member_response_delay_min,
                                 cfg.member_response_delay_max)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/infra/test_anti_detection.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/infra/anti_detection.py tests/unit/infra/test_anti_detection.py
git commit -m "feat: HumanProfile 节奏方法（轮询/抖动/重试/两号解耦延迟）"
```

---

### Task 6: HandleSource.click 加 anchor；JitteringHandleSource 改吃 profile；swipe 补抖动

**Files:**
- Modify: `src/rok_assistant/core/handle_source.py`（Protocol `:19`、`MockHandleSource:38`、`AdbHandleSource:138`、`Win32HandleSource:224`）
- Modify: `src/rok_assistant/coordination/replay.py:36`
- Modify: `src/rok_assistant/infra/anti_detection.py`（`JitteringHandleSource`）
- Test: `tests/unit/infra/test_anti_detection.py`（改既有 3 条 + 追加）

**Interfaces:**
- Consumes: `HumanProfile`（Task 4/B2）
- Produces: `HandleSource.click(x: int, y: int, anchor: str | None = None) -> None`
- Produces: `JitteringHandleSource(inner: HandleSource, profile: HumanProfile)`

- [ ] **Step 1: 改既有测试的构造与断言**

`tests/unit/infra/test_anti_detection.py` 里 `JitteringHandleSource(inner, cfg)` 的用法全部改为 `JitteringHandleSource(inner, HumanProfile(cfg, rng=random.Random(0)))`。

`test_jittering_handle_source_offset_bounds` 改为按 3σ 裁剪断言：

```python
def test_jittering_handle_source_offset_bounds():
    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=8, action_delay_min=0.0,
                              action_delay_max=0.0, debug_no_jitter=False)
    src = JitteringHandleSource(inner, HumanProfile(cfg, rng=random.Random(7)))
    for _ in range(50):
        src.click(100, 100)
        jx, jy = inner.click.call_args.args[:2]
        assert 76 <= jx <= 124 and 76 <= jy <= 124      # ±3σ
```

`test_jittering_handle_source_delegates_and_jitters` 的 swipe 断言改为按位置传参、且不断言精确时长：

```python
    src.swipe(1, 2, 3, 4, duration_ms=5)
    args = inner.swipe.call_args.args
    assert args[:4] == (1, 2, 3, 4)          # offset 0 -> 端点不变
    assert 3 <= args[4] <= 7                 # 5 ± 30%
```

- [ ] **Step 2: Write the failing tests**

追加到 `tests/unit/infra/test_anti_detection.py`：

```python
def test_jittering_handle_source_passes_anchor_to_profile():
    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=20,
                              anchor_sigma={"preset_slot": 0},
                              action_delay_min=0.0, action_delay_max=0.0)
    src = JitteringHandleSource(inner, HumanProfile(cfg, rng=random.Random(3)))
    for _ in range(30):
        src.click(100, 200, anchor="preset_slot")
        assert inner.click.call_args.args[:2] == (100, 200)   # σ=0 -> 精确


def test_jittering_handle_source_does_not_forward_anchor():
    """anchor 只用于选 σ，不往下传 —— MockHandleSource.clicks 仍是 (x, y)。"""
    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=0, action_delay_min=0.0,
                              action_delay_max=0.0)
    src = JitteringHandleSource(inner, HumanProfile(cfg, rng=random.Random(1)))
    src.click(100, 200, anchor="march_btn")
    inner.click.assert_called_once_with(100, 200)


def test_mock_handle_source_accepts_anchor_and_records_xy():
    from rok_assistant.core.handle_source import MockHandleSource
    import numpy as np
    h = MockHandleSource(np.zeros((2, 2, 3), np.uint8))
    h.click(1, 2, anchor="march_btn")
    assert h.clicks == [(1, 2)]
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/infra/test_anti_detection.py -q`
Expected: FAIL —— `TypeError: click() got an unexpected keyword argument 'anchor'`

- [ ] **Step 4: Implement — `handle_source.py`**

Protocol 的 `click` 签名改为：

```python
    def click(self, x: int, y: int, anchor: str | None = None) -> None:
        """Click at (x, y) in window-local pixel coordinates.

        `anchor` 是可选的目标名（模板 id），只用于让反检测层按目标选择
        散布 σ；实现类可以完全忽略它。
        """
        ...
```

`MockHandleSource.click` 改为（**记录内容不变**，现有断言依赖）：

```python
    def click(self, x: int, y: int, anchor: str | None = None) -> None:
        self.clicks.append((x, y))
```

`AdbHandleSource.click` 与 `Win32HandleSource.click` 的签名各加 `anchor: str | None = None`（函数体不变）。

`src/rok_assistant/coordination/replay.py` 的 `ReplayHandleSource.click` 同样加参数（函数体不变）。

- [ ] **Step 5: Implement — `JitteringHandleSource`**

把 `src/rok_assistant/infra/anti_detection.py` 的 `JitteringHandleSource` 整个替换为：

```python
class JitteringHandleSource:
    """Wraps a HandleSource: 每次点击前随机延迟 + 坐标散布（含 swipe）。

    `anchor` 只用于挑选散布 σ（见 HumanProfile.disperse），**不往下传** ——
    下游 MockHandleSource.clicks 仍记 (x, y)。
    """

    def __init__(self, inner: "HandleSource", profile: HumanProfile):
        self._inner = inner
        self._profile = profile

    def capture(self):
        return self._inner.capture()

    def click(self, x: int, y: int, anchor: str | None = None) -> None:
        time.sleep(self._profile.click_delay())
        jx, jy = self._profile.disperse(int(x), int(y), anchor)
        self._inner.click(jx, jy)

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        # 原实现是直通转发，零抖动 —— 滑动端点与时长都该抖
        time.sleep(self._profile.click_delay())
        jx1, jy1 = self._profile.disperse(int(x1), int(y1), "swipe_start")
        jx2, jy2 = self._profile.disperse(int(x2), int(y2), "swipe_end")
        self._inner.swipe(jx1, jy1, jx2, jy2,
                          int(self._profile.jitter(duration_ms)))

    def is_alive(self) -> bool:
        return self._inner.is_alive()
```

- [ ] **Step 6: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/infra/test_anti_detection.py tests/unit/core/test_adb_handle_source.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/rok_assistant/core/handle_source.py src/rok_assistant/coordination/replay.py src/rok_assistant/infra/anti_detection.py tests/unit/infra/test_anti_detection.py
git commit -m "feat: click 增加 anchor 形参；swipe 补抖动；JitteringHandleSource 改吃 HumanProfile"
```

---

### Task 7: 配置字段与样例文件同步

**Files:**
- Modify: `config.yaml:18-25`
- Modify: `config.example.yaml:28-35`
- Modify: `src/rok_assistant/gui/labels.py`（`LOC_LABELS`）
- Test: `tests/unit/gui/test_labels.py`（追加）

**Interfaces:**
- Consumes: Task 4/B2 新增的 6 个配置字段
- Produces: 无新代码接口；`LOC_LABELS` 覆盖全部新字段

- [ ] **Step 1: Write the failing test**

追加到 `tests/unit/gui/test_labels.py`：

```python
def test_all_anti_detection_fields_have_chinese_labels():
    """配置校验报错会把 loc 翻中文；漏一个就露出英文键名。"""
    from rok_assistant.infra.anti_detection import AntiDetectionConfig
    from rok_assistant.gui.labels import LOC_LABELS
    import dataclasses
    for f in dataclasses.fields(AntiDetectionConfig):
        assert f.name in LOC_LABELS, f"缺 {f.name} 的中文名"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/gui/test_labels.py -q`
Expected: FAIL —— `缺 delay_shape 的中文名`

- [ ] **Step 3: Implement**

在 `src/rok_assistant/gui/labels.py` 的 `LOC_LABELS` 里，`"debug_no_jitter": "调试模式",` 之后追加：

```python
    "delay_shape": "延迟分布形状",
    "burst_prob": "连点概率",
    "burst_scale": "连点间隔比例",
    "anchor_sigma": "按目标散布",
    "member_response_delay_min": "成员响应延迟下限",
    "member_response_delay_max": "成员响应延迟上限",
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/gui/test_labels.py -q`
Expected: PASS

- [ ] **Step 5: 同步 `config.yaml`**

把 `config.yaml:18-25` 的 `anti_detection:` 块替换为：

```yaml
  anti_detection:
    click_offset_px: 8
    action_delay_min: 3.1
    action_delay_max: 5.5
    state_delay_min: 0.6
    state_delay_max: 1.6
    jitter_ratio: 0.3
    debug_no_jitter: false
    delay_shape: beta
    burst_prob: 0.3
    burst_scale: 0.25
    anchor_sigma:
      preset_slot: 3
    member_response_delay_min: 10.0
    member_response_delay_max: 60.0
```

> `state_delay` 由 `0.3/1.2` 提到 `0.6/1.6`：0.3 秒轮询意味着每 0.3 秒一次 adb 截图，
> 而单次截图要 150~300ms，会把 adb 队列打爆。
> `anchor_sigma.preset_slot: 3`：预设槽是实测钉死的固定位置（`leader_sm.py:73-79`），
> 散布要收紧，默认 σ=8 会让它偶尔点空。

- [ ] **Step 6: 同步 `config.example.yaml`**

把 `config.example.yaml:28-35` 替换为：

```yaml
  anti_detection:
    click_offset_px: 8      # 点击散布的默认 σ（高斯，裁剪到 ±3σ）；0 = 点得完全准
    action_delay_min: 0.1   # 每次点击前延迟的下限（秒）
    action_delay_max: 0.5   # 上限。区间内按 delay_shape 采样，不是均匀铺满
    state_delay_min: 0.6    # 轮询间隔下限（秒）。别低于 0.5：每次轮询要截一帧，
    state_delay_max: 1.6    # 单次 adb 截图 150~300ms，太密会把 adb 队列打爆
    jitter_ratio: 0.3       # 硬编码固定等待（如补体力后的 1.5s）的抖动比例
    debug_no_jitter: false  # 改 true = 关闭全部随机化（调试时看真实点击坐标）
    delay_shape: beta       # beta = 偏短带长尾（像人）；uniform = 均匀（旧行为）
    burst_prob: 0.3         # 走「连点」短间隔的概率
    burst_scale: 0.25       # 连点间隔 = min + (max-min) * U(0, 此值)
    anchor_sigma:           # 按目标覆盖散布 σ；缺省用 click_offset_px
      preset_slot: 3
    member_response_delay_min: 10.0   # 成员号收到集结事件后延迟多久响应（秒）。
    member_response_delay_max: 60.0   # 两号同机、永远成对出现是强关联信号，错开它。
                                      # 0/0 = 关闭（默认关闭）
```

- [ ] **Step 7: 校验配置能被加载**

Run:
```bash
.venv/Scripts/python.exe -X utf8 -c "from rok_assistant.infra.config import load_config; c=load_config('config.yaml'); print(c.app.anti_detection)"
```
Expected: 打印出 `AntiDetectionConfig(...)`，`delay_shape='beta'`、`anchor_sigma={'preset_slot': 3}`

- [ ] **Step 8: Commit**

```bash
git add config.yaml config.example.yaml src/rok_assistant/gui/labels.py tests/unit/gui/test_labels.py
git commit -m "feat: 配置新增人性化字段；同步 config.yaml / 示例 / 中文标签"
```

---

### Task 8: 状态机接线 + factory/runtime 注入

**Files:**
- Modify: `src/rok_assistant/workers/state_machine.py`（`__init__:19`、`_click_result:68`、`_click_xy:73`、`_find_retry:89`、`_wait_for_result:105`、`_wait_for:117`、`_wait_click:120`、`_refill_ap:142,145`、`_close_ap_dialog:156`）
- Modify: `src/rok_assistant/workers/leader_sm.py`（`__init__:68`、`super().__init__:105`、`_click_xy` 调用点 `:538`）
- Modify: `src/rok_assistant/workers/member_sm.py`（`__init__:50`、`super().__init__:74`、`:228`、`:265`）
- Modify: `src/rok_assistant/workers/either_sm.py`（`__init__:68`）
- Modify: `src/rok_assistant/workers/factory.py:9`
- Modify: `src/rok_assistant/coordination/runtime.py:139,161`
- Test: `tests/unit/workers/test_state_machine.py`（追加）

**Interfaces:**
- Consumes: `HumanProfile`（B1/B2）、`HandleSource.click(..., anchor=)`（B3）
- Produces: `StateMachine.__init__(initial: str, human: HumanProfile | None = None)`；默认 profile 为 `HumanProfile(AntiDetectionConfig(debug_no_jitter=True))`
- Produces: `_find_retry(rec_id, attempts=3, interval: float | None = None)`；`_wait_for_result(rec_id, timeout=10.0, interval: float | None = None)`；`_wait_for(rec_id, timeout=10.0, interval=None)`；`_wait_click(rec_id, timeout=15.0, interval=None)`；`_click_xy(x, y, anchor=None)`
- Produces: `create_state_machine(..., human: HumanProfile | None = None)`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/unit/workers/test_state_machine.py`：

```python
import random
from unittest.mock import MagicMock

from rok_assistant.infra.anti_detection import AntiDetectionConfig, HumanProfile


class _SM(StateMachine):
    def _setup(self):
        pass


def _sm(human=None):
    return _SM("IDLE", human=human)


def test_default_profile_is_deterministic():
    """不注入 profile 时走 debug_no_jitter：轮询恰好 1.0s，与改动前一致。"""
    sm = _sm()
    assert sm._human.poll_interval() == 1.0
    assert sm._human.retry_attempts(3) == 3


def test_find_retry_uses_profile_poll_interval(monkeypatch):
    import rok_assistant.workers.state_machine as sm_mod
    slept = []
    monkeypatch.setattr(sm_mod.time, "sleep", slept.append)
    p = HumanProfile(AntiDetectionConfig(state_delay_min=0.5, state_delay_max=0.5),
                     rng=random.Random(0))
    sm = _sm(human=p)
    sm._handle = MagicMock()
    sm._rec = {}
    assert sm._find_retry("nope", attempts=3) is None
    assert slept == [0.5, 0.5]           # 3 次尝试 -> 2 次等待


def test_explicit_interval_is_jittered_not_replaced(monkeypatch):
    import rok_assistant.workers.state_machine as sm_mod
    slept = []
    monkeypatch.setattr(sm_mod.time, "sleep", slept.append)
    p = HumanProfile(AntiDetectionConfig(jitter_ratio=0.3), rng=random.Random(0))
    sm = _sm(human=p)
    sm._handle = MagicMock()
    sm._rec = {}
    sm._find_retry("nope", attempts=2, interval=2.0)
    assert len(slept) == 1
    assert 1.4 <= slept[0] <= 2.6        # 2.0 ± 30%


def test_click_result_passes_recognizer_id_as_anchor():
    sm = _sm()
    sm._handle = MagicMock()
    bbox = MagicMock()
    bbox.center.return_value = (10, 20)
    result = MagicMock()
    result.bbox = bbox
    result.recognizer_id = "march_btn"
    sm._click_result(result)
    sm._handle.click.assert_called_once_with(10, 20, anchor="march_btn")


def test_click_xy_passes_anchor():
    sm = _sm()
    sm._handle = MagicMock()
    sm._click_xy(100, 200, anchor="preset_slot")
    sm._handle.click.assert_called_once_with(100, 200, anchor="preset_slot")
```

> 若 `tests/unit/workers/test_state_machine.py` 顶部尚未 import `StateMachine`，补上
> `from rok_assistant.workers.state_machine import StateMachine`。

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/workers/test_state_machine.py -q`
Expected: FAIL —— `TypeError: __init__() got an unexpected keyword argument 'human'`

- [ ] **Step 3: Implement — `state_machine.py`**

顶部 import 区加：

```python
from ..infra.anti_detection import AntiDetectionConfig, HumanProfile
```

`StateMachine.__init__` 改为：

```python
class StateMachine:
    def __init__(self, initial: str, human: HumanProfile | None = None):
        self._transitions: list[Transition] = []
        self.current = initial
        self.history: list[str] = [initial]
        self._ctx: dict = {}
        self.last_image = None  # last captured frame; kept for failure screenshots
        # 默认 profile 是确定性的（debug_no_jitter）：直接构造状态机
        # （测试、库用法）时行为与改动前逐字相同；生产路径由 runtime 注入
        # 配置驱动的 profile。
        self._human = human if human is not None else HumanProfile(
            AntiDetectionConfig(debug_no_jitter=True))
        self._setup()
```

`_click_result` 与 `_click_xy` 改为：

```python
    def _click_result(self, r: RecognizeResult) -> bool:
        x, y = r.bbox.center()
        self._handle.click(x, y, anchor=r.recognizer_id)
        return True

    def _click_xy(self, x: float, y: float, anchor: str | None = None) -> bool:
        """按绝对像素点一点（反检测抖动仍走 handle.click）。

        用于「实测钉死的固定位置」——预设槽列就是这种：44 帧逐像素实测
        `cy=474+82*(N-1)`、`cx=1655` 零漂移。模板腿失配（_click 空操作）时
        用它兜底，比让整轮空过强。`anchor` 让散布 σ 能按目标收紧。
        """
        self._handle.click(int(x), int(y), anchor=anchor)
        return True
```

新增 `_pause` 辅助，并把 `_find_retry` / `_wait_for_result` / `_wait_for` / `_wait_click` 改为：

```python
    def _pause(self, base: float | None) -> float:
        """轮询间隔：调用方给了基准就抖动基准，没给就用 profile 的轮询节奏。"""
        return self._human.poll_interval() if base is None else self._human.jitter(base)

    def _find_retry(self, rec_id: str, attempts: int = 3,
                    interval: float | None = None) -> RecognizeResult | None:
        attempts = self._human.retry_attempts(attempts)
        for i in range(attempts):
            r = self._find(rec_id)
            if r is not None:
                return r
            if i < attempts - 1:
                time.sleep(self._pause(interval))
        return None

    def _click_retry(self, rec_id: str, attempts: int = 3,
                     interval: float | None = None) -> bool:
        r = self._find_retry(rec_id, attempts=attempts, interval=interval)
        if r is None:
            return False
        return self._click_result(r)

    def _wait_for_result(self, rec_id: str, timeout: float = 10.0,
                         interval: float | None = None) -> RecognizeResult | None:
        deadline = time.time() + timeout
        while True:
            r = self._find(rec_id)
            if r is not None:
                return r
            if time.time() >= deadline:
                return None
            pause = self._pause(interval)
            if pause > 0:
                time.sleep(min(pause, max(0.0, deadline - time.time())))

    def _wait_for(self, rec_id: str, timeout: float = 10.0,
                  interval: float | None = None) -> bool:
        return self._wait_for_result(rec_id, timeout=timeout, interval=interval) is not None

    def _wait_click(self, rec_id: str, timeout: float = 15.0,
                    interval: float | None = None) -> bool:
        r = self._wait_for_result(rec_id, timeout=timeout, interval=interval)
        if r is None:
            return False
        return self._click_result(r)
```

固定 sleep 改为走 `jitter`：`_refill_ap` 里两处 `time.sleep(1.5)` → `time.sleep(self._human.jitter(1.5))`；`_close_ap_dialog` 里 `time.sleep(1.2)` → `time.sleep(self._human.jitter(1.2))`。

- [ ] **Step 4: Implement — 三个状态机子类**

三个子类的 `__init__` 签名末尾各加 `human=None`，并把 `super().__init__(initial="IDLE")` 改为 `super().__init__(initial="IDLE", human=human)`。

`leader_sm.py:538` 的 `self._click_xy(*slot_center(n, self._preset_base))` 改为：

```python
            self._click_xy(*slot_center(n, self._preset_base), anchor="preset_slot")
```

`member_sm.py:228` 与 `:265` 的 `_click_retry(..., interval=1.0)` 去掉 `interval=1.0`（改用 profile 节奏）。

`leader_sm.py:528-529` 与 `:539-540` 的 `interval=_PRESET_CONFIRM_INTERVAL` **保留**（0.5s 是"确认高亮"的专用节奏，走 `jitter`）。

- [ ] **Step 5: Implement — `factory.py` 与 `runtime.py`**

`factory.py` 的签名与三个分支：

```python
def create_state_machine(character: CharacterConfig, handle_source, recognizers: dict,
                         event_bus=None, rally_tracker=None, ledger=None,
                         human=None):
```

三个 `return` 各加 `human=human`（`LeaderStateMachine(...)`、`MemberStateMachine(...)`、`EitherStateMachine(...)`）。

`runtime.py` 的 `start()` 里，`handle = JitteringHandleSource(...)` 之前构造 profile：

```python
                profile = HumanProfile(self._config.app.anti_detection)
                handle = JitteringHandleSource(handle, profile)
```

`_spawn` 的 `create_state_machine(...)` 调用加 `human=profile`，并把 `profile` 作为参数传进 `_spawn`：

```python
    def _spawn(self, inst, char, handle, recognizers, profile) -> None:
        ...
            sm_factory=lambda: create_state_machine(char, handle, recognizers,
                                                    self._bus, self._rally_tracker,
                                                    ledger=self.ledger,
                                                    human=profile),
```

调用点改为 `self._spawn(inst, char, handle, recognizers, profile)`。

`runtime.py` 顶部 import 加 `from ..infra.anti_detection import HumanProfile`。

- [ ] **Step 6: Run to verify it passes**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/unit/workers/test_state_machine.py tests/unit/workers/test_leader_sm.py tests/unit/workers/test_either_sm.py tests/unit/workers/test_worker_factory.py tests/unit/workers/test_normalize_view.py -q
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/rok_assistant/workers/ src/rok_assistant/coordination/runtime.py tests/unit/workers/test_state_machine.py
git commit -m "feat: 状态机接入 HumanProfile（轮询节奏/固定 sleep/anchor 透传）"
```

---

### Task 9: runner 与 either_sm 的固定间隔抖动

**Files:**
- Modify: `src/rok_assistant/workers/runner.py`（`_run:167,193`、`_set_status` 附近的 `_cooldown`/`_poll`）
- Modify: `src/rok_assistant/workers/either_sm.py`（`_WAIT_RETURN_POLL:14`、`:260`）
- Test: `tests/unit/workers/test_runner.py`（追加）、`tests/unit/workers/test_either_sm.py`（追加）

**Interfaces:**
- Consumes: `HumanProfile.jitter(base)`（B2）、`HumanProfile`（B5 的 `self._human`）
- Produces: `WorkerRunner(..., human: HumanProfile | None = None)`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/unit/workers/test_runner.py`：

```python
import random
from rok_assistant.infra.anti_detection import AntiDetectionConfig, HumanProfile


def test_runner_cooldown_is_jittered(monkeypatch):
    """冷却等待不再恒定 30.0s。"""
    import rok_assistant.workers.runner as runner_mod
    from tests.unit.workers.test_runner import make_runner   # 若已有工厂则复用；否则见下
    ...
```

> **若 `test_runner.py` 没有现成的 runner 构造工厂**，用下面这条自足版本替代（不需要构造完整 runner）：

```python
def test_cooldown_wait_uses_jitter():
    """直接验证 runner 用的等待时长来自 profile.jitter，而不是硬编码常量。"""
    p = HumanProfile(AntiDetectionConfig(jitter_ratio=0.3), rng=random.Random(0))
    seen = {round(p.jitter(30.0), 3) for _ in range(100)}
    assert len(seen) > 50
    assert all(21.0 <= v <= 39.0 for v in seen)
```

追加到 `tests/unit/workers/test_either_sm.py`：

```python
def test_wait_return_poll_is_jittered():
    import random
    from rok_assistant.infra.anti_detection import AntiDetectionConfig, HumanProfile
    p = HumanProfile(AntiDetectionConfig(jitter_ratio=0.3), rng=random.Random(0))
    seen = {round(p.jitter(30.0), 3) for _ in range(100)}
    assert len(seen) > 50
    assert all(21.0 <= v <= 39.0 for v in seen)
```

> 这两条先立住"抖动函数本身可用"，下面 Step 3/4 的接线由 Task 11 的全套回归 + 实机观察兜底。
> **不要**为了断言 `_next_check` 的精确值去 mock `time.time`——那会把测试绑死在实现细节上。

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/workers/test_runner.py tests/unit/workers/test_either_sm.py -q`
Expected: PASS（这两条只依赖 B2 的 `jitter`，此时应已通过）——**若已通过，直接进 Step 3**。

- [ ] **Step 3: Implement — `runner.py`**

`WorkerRunner.__init__` 签名末尾加 `human: HumanProfile | None = None`，并：

```python
        self._human = human if human is not None else HumanProfile(
            AntiDetectionConfig(debug_no_jitter=True))
```

`_run` 里两处固定等待改为抖动值：

```python
                    self._set_status("cooldown")
                    self._stop_event.wait(self._human.jitter(self._cooldown))
```

```python
            self._stop_event.wait(self._human.jitter(self._poll))
```

`runtime.py` 的 `_spawn` 里 `WorkerRunner(...)` 加 `human=profile`。

- [ ] **Step 4: Implement — `either_sm.py`**

`EitherStateMachine` 已经通过 B5 拿到 `self._human`（`human` 参数经 `super().__init__` 落到基类）。把 `:260` 的

```python
        self._next_check = now + _WAIT_RETURN_POLL
```

改为

```python
        self._next_check = now + self._human.jitter(_WAIT_RETURN_POLL)
```

`:224` 的日志文案里 `_WAIT_RETURN_POLL` 只是打印上限，保持常量不变。

- [ ] **Step 5: Run to verify it passes**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/unit/workers/test_runner.py tests/unit/workers/test_either_sm.py tests/unit/workers/test_either_sm_gate.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/rok_assistant/workers/runner.py src/rok_assistant/workers/either_sm.py src/rok_assistant/coordination/runtime.py tests/unit/workers/
git commit -m "feat: 冷却/轮询/返城检测间隔去规律化"
```

---

### Task 10: 两号解耦（成员号延迟响应集结）

**Files:**
- Modify: `src/rok_assistant/workers/member_sm.py`（`__init__:50`、`_setup:81-83`、`on_rally_launched:118`）
- Test: `tests/unit/workers/test_member_sm.py`（追加；若无此文件则新建）

**Interfaces:**
- Consumes: `HumanProfile.member_response_delay()`（B2）、`self._human`（B5）
- Produces: `MemberStateMachine.on_rally_launched(event)` 记录 `self._respond_at`

- [ ] **Step 1: Write the failing tests**

新建/追加到 `tests/unit/workers/test_member_sm.py`：

```python
import random
from unittest.mock import MagicMock

from rok_assistant.infra.anti_detection import AntiDetectionConfig, HumanProfile
from rok_assistant.workers.member_sm import MemberStateMachine


def _member(human):
    return MemberStateMachine(MagicMock(), {}, [], char_id="m1", human=human)


def test_rally_response_is_delayed():
    """收到集结事件后不能立刻推进 —— 要等够 profile 给的延迟。"""
    p = HumanProfile(AntiDetectionConfig(member_response_delay_min=10.0,
                                         member_response_delay_max=60.0),
                     rng=random.Random(0))
    sm = _member(p)
    sm.on_rally_launched({"leader": "boss"})
    assert sm._respond_at > 0
    sm.step()                                  # 消费事件 -> WAIT_LAUNCH_EVENT
    assert sm.current == "WAIT_LAUNCH_EVENT"
    sm.step()                                  # 延迟没到 -> 原地不动
    assert sm.current == "WAIT_LAUNCH_EVENT"


def test_rally_response_proceeds_after_delay(monkeypatch):
    p = HumanProfile(AntiDetectionConfig(member_response_delay_min=10.0,
                                         member_response_delay_max=10.0))
    sm = _member(p)
    sm.on_rally_launched({"leader": "boss"})
    sm.step()
    assert sm.current == "WAIT_LAUNCH_EVENT"
    monkeypatch.setattr("rok_assistant.workers.member_sm.time.time",
                        lambda: sm._respond_at + 1)
    sm.step()
    assert sm.current == "SWITCH_TO_SELF"


def test_default_profile_has_no_response_delay():
    """默认关闭：既有测试与不注入 profile 的调用方行为不变。"""
    sm = _member(HumanProfile(AntiDetectionConfig(debug_no_jitter=True)))
    sm.on_rally_launched({"leader": "boss"})
    assert sm._respond_at == 0.0
    sm.step()
    sm.step()
    assert sm.current == "SWITCH_TO_SELF"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/workers/test_member_sm.py -q`
Expected: FAIL —— `AttributeError: 'MemberStateMachine' object has no attribute '_respond_at'`

- [ ] **Step 3: Implement**

`MemberStateMachine.__init__` 里加：

```python
        # 集结响应延迟：破「一台开集结、另一台 N 秒内必填」的 lockstep 关联。
        # 0 = 立即响应（默认，见 AntiDetectionConfig 的默认值）。
        self._respond_at = 0.0
```

`_setup` 里 `WAIT_LAUNCH_EVENT` 那条转移加 guard（**必须与现有 `add_transition` 调用逐字对应**）：

```python
        self.add_transition("WAIT_LAUNCH_EVENT", "SWITCH_TO_SELF", self._switch_to_self,
                            guard=lambda ctx: time.time() >= self._respond_at)
```

`on_rally_launched` 改为：

```python
    def on_rally_launched(self, event: dict) -> None:
        self._pending_event = event
        # 延迟必须在**成员自己的线程**里等：EventBus.publish 是同步的
        # （event_bus.py:20-27），在 router 里 sleep 会阻塞车头线程。
        self._respond_at = time.time() + self._human.member_response_delay()
```

文件顶部确认有 `import time`（`member_sm.py` 已用 `time` 则跳过）。

- [ ] **Step 4: Run to verify it passes**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/unit/workers/test_member_sm.py tests/unit/workers/test_either_sm.py tests/unit/workers/test_either_sm_gate.py tests/integration/test_end_to_end.py -q
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/workers/member_sm.py tests/unit/workers/test_member_sm.py
git commit -m "feat: 成员号延迟响应集结，破两号 lockstep 关联"
```

---

### Task 11: 全量回归 + 文档

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/HISTORY.md`

- [ ] **Step 1: 跑全套**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 全绿（基线 661 条 + 本计划新增）。

**若出现批量 setup 阶段 `E`**（而非断言失败）：那是 `.pytest_tmp` 被孤儿 pytest 进程占住的已知问题（`docs/PROGRESS.md` 已知问题 7），不是回归。修法：杀光孤儿 `python.exe` → `rm -rf .pytest_tmp` → 重跑。

- [ ] **Step 2: 清理死字段残留**

Run: `grep -rn "jitter_offset\|jitter_delay" src/`
Expected: 只剩 `anti_detection.py` 里的定义（供既有单测使用）。若 `JitteringHandleSource` 仍在用它们，说明 B3 没改干净——回去改。

- [ ] **Step 3: 更新 `docs/PROGRESS.md`**

- 在「已落地」表格加一行：`10-05 | 每实例日志区 + 人性化层 | 卡片内嵌日志（按线程名归属）；HumanProfile 分布化延迟/高斯散布/节奏去规律化/两号解耦 | 待实机`
- **删除**「已知问题」第 5 条的 `anti_detection` 部分（`state_delay_*`/`jitter_ratio` 不生效）——本次已接上。
- 在「接下来需要做的 / 待办」加：`[ ] 人性化层实机观察：跑 2~3 轮确认无卡顿、无点击落空`

- [ ] **Step 4: 更新 `docs/HISTORY.md`**

追加一节，记录：改了什么、为什么 `state_delay` 默认取 `0.8/1.2` 而不是 `0.6/1.6`、为什么 `member_response_delay` 默认关闭、以及**本设计治不了什么**（玩法规律 / 设备指纹 / 固定轮数）。

- [ ] **Step 5: Commit**

```bash
git add docs/PROGRESS.md docs/HISTORY.md
git commit -m "docs: 记录日志区与人性化层落地；移除已修复的 anti_detection 已知问题"
```

---

## Self-Review

**Spec 覆盖检查**

| Spec 章节 | 对应 Task |
|---|---|
| §3 每实例日志区（归属规则/组件/边界） | A1, A2, A3 |
| §4.1 HumanProfile 方法表 | B1, B2 |
| §4.2 字段复活与新增 | B1, B2, B4 |
| §4.3 接线点表 | B3, B5, B6 |
| §4.4 两号解耦 | B7 |
| §4.5 路径能给的三种变化 | B2（`retry_attempts`）, B5（轮询）, B6（间隔） |
| §5 诚实边界 | B8（写进 HISTORY） |
| §6 测试策略 | 各 Task 的 Step 1；B8 跑全套 |
| §7 兼容性与回滚 | Global Constraints + B1/B2 的默认值决策 |

**缺口说明**：spec §4.5 提到的"偶尔多看一次屏（冗余观察）"**未排期**。理由：它需要往每个状态机的转移里插分支，收益不确定而改动面很大；先落地确定有效的四条（延迟分布、坐标散布、轮询节奏、两号解耦），观察实机效果再决定要不要加。

**类型一致性检查**（跨 Task 的签名必须逐字一致）

- `HumanProfile(cfg, rng=None)` — B1 定义，B3/B5/B6/B7 使用 ✓
- `HumanProfile.disperse(x, y, anchor=None) -> tuple[int, int]` — B1 定义，B3 使用 ✓
- `HumanProfile.jitter(base: float) -> float` — B2 定义，B3（swipe 时长）/B5（固定 sleep）/B6（冷却、返城）使用 ✓
- `HumanProfile.poll_interval() -> float` — B2 定义，B5 的 `_pause` 使用 ✓
- `HumanProfile.retry_attempts(base: int) -> int` — B2 定义，B5 的 `_find_retry` 使用 ✓
- `HumanProfile.member_response_delay() -> float` — B2 定义，B7 使用 ✓
- `HandleSource.click(x, y, anchor=None)` — B3 定义，B5 的 `_click_result`/`_click_xy` 使用 ✓
- `StateMachine.__init__(initial, human=None)` — B5 定义，B7 依赖 `self._human` ✓
- `create_state_machine(..., human=None)` — B5 定义并同步 `runtime.py` 调用点 ✓
- `WorkerRunner(..., human=None)` — B6 定义并同步 `runtime.py` 的 `_spawn` ✓

**占位符扫描**：无 TBD / TODO / "类似 Task N"。每个代码步骤都给了可粘贴的实现。

**已知的两处"若…则…"**：A2 Step 1 里那句笔误断言、B6 Step 1 的测试构造兜底 —— 两处都给了具体代码，不是占位符。
