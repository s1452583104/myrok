# 运行时里程碑（填兵去预设 + §1.5 状态机修正 + 调度器接线）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已实现但未接线的运行时真正跑起来：member 填兵不点预设（用户明确要求）、状态机按 2026-09 实测修正、WorkerRunner/RuntimeCoordinator 消费 `create_state_machine` 工厂、GUI Start/Stop 可用。

**Architecture:** 每实例 1 个 HandleSource（ADB，包一层 JitteringHandleSource 防检测）→ 每实例第 1 个角色 1 个 WorkerRunner 线程（循环 step 状态机、发布 status、异常截图、终态重建）。RuntimeCoordinator 从 RootConfig 组装一切并通过 EventBus 路由 `rally_launched` 给 member 角色。GuiController 变成 QObject 信号桥（worker 线程 → Qt 主线程），MainWindow 用 config 建卡、Start/Stop 接真。

**Tech Stack:** Python 3.11+、pydantic v2、PyQt6、pytest（GUI 测试 `QT_QPA_PLATFORM=offscreen`）、OpenCV TemplateMatch。

**背景（执行者必读的实测事实，来自 2026-09-07~10 实机）：**

1. **当前 leader_sm 在真实屏幕上会死循环**：`_check_result` 直接等 `rally_attack_popup`，但真实流程是 搜索→城寨详情弹窗（含红「集结」按钮=red_rally）→**必须点 red_rally**→才出现集结进攻弹窗。现代码从不点 red_rally。
2. **视角归一化（ACCEPTANCE §1.5.2）**：城市视角左下角是蓝色地图按钮（模板 `map_btn`，2026-09-10 已采集，城市视角 1.0 / 地图视角 0.528 不匹配）；点它进世界地图视角后 `search_icon` 稳定 0.998。成员的 `alliance_btn` 也是地图视角底部栏的按钮，同样需要归一化。
3. **搜索面板记住上次等级**（实测显示 8），等级加减不能假设从 1 开始。
4. **填兵不使用预设**（用户原话「填兵不使用预设操作，直接使用默认的即可」）：member 的 `march_preset`/`march_troop_types` 只在它当车头时才有意义。车头开集结仍用预设槽（用户确认「集结都使用预设槽1」）。
5. **锁定的城寨**：点红集结后 5 秒内不出现集结进攻弹窗即视为被锁（ACCEPTANCE §3.3）；⭐ 书签与锁定无关。
6. **无结果 toast**：`toast_no_fortress`（「您的城市附近暂未找到符合条件的野蛮人城寨」）。
7. **切角色是 5 步 + 确认 + 重登**（§1.5.1）：头像→设置→角色管理→点目标角色→「角色登入」确认框点「是」（`switch_confirm_yes`）→完整重登（`click_to_enter`→约 20-25s）。主界面左上角**没有角色名**（§1.5.3），校验靠头像模板，无模板则跳过。
8. **模板 31+1 个已采齐**（march_btn、preset_1~6、troop_infantry/cavalry/archer/siege、map_btn 等）；`templates/*.png` 被 .gitignore，不入库，只入库 manifest.yaml。
9. **v1 限制（写进代码注释和文档）**：每实例只跑第 1 个角色（多角色切换属 v2）；member 填兵暂时加入排序后第一个集结（按名字 OCR 匹配是后续里程碑 §3.7）；either 角色的集结可能被自己的 member 阶段搜到，v1 接受该风险。
10. **测试基线**：142 passed。所有测试跑 `python -m pytest tests/ -q`，GUI 测试文件顶部 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`。recognizer 测试替身用 `MagicMock`（`recognize.return_value.matched=True`、`bbox.center=lambda:(50,50)`）+ `MockHandleSource`。
11. **状态机测试速度关键**：SM 动作里的 `time.sleep` 必须可通过构造参数归零（`wait_members_seconds`、`load_wait_seconds`），否则单测挂 5 分钟。
12. **EitherStateMachine 契约**（`workers/either_sm.py` docstring）：`step()`/`is_terminal()`/`departed` 归 Leader SM 所有，调用方不得预置。

---

### Task 1: TemplateRegistry.build_recognizers()

**Files:**
- Modify: `src/rok_assistant/core/template_registry.py`
- Test: `tests/unit/core/test_template_registry.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/unit/core/test_template_registry.py`，沿用该文件现有的 manifest_test.yaml fixture 约定）

```python
def test_build_recognizers_returns_template_matches(tmp_path):
    # 复用文件内已有的 manifest 写法；若该文件用 fixtures/manifest_test.yaml 则直接用
    import cv2
    from rok_assistant.core.template_registry import TemplateRegistry
    reg = TemplateRegistry.load(Path("tests/fixtures/manifest_test.yaml"))
    recs = reg.build_recognizers()
    assert set(recs) >= {"search"}          # manifest_test.yaml 里的模板 id
    r = recs["search"].recognize(
        cv2.imread("tests/fixtures/screenshot_with_template.png"))
    assert r.matched
```

（若 `manifest_test.yaml` 的 id 不是 `search`，按实际 id 改断言；先读 fixture 确认。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/core/test_template_registry.py -q`
Expected: FAIL，`AttributeError: 'TemplateRegistry' object has no attribute 'build_recognizers'`

- [ ] **Step 3: 实现**（在 `TemplateRegistry` 类中，`load` 之后加）

```python
    def build_recognizers(self) -> dict:
        """Build {template_id: TemplateMatch} for all loaded templates."""
        import cv2
        from .recognizers.template_match import TemplateMatch
        from .recognizer import BBox
        out = {}
        for tid, spec in self._t.items():
            img = cv2.imread(str(spec.file))
            if img is None:
                raise FileNotFoundError(f"template image missing: {spec.file}")
            roi = None if spec.roi.is_full else BBox(spec.roi.x1, spec.roi.y1, spec.roi.x2, spec.roi.y2)
            out[tid] = TemplateMatch(img, threshold=spec.threshold, roi=roi, name=tid)
        return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/core/test_template_registry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/core/template_registry.py tests/unit/core/test_template_registry.py
git commit -m "feat: TemplateRegistry.build_recognizers() for runtime assembly"
```

---

### Task 2: JitteringHandleSource（防检测包装）

**Files:**
- Modify: `src/rok_assistant/infra/anti_detection.py`
- Test: `tests/unit/infra/test_anti_detection.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/unit/infra/test_anti_detection.py`）

```python
def test_jittering_handle_source_delegates_and_jitters():
    from unittest.mock import MagicMock
    from rok_assistant.infra.anti_detection import (
        AntiDetectionConfig, JitteringHandleSource)

    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=0, action_delay_min=0.0,
                              action_delay_max=0.0, debug_no_jitter=False)
    src = JitteringHandleSource(inner, cfg)
    src.click(100, 200)
    inner.click.assert_called_once_with(100, 200)  # offset 0 -> 精确坐标
    assert src.is_alive() is inner.is_alive.return_value
    assert src.capture() is inner.capture.return_value
    # swipe 透传
    src.swipe(1, 2, 3, 4, duration_ms=5)
    inner.swipe.assert_called_once_with(1, 2, 3, 4, duration_ms=5)

def test_jittering_handle_source_offset_bounds():
    from unittest.mock import MagicMock
    from rok_assistant.infra.anti_detection import (
        AntiDetectionConfig, JitteringHandleSource)

    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=8, action_delay_min=0.0,
                              action_delay_max=0.0, debug_no_jitter=False)
    src = JitteringHandleSource(inner, cfg)
    for _ in range(50):
        src.click(100, 100)
        jx, jy = inner.click.call_args.args
        assert 92 <= jx <= 108 and 92 <= jy <= 108
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/infra/test_anti_detection.py -q`
Expected: FAIL，`ImportError: cannot import name 'JitteringHandleSource'`

- [ ] **Step 3: 实现**（追加到 `src/rok_assistant/infra/anti_detection.py` 末尾）

```python
import time

class JitteringHandleSource:
    """包装 HandleSource：点击前加随机偏移 + 随机延时（设计稿 §8.3/8.4）。

    debug_no_jitter=True 时 jitter_offset 已返回原坐标、random_action_delay
    返回中值，本包装自然退化为直通。
    """

    def __init__(self, inner, cfg: AntiDetectionConfig):
        self._inner = inner
        self._cfg = cfg

    def capture(self):
        return self._inner.capture()

    def click(self, x: int, y: int) -> None:
        time.sleep(self._cfg.random_action_delay())
        jx, jy = jitter_offset(int(x), int(y), self._cfg)
        self._inner.click(jx, jy)

    def swipe(self, *args, **kwargs):
        return self._inner.swipe(*args, **kwargs)

    def is_alive(self) -> bool:
        return self._inner.is_alive()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/infra/test_anti_detection.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/infra/anti_detection.py tests/unit/infra/test_anti_detection.py
git commit -m "feat: JitteringHandleSource anti-detection wrapper"
```

---

### Task 3: StateMachine 公共 find/click + 重试等待助手

`leader_sm`/`member_sm` 各有一份重复的 `_find`/`_click`，且都是"点一下失败就过"。抽到基类并加重试/等待（真实屏幕上弹窗需要时间出现）。

**Files:**
- Modify: `src/rok_assistant/workers/state_machine.py`
- Modify: `src/rok_assistant/workers/leader_sm.py`（删除本地 `_find`/`_click`）
- Modify: `src/rok_assistant/workers/member_sm.py`（删除本地 `_click`）
- Test: `tests/unit/workers/test_state_machine.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/unit/workers/test_state_machine.py`）

```python
def _fake_rec(matched=True):
    from unittest.mock import MagicMock
    rec = MagicMock()
    rec.recognize.return_value.matched = matched
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec

def test_base_helpers_click_retry_and_wait_for():
    import numpy as np
    from unittest.mock import MagicMock
    from rok_assistant.core.handle_source import MockHandleSource
    from rok_assistant.workers.leader_sm import LeaderStateMachine

    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = _fake_rec()
    # 前两次 capture 没找到，第三次找到：用 side_effect 切换 matched
    results = [MagicMock(matched=False), MagicMock(matched=False),
               MagicMock(matched=True, bbox=MagicMock(center=lambda: (50, 50)))]
    rec.recognize.side_effect = results + [results[-1]] * 100
    sm = LeaderStateMachine(handle, {"x": rec}, target_level=7, march_preset=1,
                            march_troop_types=["cavalry"],
                            wait_members_seconds=0.0)
    assert sm._wait_for("x", timeout=10.0, interval=0.0) is True
    assert sm._click_retry("x", attempts=1, interval=0.0) is True
    assert handle.clicks == [(50, 50)]
    assert sm._find_retry("nope", attempts=2, interval=0.0) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/workers/test_state_machine.py -q`
Expected: FAIL，`AttributeError: ... no attribute '_wait_for'`（`wait_members_seconds` 参数也不存在，Task 5 才加——本步先只测 `_wait_for/_click_retry/_find_retry`，构造 LeaderStateMachine 用现有签名 `LeaderStateMachine(handle, {"x": rec}, 7, 1, ["cavalry"])`，Task 5 再改此测试签名）

- [ ] **Step 3: 实现**（`state_machine.py` 的 `StateMachine` 类内，`step` 之后加；注意两个 SM 都在 `super().__init__()` **之前**设置 `self._handle/self._rec`，基类方法运行时才访问，安全）

```python
    # ---- 公共识别/点击助手（子类共享；要求子类有 _handle/_rec）----
    def _find(self, rec_id: str):
        img = self._handle.capture()
        self.last_image = img
        r = self._rec[rec_id].recognize(img)
        return r if r.matched else None

    def _click(self, rec_id: str) -> bool:
        r = self._find(rec_id)
        if r is None:
            return False
        x, y = r.bbox.center()
        self._handle.click(x, y)
        return True

    def _find_retry(self, rec_id: str, attempts: int = 3, interval: float = 1.0):
        import time
        for i in range(attempts):
            r = self._find(rec_id)
            if r is not None:
                return r
            if i < attempts - 1 and interval > 0:
                time.sleep(interval)
        return None

    def _click_retry(self, rec_id: str, attempts: int = 3, interval: float = 1.0) -> bool:
        r = self._find_retry(rec_id, attempts=attempts, interval=interval)
        if r is None:
            return False
        x, y = r.bbox.center()
        self._handle.click(x, y)
        return True

    def _wait_for(self, rec_id: str, timeout: float = 10.0, interval: float = 1.0) -> bool:
        import time
        deadline = time.time() + timeout
        while True:
            if self._find(rec_id) is not None:
                return True
            if time.time() >= deadline:
                return False
            if interval > 0:
                time.sleep(min(interval, max(0.0, deadline - time.time())))

    def _wait_click(self, rec_id: str, timeout: float = 15.0, interval: float = 1.0) -> bool:
        if self._wait_for(rec_id, timeout=timeout, interval=interval):
            return self._click(rec_id)
        return False
```

同时给 `__init__` 加 `self.last_image = None`（failure 截图用，Task 7）。

删除 `leader_sm.py` 里的 `_find`/`_click` 与 `member_sm.py` 里的 `_click`（改用基类；member 的 `_click` 语义与基类一致）。

- [ ] **Step 4: 跑全部 worker 测试确认通过**

Run: `python -m pytest tests/unit/workers/ -q`
Expected: PASS（现有 leader/member 测试用 always-matched MagicMock，重试立即成功，不会变慢）

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/workers/state_machine.py src/rok_assistant/workers/leader_sm.py src/rok_assistant/workers/member_sm.py tests/unit/workers/test_state_machine.py
git commit -m "feat: shared retry/wait helpers on StateMachine base"
```

---

### Task 4: member 填兵不点预设 + 视角归一化

用户明确要求：填兵用游戏默认部队，**不点预设、不点兵种**。member 流程加入 NORMALIZE（`alliance_btn` 在地图视角底部栏）。

**Files:**
- Modify: `src/rok_assistant/workers/member_sm.py`
- Modify: `src/rok_assistant/workers/factory.py`（member 分支）
- Modify: `src/rok_assistant/workers/either_sm.py`（MemberStateMachine 构造参数）
- Test: `tests/unit/workers/test_member_sm.py`、`tests/unit/workers/test_either_sm.py`、`tests/unit/workers/test_worker_factory.py`

- [ ] **Step 1: 改写测试**（`tests/unit/workers/test_member_sm.py` 全文替换——recognizers 里**不含** preset/troop 键，旧代码会 KeyError）

```python
import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def _mock_rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec

def _make_sm():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    rec = _mock_rec()
    # 注意：没有 preset_* 和 troop_* 键——填兵不使用预设（用户要求 2026-09-09）
    recs = {k: rec for k in ("map_btn", "search_icon", "alliance_btn", "war_btn",
                             "sort_nearest", "join_btn", "march_btn")}
    sm = MemberStateMachine(handle_source=handle, recognizers=recs,
                            fill_target_leaders=[{"instance": "i1", "name": "Boss"}])
    return sm, handle

def test_member_receives_event_and_joins_without_preset():
    sm, handle = _make_sm()
    sm.on_rally_launched({"rally_id": "r1", "fortress_level": 8, "march_preset": 1})
    for _ in range(40):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    # 没有点过任何预设/兵种（若误点 preset_N 会因 KeyError 暴露；这里再断言点击次数）
    # IDLE->WAIT_LAUNCH_EVENT 无点击；SWITCH_TO_SELF 无；NORMALIZE(search_icon 已可见不点 map_btn)
    # OPEN_ALLIANCE/OPEN_WAR/SORT/JOIN/FORM(等待)/LAUNCH = 6 次点击
    assert len(handle.clicks) == 6

def test_member_form_troop_does_not_click_preset_or_troops():
    sm, handle = _make_sm()
    sm.on_rally_launched({"rally_id": "r1"})
    # 手动推进到 FORM_TROOP 之前的所有状态
    for _ in range(6):
        sm.step()
    assert sm.current == "FORM_TROOP"
    clicks_before = len(handle.clicks)
    sm.step()  # FORM_TROOP: 只等待弹窗出现（MagicMock 立即可见），不点击
    assert len(handle.clicks) == clicks_before
```

（点击次数若因实现细节差 1，以"推进后 clicks 数不再增加"的行为断言为准，修正常量注释。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/workers/test_member_sm.py -q`
Expected: FAIL（旧构造函数接受 march_preset 参数 → TypeError；或旧流程点 preset_1 → KeyError）

- [ ] **Step 3: 实现**（`member_sm.py` 全文替换）

```python
from __future__ import annotations
from .state_machine import StateMachine

class MemberStateMachine(StateMachine):
    """成员填兵。用户要求（2026-09-09）：填兵不使用预设/兵种选择，
    打开「创建部队」弹窗后直接用游戏默认部队点行军。
    """

    def __init__(self, handle_source, recognizers: dict, fill_target_leaders,
                 switcher=None):
        self._handle = handle_source
        self._rec = recognizers
        self._filter = fill_target_leaders  # §3.7 OCR 名字匹配是后续里程碑；现为加入排序后第一个集结
        self._switcher = switcher
        self._pending_event = None
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "WAIT_LAUNCH_EVENT",
                            lambda ctx: None,
                            guard=lambda ctx: self._pending_event is not None)
        self.add_transition("WAIT_LAUNCH_EVENT", "SWITCH_TO_SELF", self._switch_to_self)
        self.add_transition("SWITCH_TO_SELF", "NORMALIZE", self._normalize_view)
        self.add_transition("NORMALIZE", "OPEN_ALLIANCE", self._open_alliance)
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

    def _switch_to_self(self, ctx):
        # v1 每实例只跑第 1 个角色，无需切角色（多角色切换属 v2）
        pass

    def _normalize_view(self, ctx):
        # alliance_btn 在地图视角底部栏；城市视角左下角是 map_btn（§1.5.2）
        if self._find("search_icon"):
            return
        self._click("map_btn")
        self._wait_for("search_icon", timeout=6.0)

    def _open_alliance(self, ctx):
        self._click_retry("alliance_btn")

    def _open_war(self, ctx):
        ctx["war_attempts"] = ctx.get("war_attempts", 0) + 1
        self._click_retry("war_btn")

    def _sort_nearest(self, ctx):
        self._click_retry("sort_nearest")

    def _filter_rally(self, ctx):
        # fill_target_leaders 按名字 OCR 匹配是后续里程碑（ACCEPTANCE §3.7），
        # 当前简化为加入排序后的第一个集结。
        ctx["rally_found"] = ctx.get("war_attempts", 1) <= 10

    def _click_join(self, ctx):
        self._click_retry("join_btn")

    def _form_troop(self, ctx):
        # 只等「创建部队」弹窗出现（march_btn 可见），不点预设、不点兵种
        self._wait_for("march_btn", timeout=15.0)

    def _launch(self, ctx):
        self._click_retry("march_btn", attempts=3)

    def _switch_back(self, ctx):
        pass  # simplified

    def is_terminal(self) -> bool:
        return self.current == "END"
```

同步改 `factory.py` member 分支：

```python
    if character.role == RoleEnum.MEMBER:
        return MemberStateMachine(handle_source, recognizers,
                                  character.fill_target_leaders)
```

同步改 `either_sm.py` `__init__` 中 member 构造（去掉 march_preset/march_troop_types 两个实参）：

```python
        self._member = MemberStateMachine(handle_source, recognizers,
                                          fill_target_leaders)
```

同步改 `tests/unit/workers/test_either_sm.py` 的 `EitherStateMachine(...)` 构造（删去 `march_preset=1, march_troop_types=["infantry"]`，recognizers 集合加上 `"map_btn","search_icon","toast_no_fortress","level_minus"`；保持其余断言不变）。`tests/unit/workers/test_worker_factory.py` 中 member 分支的构造断言同步更新（读文件后按新签名改）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/workers/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/workers/member_sm.py src/rok_assistant/workers/factory.py src/rok_assistant/workers/either_sm.py tests/unit/workers/
git commit -m "feat: member fills with default troops (no preset), normalize view first"
```

---

### Task 5: leader_sm 按真实流程重写

真实流程：归一化 → 搜索 → 调等级 → 搜索 → **城寨详情弹窗** → 点 red_rally → 集结进攻弹窗（5分钟默认勾选）→ 创建部队（预设+兵种）→ 行军 → 被动等待。加无结果/被锁恢复与上限。

**Files:**
- Modify: `src/rok_assistant/workers/leader_sm.py`（全文替换）
- Test: `tests/unit/workers/test_leader_sm.py`

- [ ] **Step 1: 改写测试**（`tests/unit/workers/test_leader_sm.py` 全文替换）

```python
import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def _mock_rec(matched=True):
    rec = MagicMock()
    rec.recognize.return_value.matched = matched
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec

RECOGNIZER_IDS = ("map_btn", "search_icon", "level_plus", "level_minus",
                  "search_btn", "red_rally", "toast_no_fortress",
                  "rally_attack_popup", "preset_1", "troop_cavalry", "march_btn")

def _make_sm(target_level=7, wait=0.0):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    recs = {k: _mock_rec() for k in RECOGNIZER_IDS}
    sm = LeaderStateMachine(handle, recs, target_level=target_level,
                            march_preset=1, march_troop_types=["cavalry"],
                            event_bus=None, wait_members_seconds=wait)
    return sm, handle

def test_happy_path_reaches_end_and_publishes():
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    events = []
    bus.subscribe("rally_launched", lambda p: events.append(p))
    sm, handle = _make_sm()
    sm._bus = bus
    for _ in range(30):
        sm.step()
        if sm.is_terminal():
            break
    assert sm.current == "END"
    assert len(events) == 1
    assert events[0]["fortress_level"] == 7
    # 真实流程必须点过 red_rally（修正点：旧代码从不点它）
    assert handle.clicks.count((50, 50)) >= 9

def test_select_level_resets_with_minus_then_plus():
    sm, handle = _make_sm(target_level=3)
    sm.step()              # IDLE -> NORMALIZE
    sm.step()              # NORMALIZE -> SEARCH_FORTRESS
    sm.step()              # -> SELECT_LEVEL
    sm.step()              # -> CONFIRM_SEARCH（执行 minus*12 + plus*2 + search_btn）
    # NORMALIZE 不点（search_icon 可见）；SELECT_LEVEL 点 14 次；CONFIRM_SEARCH 1 次
    assert len(handle.clicks) == 15

def test_no_result_toast_retries_then_ends():
    sm, handle = _make_sm()
    recs = sm._rec
    # search_btn 之后的画面：red_rally 永远不出现，toast 出现
    toast = _mock_rec(matched=True)
    recs["toast_no_fortress"] = toast
    recs["red_rally"].recognize.return_value.matched = False
    steps = 0
    while not sm.is_terminal() and steps < 60:
        sm.step()
        steps += 1
    assert sm.is_terminal()
    assert sm.history.count("CHECK_RESULT") >= 3   # 重试过

def test_locked_fortress_dismisses_and_researches():
    sm, handle = _make_sm()
    recs = sm._rec
    # red_rally 可见（详情弹窗在）但 rally_attack_popup 永不出现 => 被锁
    recs["rally_attack_popup"].recognize.return_value.matched = False
    steps = 0
    while not sm.is_terminal() and steps < 120:
        sm.step()
        steps += 1
    assert sm.is_terminal()   # locked_count 达上限后 END，不死循环
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/workers/test_leader_sm.py -q`
Expected: FAIL（`wait_members_seconds` 参数不存在；状态图不同）

- [ ] **Step 3: 实现**（`leader_sm.py` 全文替换）

```python
from __future__ import annotations
import time
from .state_machine import StateMachine

_MAX_NO_RESULT = 3
_MAX_LOCKED = 5
_EMPTY_GROUND = (960, 540)   # 点空地关掉详情弹窗


class LeaderStateMachine(StateMachine):
    """车头开集结。真实 UI 流程（2026-09 实测，ACCEPTANCE §1.4/§1.5）：
    归一化视角 → 搜索 → 调等级（先减到地板再加）→ 搜索 → 城寨详情弹窗
    （red_rally 可见）→ 点红集结 → 集结进攻弹窗（5分钟默认勾选）→
    创建部队（预设槽 + 兵种）→ 行军 → 被动等成员。
    被锁 = 点红集结后 5s 内无集结进攻弹窗（§3.3）；无结果 = toast_no_fortress。
    """

    def __init__(self, handle_source, recognizers: dict, target_level: int,
                 march_preset: int, march_troop_types: list, event_bus=None,
                 wait_members_seconds: float = 330.0):
        self._handle = handle_source
        self._rec = recognizers
        self._target_level = target_level
        self._march_preset = march_preset
        self._march_troop_types = march_troop_types
        self._bus = event_bus
        self._wait_members_seconds = wait_members_seconds
        self.last_rally_event = None
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "NORMALIZE", self._normalize_view)
        self.add_transition("NORMALIZE", "SEARCH_FORTRESS", self._search_fortress)
        self.add_transition("SEARCH_FORTRESS", "SELECT_LEVEL", self._select_level)
        self.add_transition("SELECT_LEVEL", "CONFIRM_SEARCH", self._confirm_search)
        self.add_transition("CONFIRM_SEARCH", "CHECK_RESULT", self._check_result)
        self.add_transition("CHECK_RESULT", "CLICK_RED_RALLY", self._click_red_rally,
                            guard=lambda ctx: ctx.get("search_outcome") == "found")
        self.add_transition("CHECK_RESULT", "CONFIRM_SEARCH", self._retry_search,
                            guard=lambda ctx: ctx.get("search_outcome") == "no_result"
                            and ctx.get("no_result_count", 0) < _MAX_NO_RESULT)
        self.add_transition("CHECK_RESULT", "END", self._give_up,
                            guard=lambda ctx: ctx.get("search_outcome") == "no_result")
        self.add_transition("CLICK_RED_RALLY", "VERIFY_UNLOCKED", self._verify_unlocked)
        self.add_transition("VERIFY_UNLOCKED", "SELECT_RALLY_TIME", lambda ctx: None,
                            guard=lambda ctx: ctx.get("not_locked"))
        self.add_transition("VERIFY_UNLOCKED", "NORMALIZE", self._recover_locked,
                            guard=lambda ctx: not ctx.get("not_locked")
                            and ctx.get("locked_count", 0) < _MAX_LOCKED)
        self.add_transition("VERIFY_UNLOCKED", "END", self._give_up,
                            guard=lambda ctx: not ctx.get("not_locked"))
        self.add_transition("SELECT_RALLY_TIME", "FORM_TROOP", self._form_troop)
        self.add_transition("FORM_TROOP", "LAUNCH", self._launch)
        self.add_transition("LAUNCH", "WAIT_MEMBERS", self._wait_members)
        self.add_transition("WAIT_MEMBERS", "END", lambda ctx: None,
                            guard=lambda ctx: ctx.get("departed"))

    # ---- 动作 ----

    def _normalize_view(self, ctx):
        # 城市视角左下角是 map_btn、没有搜索放大镜（§1.5.2；map_btn 在地图
        # 视角不匹配 0.528，模板本身不会误点）。search_icon 可见则已在地图视角。
        if self._find("search_icon"):
            return
        self._click("map_btn")
        self._wait_for("search_icon", timeout=6.0)

    def _search_fortress(self, ctx):
        if not self._click_retry("search_icon", attempts=3):
            raise RuntimeError("search_icon 不可见且 map_btn 归一化失败")

    def _select_level(self, ctx):
        # 搜索面板记住上次等级（实测显示 8），先减到 1 级地板再加到目标
        for _ in range(12):
            self._click("level_minus")
        for _ in range(max(0, self._target_level - 1)):
            self._click("level_plus")

    def _confirm_search(self, ctx):
        self._click_retry("search_btn")

    def _check_result(self, ctx):
        ctx.setdefault("no_result_count", 0)
        ctx.setdefault("locked_count", 0)
        if self._wait_for("red_rally", timeout=8.0):
            ctx["search_outcome"] = "found"
            return
        # 无详情弹窗：toast 出现=无结果；无 toast 也按无结果处理（可能加载慢）
        self._find("toast_no_fortress")
        ctx["search_outcome"] = "no_result"
        ctx["no_result_count"] = ctx["no_result_count"] + 1

    def _retry_search(self, ctx):
        # 搜索面板仍开着（toast 不关面板），直接再搜
        self._click_retry("search_btn")

    def _click_red_rally(self, ctx):
        self._click_retry("red_rally")

    def _verify_unlocked(self, ctx):
        # 被锁 = 点红集结后 5s 内无集结进攻弹窗（§3.3）；⭐ 书签与锁定无关
        ctx["not_locked"] = self._wait_for("rally_attack_popup", timeout=5.0)
        if not ctx["not_locked"]:
            ctx["locked_count"] = ctx.get("locked_count", 0) + 1

    def _recover_locked(self, ctx):
        # 点空地关详情弹窗，回到 NORMALIZE 重新搜
        self._handle.click(*_EMPTY_GROUND)

    def _give_up(self, ctx):
        # 连续无结果/被锁达上限：本轮结束，WorkerRunner 冷却后重建 SM 重来
        self.last_rally_event = None

    def _form_troop(self, ctx):
        if not self._wait_for("march_btn", timeout=15.0):
            raise RuntimeError("创建部队弹窗未出现（march_btn 不可见）")
        self._click(f"preset_{self._march_preset}")
        for t in self._march_troop_types:
            self._click(f"troop_{t}")

    def _launch(self, ctx):
        if not self._click_retry("march_btn", attempts=3):
            raise RuntimeError("march_btn 点击失败，集结未发起")
        self.last_rally_event = {
            "rally_id": f"rally_{int(time.time())}",
            "fortress_level": self._target_level,
            "march_preset": self._march_preset,
        }
        if self._bus:
            self._bus.publish("rally_launched", self.last_rally_event)

    def _wait_members(self, ctx):
        # 被动等待：成员填满或准备倒计时结束游戏自动出发（默认5分钟+缓冲）。
        # either 角色（即刻去填别人的集结）传 wait_members_seconds=0。
        deadline = time.time() + self._wait_members_seconds
        while time.time() < deadline:
            time.sleep(min(10.0, deadline - time.time()))
        ctx["departed"] = True

    def is_terminal(self) -> bool:
        return self.current == "END"
```

- [ ] **Step 4: 跑 worker 测试（含 either_sm）确认通过**

Run: `python -m pytest tests/unit/workers/ -q`
Expected: PASS。若 `test_either_sm.py` 因 leader 新签名失败：`EitherStateMachine.__init__` 里构造 LeaderStateMachine 时传 `wait_members_seconds=0.0`（either 开完寨**不等满、即刻**转 member 填兵——用户原话）。

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/workers/leader_sm.py src/rok_assistant/workers/either_sm.py tests/unit/workers/
git commit -m "feat: leader SM matches real UI flow (red_rally, normalize, toast/locked recovery)"
```

---

### Task 6: switcher_sm 按 5 步实测重写

**Files:**
- Modify: `src/rok_assistant/workers/switcher_sm.py`（全文替换）
- Test: `tests/unit/workers/test_switcher_sm.py`

- [ ] **Step 1: 改写测试**（全文替换；v1 每实例 1 角色不用切角色，此重写为 v2 铺路，按 mock 测试）

```python
import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.switcher_sm import SwitcherStateMachine
from rok_assistant.core.handle_source import MockHandleSource

def _mock_rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec

def _make_sm(recognizers=None, load_wait=0.0):
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    sm = SwitcherStateMachine(handle_source=handle, target_character="Boss",
                              recognizers=recognizers or {},
                              avatar_key="char_avatar_boss",
                              verify_key="avatar_self_boss",
                              load_wait_seconds=load_wait)
    return sm, handle

def test_walks_5_steps_with_confirm_and_relogin():
    recs = {k: _mock_rec() for k in ("settings_btn", "char_mgmt_btn",
                                     "char_avatar_boss", "switch_confirm_yes",
                                     "click_to_enter", "avatar_self_boss")}
    sm, handle = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.current == "DONE"
    assert not sm.ctx.get("switch_failed")
    # 头像(固定坐标) + 设置 + 角色管理 + 目标角色 + 确认 + 进入游戏 = 6 次点击
    assert len(handle.clicks) == 6

def test_verify_skipped_when_no_template():
    recs = {k: _mock_rec() for k in ("settings_btn", "char_mgmt_btn",
                                     "char_avatar_boss", "switch_confirm_yes",
                                     "click_to_enter")}
    sm, _ = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.current == "DONE"
    assert sm.ctx.get("verify_skipped") is True   # §1.5.3：无头像模板跳过校验

def test_no_avatar_template_flags_failure():
    recs = {k: _mock_rec() for k in ("settings_btn", "char_mgmt_btn",
                                     "switch_confirm_yes", "click_to_enter")}
    sm, _ = _make_sm(recognizers=recs)
    sm.run_until_done()
    assert sm.ctx.get("switch_failed") is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/workers/test_switcher_sm.py -q`
Expected: FAIL（新参数 avatar_key/verify_key/load_wait_seconds 不存在）

- [ ] **Step 3: 实现**（全文替换）

```python
from __future__ import annotations
import time
from .state_machine import StateMachine

AVATAR_CLICK = (75, 60)        # 主界面左上角头像，位置固定（§1.5.3 左上角无角色名）


class SwitcherStateMachine(StateMachine):
    """切角色 5 步 + 确认 + 重登（ACCEPTANCE §1.5.1 实测）：
    头像 → 设置 → 角色管理 → 点目标角色头像 → 「角色登入」确认框点「是」
    → 完整重登（点击进入游戏 → 加载约 20-25s）→ 头像校验。
    """

    def __init__(self, handle_source, target_character: str, recognizers: dict,
                 ocr=None, avatar_key: str = "", verify_key: str = "",
                 load_wait_seconds: float = 25.0):
        self._handle = handle_source
        self._target = target_character
        self._recognizers = recognizers
        self._ocr = ocr  # 未用：OCR 名字校验方案已废弃（§1.5.3），保留参数避免破坏签名
        self._avatar_key = avatar_key
        self._verify_key = verify_key
        self._load_wait = load_wait_seconds
        self.ctx: dict = {}
        super().__init__(initial="IDLE")

    def _setup(self):
        self.add_transition("IDLE", "OPEN_PROFILE", self._open_profile)
        self.add_transition("OPEN_PROFILE", "OPEN_SETTINGS", self._open_settings)
        self.add_transition("OPEN_SETTINGS", "OPEN_CHAR_MGMT", self._open_char_mgmt)
        self.add_transition("OPEN_CHAR_MGMT", "PICK_CHAR", self._pick_char)
        self.add_transition("PICK_CHAR", "CONFIRM_SWITCH", self._confirm_switch)
        self.add_transition("CONFIRM_SWITCH", "RELOGIN", self._relogin)
        self.add_transition("RELOGIN", "WAIT_LOAD", self._wait_load)
        self.add_transition("WAIT_LOAD", "VERIFY", self._verify)
        self.add_transition("VERIFY", "DONE", lambda ctx: None,
                            guard=lambda c: c.get("verified", False))
        self.add_transition("VERIFY", "OPEN_PROFILE", self._retry,
                            guard=lambda c: not c.get("verified", False)
                            and c.get("retries", 0) < 2)
        self.add_transition("VERIFY", "DONE", self._flag_failed,
                            guard=lambda c: not c.get("verified", False))

    # step() 用 self._ctx；这里把 self.ctx 与基类 context 合并（保持 run_until_done 简单）
    def step(self, context: dict | None = None) -> None:
        context = context if context is not None else self.ctx
        self.ctx = context
        super().step(context)

    def _open_profile(self, ctx):
        self._handle.click(*AVATAR_CLICK)

    def _open_settings(self, ctx):
        if not self._click_retry("settings_btn", attempts=3):
            raise RuntimeError("settings_btn 未找到，切角色中止")

    def _open_char_mgmt(self, ctx):
        if not self._click_retry("char_mgmt_btn", attempts=3):
            raise RuntimeError("char_mgmt_btn 未找到，切角色中止")

    def _pick_char(self, ctx):
        if self._avatar_key and self._avatar_key in self._recognizers:
            self._click_retry(self._avatar_key, attempts=3)
        else:
            ctx["switch_failed"] = True   # 没有目标角色头像模板，无法点选

    def _confirm_switch(self, ctx):
        # 「角色登入」确认框（§1.5.1 第 5 步）
        self._wait_click("switch_confirm_yes", timeout=10.0)

    def _relogin(self, ctx):
        # 完整重登：登录页「点击进入游戏」；等待窗口要够长（游戏可能重启）
        self._wait_click("click_to_enter", timeout=60.0)

    def _wait_load(self, ctx):
        time.sleep(self._load_wait)   # 重登加载 20-25s（测试传 0）

    def _verify(self, ctx):
        ctx["retries"] = ctx.get("retries", 0) + 1
        if not self._verify_key or self._verify_key not in self._recognizers:
            ctx["verified"] = True
            ctx["verify_skipped"] = True   # §1.5.3：无头像模板，跳过校验
            return
        ctx["verified"] = self._find_retry(self._verify_key, attempts=3, interval=2.0) is not None

    def _retry(self, ctx):
        pass  # 回 OPEN_PROFILE 整个流程重走

    def _flag_failed(self, ctx):
        ctx["switch_failed"] = True

    def is_done(self) -> bool:
        return self.current == "DONE"

    def run_until_done(self) -> None:
        for _ in range(40):
            self.step()
            if self.is_done():
                return
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/workers/test_switcher_sm.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/workers/switcher_sm.py tests/unit/workers/test_switcher_sm.py
git commit -m "feat: switcher SM = 5-step + confirm + relogin + optional avatar verify"
```

---

### Task 7: WorkerRunner（每角色一个线程）

**Files:**
- Create: `src/rok_assistant/workers/runner.py`
- Test: `tests/unit/workers/test_runner.py`

- [ ] **Step 1: 写失败测试**

```python
import time
import numpy as np
from unittest.mock import MagicMock
from rok_assistant.workers.runner import WorkerRunner
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.coordination.event_bus import EventBus


def _mock_rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec


def _member_factory(recognizers=None):
    def build():
        handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
        recs = {k: recognizers or _mock_rec() for k in (
            "map_btn", "search_icon", "alliance_btn", "war_btn", "sort_nearest",
            "join_btn", "march_btn")}
        return MemberStateMachine(handle, recs, [{"instance": "i1", "name": "B"}])
    return build


def test_runner_drives_member_to_end_and_publishes_status():
    bus = EventBus()
    statuses = []
    bus.subscribe("status_update", lambda p: statuses.append(p))
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="成员甲",
                     sm_factory=_member_factory(), handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=bus, poll_interval=0.01, restart_cooldown=0.05)
    r.sm.on_rally_launched({"rally_id": "r1"})
    r.start()
    deadline = time.time() + 5
    while time.time() < deadline and not r.is_terminal_once():
        time.sleep(0.02)
    r.stop()
    states = [s["state"] for s in statuses]
    assert any(s == "END" for s in states)
    assert statuses[0]["instance_id"] == "i1"
    assert statuses[0]["char_id"] == "c1"


def test_runner_pauses_when_handle_dies():
    handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    handle.set_alive(False)
    bus = EventBus()
    statuses = []
    bus.subscribe("status_update", lambda p: statuses.append(p))
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(), handle_source=handle,
                     event_bus=bus, poll_interval=0.01, restart_cooldown=0.05)
    r.start()
    time.sleep(0.3)
    r.stop()
    assert any(s["state"] == "paused" for s in statuses)


def test_runner_survives_sm_exception_and_saves_screenshot(tmp_path):
    import cv2
    bad = _mock_rec()
    bad.recognize.side_effect = RuntimeError("boom")
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(recognizers=bad),
                     handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=None, poll_interval=0.01, restart_cooldown=0.05,
                     screenshot_dir=tmp_path)
    r.start()
    time.sleep(0.4)
    r.stop()
    shots = list(tmp_path.glob("failure_*.png"))
    assert shots, "异常时应保存失败截图"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/workers/test_runner.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'rok_assistant.workers.runner'`

- [ ] **Step 3: 实现**（新建 `src/rok_assistant/workers/runner.py`）

```python
from __future__ import annotations
import threading
import time
from datetime import datetime
from pathlib import Path

from ..infra.logger import get_logger

logger = get_logger(__name__)


class WorkerRunner:
    """每个角色一个线程：循环 step 状态机、发布状态、异常截图、终态冷却重建。

    状态发布走 EventBus 的 "status_update"：
    payload = {"instance_id", "char_id", "char_name", "state", "ts"}（仅在变化时发布）
    """

    def __init__(self, instance_id: str, char_id: str, char_name: str,
                 sm_factory, handle_source, event_bus=None,
                 poll_interval: float = 2.0, restart_cooldown: float = 30.0,
                 screenshot_dir: Path | None = None):
        self.instance_id = instance_id
        self.char_id = char_id
        self.char_name = char_name
        self._sm_factory = sm_factory
        self.sm = sm_factory()
        self._handle = handle_source
        self._bus = event_bus
        self._poll = poll_interval
        self._cooldown = restart_cooldown
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else Path("recordings")
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "idle"
        self._reached_terminal = False

    # ---- 生命周期 ----
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"worker:{self.instance_id}:{self.char_id}")
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ---- 查询 ----
    @property
    def status(self) -> str:
        return self._status

    @property
    def last_frame(self):
        img = getattr(self.sm, "last_image", None)
        return None if img is None else img

    def is_terminal_once(self) -> bool:
        return self._reached_terminal

    # ---- 主循环 ----
    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self._handle.is_alive():
                    self._set_status("paused")   # §3.5：窗口消失 → 暂停
                    self._stop_event.wait(5.0)
                    continue
                if self.sm.is_terminal():
                    self._reached_terminal = True
                    self._set_status("cooldown")
                    self._stop_event.wait(self._cooldown)
                    if self._stop_event.is_set():
                        break
                    self.sm = self._sm_factory()   # 冷却后重建，进入下一轮
                    self._set_status(self.sm.current)
                    continue
                self.sm.step()
                self._set_status(self.sm.current)
            except Exception as e:   # 任何异常：截图 + 记录 + 稍后继续（不杀线程）
                logger.exception("worker %s/%s step failed: %s",
                                 self.instance_id, self.char_id, e)
                self._save_failure_screenshot()
                self._set_status("error")
                self._stop_event.wait(10.0)
            self._stop_event.wait(self._poll)

    def _set_status(self, state: str) -> None:
        if state == self._status:
            return
        self._status = state
        logger.info("worker %s/%s -> %s", self.instance_id, self.char_id, state)
        if self._bus:
            self._bus.publish("status_update", {
                "instance_id": self.instance_id, "char_id": self.char_id,
                "char_name": self.char_name, "state": state,
                "ts": datetime.now().isoformat(timespec="seconds"),
            })

    def _save_failure_screenshot(self) -> None:
        img = self.last_frame
        if img is None:
            return
        try:
            import cv2
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)
            name = f"failure_{self.instance_id}_{self.char_id}_{datetime.now():%Y%m%d_%H%M%S}.png"
            cv2.imwrite(str(self._screenshot_dir / name), img)
        except Exception:
            logger.exception("保存失败截图出错")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/workers/test_runner.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/workers/runner.py tests/unit/workers/test_runner.py
git commit -m "feat: WorkerRunner thread per character (status, pause, failure screenshots, restart)"
```

---

### Task 8: RuntimeCoordinator + GuiController(QObject) + MainWindow 接线

**Files:**
- Create: `src/rok_assistant/coordination/runtime.py`
- Modify: `src/rok_assistant/gui/controller.py`（全文替换）
- Modify: `src/rok_assistant/gui/main_window.py`（全文替换）
- Test: `tests/integration/test_controller.py`（全文替换）、`tests/integration/test_runtime.py`（新建）、`tests/integration/test_gui_smoke.py`（追加）

- [ ] **Step 1: 写失败测试**（`tests/integration/test_runtime.py` 新建）

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import numpy as np
import yaml
from unittest.mock import MagicMock, patch

from rok_assistant.coordination.runtime import RuntimeCoordinator
from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.infra.config import load_config


VALID = """
app:
  mumu_manager_path: ""
  adb_path: "adb"
instances:
  - id: inst0
    name: a
    adb_address: "127.0.0.1:5555"
    characters:
      - id: boss
        name: 车头
        role: leader
        target_level: 7
        march_preset: 1
        march_troop_types: [cavalry]
  - id: inst1
    name: b
    adb_address: "127.0.0.1:5556"
    characters:
      - id: worker
        name: 成员
        role: member
        target_level: 7
        march_preset: 1
        march_troop_types: [cavalry]
        fill_target_leaders:
          - { instance: inst0, name: 车头 }
"""

def _write_config(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(VALID, encoding="utf-8")
    return load_config(p)

def test_coordinator_builds_one_runner_per_first_character(tmp_path):
    cfg = _write_config(tmp_path)
    bus = EventBus()
    fake_handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    with patch("rok_assistant.coordination.runtime.create_handle_source",
               return_value=fake_handle):
        coord = RuntimeCoordinator(cfg, event_bus=bus, template_dir=None)
        coord.start()
        try:
            assert set(coord.runners) == {"inst0:boss", "inst1:worker"}
        finally:
            coord.stop()

def test_coordinator_routes_rally_to_member_runner(tmp_path):
    cfg = _write_config(tmp_path)
    bus = EventBus()
    fake_handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    with patch("rok_assistant.coordination.runtime.create_handle_source",
               return_value=fake_handle):
        coord = RuntimeCoordinator(cfg, event_bus=bus, template_dir=None)
        coord.start()
        try:
            member_sm = coord.runners["inst1:worker"].sm
            bus.publish("rally_launched", {"rally_id": "r9"})
            assert member_sm._pending_event == {"rally_id": "r9"}
        finally:
            coord.stop()
```

`tests/integration/test_controller.py` 全文替换：

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pytest
from rok_assistant.gui.controller import GuiController


class FakeCoordinator:
    def __init__(self, *a, **kw):
        self.started = False
        self.stopped = False
    def start(self): self.started = True
    def stop(self): self.stopped = True
    def snapshot(self, char_id): return None


@pytest.fixture
def controller(qapp, tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
app: {}
instances:
  - id: inst0
    name: a
    adb_address: "127.0.0.1:5555"
    characters:
      - id: boss
        name: 车头
        role: leader
        target_level: 7
        march_preset: 1
        march_troop_types: [cavalry]
""", encoding="utf-8")
    monkeypatch.setattr("rok_assistant.gui.controller.RuntimeCoordinator",
                        FakeCoordinator)
    c = GuiController(config_path=cfg)
    yield c

def test_lists_characters(controller):
    chars = controller.characters()
    assert [(c["instance_id"], c["char_id"], c["role"]) for c in chars] == [
        ("inst0", "boss", "leader")]

def test_start_stop_uses_coordinator(controller):
    controller.start()
    assert controller._coordinator.started
    controller.stop()
    assert controller._coordinator.stopped

def test_status_signal_from_bus(controller, qapp):
    received = []
    controller.status_changed.connect(lambda p: received.append(p))
    controller._on_bus_status({"instance_id": "inst0", "char_id": "boss",
                               "char_name": "车头", "state": "SEARCH_FORTRESS"})
    assert received and received[0]["state"] == "SEARCH_FORTRESS"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/integration/test_runtime.py tests/integration/test_controller.py -q`
Expected: FAIL，`ModuleNotFoundError: ... runtime` / controller 签名不符

- [ ] **Step 3: 实现**（新建 `src/rok_assistant/coordination/runtime.py`）

```python
from __future__ import annotations
import cv2
from pathlib import Path

from ..core.template_registry import TemplateRegistry
from ..core.handle_source import create_handle_source
from ..infra.config import RootConfig, RoleEnum
from ..infra.anti_detection import JitteringHandleSource
from ..workers.factory import create_state_machine
from ..workers.runner import WorkerRunner
from ..workers.switcher_sm import SwitcherStateMachine
from .event_bus import EventBus


class RuntimeCoordinator:
    """从 RootConfig 组装运行时：每实例 1 个 HandleSource（防检测包装），
    每实例第 1 个角色 1 个 WorkerRunner。member 角色订阅 rally_launched。

    v1 限制：每实例只跑第 1 个角色（多角色切换属 v2）。
    """

    def __init__(self, config: RootConfig, event_bus: EventBus | None = None,
                 template_dir: Path | None = None):
        self._config = config
        self._bus = event_bus or EventBus()
        self._template_dir = Path(template_dir) if template_dir else Path("templates")
        self.runners: dict[str, WorkerRunner] = {}
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        recognizers = TemplateRegistry.load(
            self._template_dir / "manifest.yaml").build_recognizers()
        for inst in self._config.instances:
            handle = create_handle_source(
                mumu_index=inst.mumu_index,
                mumu_manager_path=self._config.app.mumu_manager_path,
                adb_address=inst.adb_address,
                adb_path=self._config.app.adb_path,
                window_title_pattern=inst.window_title_pattern)
            handle = JitteringHandleSource(handle, self._config.app.anti_detection)
            for char in inst.characters[:1]:
                self._spawn(inst, char, handle, recognizers)
        self._running = True

    def _spawn(self, inst, char, handle, recognizers) -> None:
        sm_factory = self._sm_factory_for(char, handle, recognizers)
        runner = WorkerRunner(
            instance_id=inst.id, char_id=char.id, char_name=char.name,
            sm_factory=sm_factory, handle_source=handle, event_bus=self._bus)
        self.runners[f"{inst.id}:{char.id}"] = runner
        if char.role == RoleEnum.MEMBER:
            self._bus.subscribe("rally_launched", self._make_router(f"{inst.id}:{char.id}"))
        runner.start()

    def _sm_factory_for(self, char, handle, recognizers):
        if char.role == RoleEnum.MEMBER:
            return lambda: create_state_machine(char, handle, recognizers, self._bus)
        return lambda: create_state_machine(char, handle, recognizers, self._bus)

    def _make_router(self, runner_key: str):
        def route(event: dict) -> None:
            runner = self.runners.get(runner_key)
            if runner is None:
                return
            sm = runner.sm
            # 冷却重建后的新 SM 从 IDLE 等事件；已在跑的（非等待态）不吃新事件
            if sm.current in ("IDLE", "WAIT_LAUNCH_EVENT"):
                sm.on_rally_launched(event)
        return route

    def stop(self) -> None:
        for runner in self.runners.values():
            runner.stop()
        self.runners.clear()
        self._running = False

    def snapshot(self, char_id: str) -> bytes | None:
        """该角色最近一帧的 JPEG bytes（GUI 缩略图用），无则 None。"""
        for runner in self.runners.values():
            if runner.char_id == char_id:
                img = runner.last_frame
                if img is None:
                    return None
                ok, buf = cv2.imencode(".jpg", img)
                return bytes(buf) if ok else None
        return None
```

（注意：`_sm_factory_for` 两个分支相同是刻意的——member 的 SM 由工厂每次新建，路由经 `route` 拿 runner 当前 SM；`SwitcherStateMachine` 导入暂未用到就删掉该行 import。）

`src/rok_assistant/gui/controller.py` 全文替换：

```python
from __future__ import annotations
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
import yaml

from ..coordination.event_bus import EventBus
from ..coordination.runtime import RuntimeCoordinator
from ..infra.config import RootConfig
from ..infra.logger import get_logger

logger = get_logger(__name__)


class GuiController(QObject):
    """GUI 与运行时之间的桥。worker 线程经 EventBus 发布状态，
    这里转成 Qt 信号（跨线程安全，Qt 自动排队到主线程）。"""

    status_changed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, config_path: Path | None = None,
                 coordinator_factory=RuntimeCoordinator, parent=None):
        super().__init__(parent)
        self.config_path = Path(config_path) if config_path else Path("config.yaml")
        self._coordinator_factory = coordinator_factory
        self._coordinator = None
        self._config: RootConfig | None = None
        self._bus = EventBus()
        self._bus.subscribe("status_update", self._on_bus_status)

    # ---- 配置 ----
    @property
    def config_loaded(self) -> bool:
        return self._config is not None

    def load_config(self) -> bool:
        try:
            self._config = RootConfig.model_validate(
                yaml.safe_load(self.config_path.read_text(encoding="utf-8")))
            return True
        except Exception as e:
            logger.exception("配置加载失败")
            self.error_occurred.emit(f"配置加载失败：{e}")
            return False

    def characters(self) -> list[dict]:
        if self._config is None:
            self.load_config()
        out = []
        if self._config:
            for inst in self._config.instances:
                for char in inst.characters:
                    out.append({"instance_id": inst.id, "char_id": char.id,
                                "char_name": char.name, "role": char.role.value})
        return out

    # ---- 运行 ----
    def start(self) -> None:
        if self._config is None and not self.load_config():
            return
        try:
            self._coordinator = self._coordinator_factory(self._config, event_bus=self._bus)
            self._coordinator.start()
        except Exception as e:
            logger.exception("启动失败")
            self.error_occurred.emit(f"启动失败：{e}")

    def stop(self) -> None:
        if self._coordinator is not None:
            self._coordinator.stop()
            self._coordinator = None

    def snapshot(self, char_id: str) -> bytes | None:
        return self._coordinator.snapshot(char_id) if self._coordinator else None

    # ---- 内部 ----
    def _on_bus_status(self, payload: dict) -> None:
        self.status_changed.emit(payload)   # worker 线程 emit -> Qt 排队到主线程
```

`src/rok_assistant/gui/main_window.py` 全文替换：

```python
from __future__ import annotations
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QScrollArea, QStatusBar, QMessageBox
)
from PyQt6.QtCore import QTimer

from .character_card import CharacterCard
from .controller import GuiController


class MainWindow(QMainWindow):
    def __init__(self, controller: GuiController | None = None):
        super().__init__()
        self.setWindowTitle("rok-assistant")
        self.resize(1200, 800)
        self._controller = controller or GuiController(config_path=Path("config.yaml"))
        self._cards: dict[str, CharacterCard] = {}
        self._build_ui()
        self._build_cards()
        self._setup_refresh_timer()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        top = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["rally"])
        self.refresh_btn = QPushButton("刷新配置")
        self.config_btn = QPushButton("⚙ 配置")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        self.refresh_btn.clicked.connect(self._rebuild_cards)
        self.config_btn.clicked.connect(self._open_config)
        for w in (self.start_btn, self.stop_btn, QLabel("Mode:"),
                  self.mode_combo, self.refresh_btn, self.config_btn):
            top.addWidget(w)
        root.addLayout(top)
        self.account_area = QScrollArea()
        self.account_widget = QWidget()
        self.account_layout = QVBoxLayout(self.account_widget)
        self.account_area.setWidget(self.account_widget)
        root.addWidget(self.account_area)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")
        self._controller.status_changed.connect(self._on_status)
        self._controller.error_occurred.connect(self._on_error)

    def _build_cards(self):
        chars = self._controller.characters()
        self._cards.clear()
        for c in chars:
            card = CharacterCard(c["char_name"], c["role"])
            self._cards[c["char_id"]] = card
            self.account_layout.addWidget(card)

    def _rebuild_cards(self):
        for card in self._cards.values():
            self.account_layout.removeWidget(card)
            card.deleteLater()
        self._build_cards()

    def _setup_refresh_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._on_refresh)
        self._timer.start()

    def _on_refresh(self):
        for char_id, card in self._cards.items():
            data = self._controller.snapshot(char_id)
            if data:
                card.set_thumbnail(data)

    def _on_status(self, payload: dict):
        card = self._cards.get(payload["char_id"])
        if card:
            card.set_status(payload["state"])

    def _on_error(self, message: str):
        QMessageBox.critical(self, "运行时错误", message)

    def _on_start(self):
        if not self._controller.config_loaded and not self._controller.load_config():
            return
        self._controller.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.statusBar().showMessage("运行中")

    def _on_stop(self):
        self._controller.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.statusBar().showMessage("已停止")

    def _open_config(self):
        from .config_dialog import ConfigDialog
        if not self.config_path_exists():
            QMessageBox.warning(self, "配置", "未找到 config.yaml（请先在项目根目录准备）")
            return
        dlg = ConfigDialog(self.config_path, self)
        dlg.exec()

    def config_path_exists(self) -> bool:
        return Path("config.yaml").exists()


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

注意 `ConfigDialog(path, parent)` 的实际签名以 `gui/config_dialog.py` 为准（读文件确认，若为 `ConfigDialog(path, parent=None)` 则如上；否则按实际改）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/integration/ -q`
Expected: PASS（test_gui_smoke 的 MainWindow() 默认构造会用 GuiController——不再弹错；controller 构造不 load_config 不触 adb）

- [ ] **Step 5: Commit**

```bash
git add src/rok_assistant/coordination/runtime.py src/rok_assistant/gui/controller.py src/rok_assistant/gui/main_window.py tests/integration/
git commit -m "feat: RuntimeCoordinator + QObject controller + live GUI start/stop"
```

---

### Task 9: 端到端集成测试 + 文档收尾

**Files:**
- Test: `tests/integration/test_end_to_end.py`（新建）
- Modify: `docs/ACCEPTANCE.md`

- [ ] **Step 1: 写端到端测试**（mock 屏幕驱动的完整链路：leader 发布集结 → 路由到 member → member 填完到 END → 冷却重建回 IDLE）

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import numpy as np
from unittest.mock import MagicMock

from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.workers.runner import WorkerRunner
from rok_assistant.workers.leader_sm import LeaderStateMachine
from rok_assistant.workers.member_sm import MemberStateMachine
from rok_assistant.core.handle_source import MockHandleSource


def _rec():
    rec = MagicMock()
    rec.recognize.return_value.matched = True
    rec.recognize.return_value.bbox = MagicMock(center=lambda: (50, 50))
    rec.recognize.return_value.confidence = 0.95
    return rec

LEADER_IDS = ("map_btn", "search_icon", "level_plus", "level_minus", "search_btn",
              "red_rally", "toast_no_fortress", "rally_attack_popup",
              "preset_1", "troop_cavalry", "march_btn")
MEMBER_IDS = ("map_btn", "search_icon", "alliance_btn", "war_btn",
              "sort_nearest", "join_btn", "march_btn")

def test_leader_launches_member_fills_and_runner_rebuilds():
    bus = EventBus()
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    handle = MockHandleSource(screenshot=img)

    def leader_factory():
        return LeaderStateMachine(handle, {k: _rec() for k in LEADER_IDS},
                                  target_level=7, march_preset=1,
                                  march_troop_types=["cavalry"], event_bus=bus,
                                  wait_members_seconds=0.0)

    def member_factory():
        return MemberStateMachine(handle, {k: _rec() for k in MEMBER_IDS},
                                  [{"instance": "i0", "name": "车头"}])

    leader = WorkerRunner("i0", "boss", "车头", leader_factory, handle, bus,
                          poll_interval=0.01, restart_cooldown=0.1)
    member = WorkerRunner("i1", "sub", "成员", member_factory, handle, bus,
                          poll_interval=0.01, restart_cooldown=0.1)
    leader.start()
    member.start()
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            if (member.sm.current == "END" and leader.sm.current == "IDLE"
                    and leader.is_terminal_once()):
                break
            time.sleep(0.05)
        # member 收到 leader 的集结事件并走完填兵
        assert member.sm.current == "END"
        # leader 冷却后重建，回到 IDLE 准备下一轮
        # （终态是 END，不可能自己变回 IDLE——变回 IDLE 即证明 sm 被重建为新实例）
        assert leader.sm.current == "IDLE"
        assert leader.is_terminal_once()
    finally:
        leader.stop()
        member.stop()
```

（最后那行 `is not leader_factory` 写法不对——直接删掉它，保留 `leader.is_terminal_once()` 断言即可；重建正确性由 `leader.sm.current == "IDLE"` 证明，因为终态是 END 不可能自己变回 IDLE。）

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/integration/test_end_to_end.py -q`
Expected: PASS

- [ ] **Step 3: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS（142 基线 + 本计划新增）

- [ ] **Step 4: 更新 docs/ACCEPTANCE.md**

在「当前状态」表加一行：

```markdown
| 运行时接线 | ✅（2026-09-10） | WorkerRunner/RuntimeCoordinator/GuiController 已接线，GUI Start/Stop 可用；member 填兵不点预设；leader 流程含 red_rally/归一化/toast/被锁恢复 |
```

并把 §3 开头的说明改为：8 项验收现在可以真实执行（先 `python -m rok_assistant.gui.main_window` → Start）。§1.5 中已落代码的修正项（1/2/4/6）标注 ✅ 已实现。

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_end_to_end.py docs/ACCEPTANCE.md
git commit -m "test: end-to-end leader->member flow; docs: runtime wiring complete"
```

---

## 已知风险与后续里程碑（不在本计划）

- **填兵目标匹配**：member 加入排序后第一个集结，可能搜到自己（either 角色）的集结——按名字 OCR 匹配（§3.7）是下一个里程碑。
- **每实例多角色**：v1 只跑每实例第 1 个角色；switcher 已具备但无人调用（v2 接线）。
- **rally_completed 事件**：无人生成（需要识别集结完成画面），WAIT_MEMBERS 用固定等待代替。
- **真实屏幕联调**：本计划全部用 mock 测试；首次真实 Start 的模板阈值/等待时长大概率要现场微调（`tools/verify.py` + `_capture_driver.py` 还留着，用完再删）。
