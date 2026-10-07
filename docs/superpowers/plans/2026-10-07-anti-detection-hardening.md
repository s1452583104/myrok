# 防检测加固与运维闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把等级调整从「固定 12 连点降底再升」改成「读面板实际等级 → 点差量 → 回读校验」，并补齐连点节奏、轮数界面配置 + 跑完自动复位、启动连接预检。

**Architecture:** 新增一个「文本字段」识别族（固定 ROI + RapidOCR + 整块正则），与既有的 `templates:` / `pixel_stats:` 并列挂在 manifest 顶层；`LeaderStateMachine._select_level` 改为回读驱动，读不出时**逐字退回**改动前的盲降路径（缓存保留、只服务该路径）。连点节奏作为 `AntiDetectionConfig` 的独立旋钮，经 `HandleSource.click(rapid=True)` 下传。轮数与预检分别落在 GUI 配置对话框与 `RuntimeCoordinator.start()` 的前置检查。

**Tech Stack:** Python 3.14 / PyQt6 / pydantic v2 / RapidOCR(onnxruntime) / pytest。测试一律用假件，不碰真模拟器。

**Spec:** `docs/superpowers/specs/2026-10-07-anti-detection-hardening-design.md`

## Global Constraints

- **必须用 `.venv/Scripts/python.exe`**，不要用系统 `python`（那是 torch+cpu，会静默降级跑 CPU）。
- 跑 `tools/*.py` 的中文输出要加 `-X utf8`（控制台是 GBK，含 `✓` 会 UnicodeEncodeError）。
- **bash 双引号里不要出现反引号**——会被当命令替换执行；写文件用 `<<'EOF'` 单引号定界符。
- 测试默认**只跑相关子集**；收尾（Task 7）跑一次全量 `pytest tests/ -q`。
- `.pytest_tmp` 是 repo 内固定 basetemp：**看到批量 setup 阶段 `E` 先查它**——杀光孤儿 `python.exe` → `rm -rf .pytest_tmp` → 重跑（PROGRESS 已知问题 7）。
- **文档只记字段作用，不记取值**（哪个角色配了几级/什么预设/兵种一律不写进 docs，要看值直接读 `config.yaml`）。
- 删任何图片/模板/标注前先确认没有引用（用户明确要求过：千万不要把在用的清理掉）。
- 本计划**不含实机步骤**；凡需实机确认的，写进 `docs/PROGRESS.md` 的待办，不在此假装已验证。
- 反检测取向：**消除机器签名**（可变的步数与节奏），不做坐标缓存、不全局提速。

---

### Task 1: `TextFieldRecognizer` — 按 ROI + 整块正则读一个文本字段

**Files:**
- Create: `src/rok_assistant/core/recognizers/text_field.py`
- Test: `tests/unit/core/recognizers/test_text_field.py`

**Interfaces:**
- Consumes: `core/recognizer.py` 的 `BBox(x1,y1,x2,y2)` / `RecognizeResult(matched, bbox, confidence, data, recognizer_id)`；OCR 引擎接口 `detect_text(img) -> list[(BBox, str, float)]`（见 `core/recognizers/ocr_text.py:25`）。
- Produces: `TextFieldRecognizer(field_id: str, roi: BBox, pattern: str, engine, name: str | None = None)`，其 `.recognize(screenshot) -> RecognizeResult`；命中时 `data == {"text": 原文, "value": 捕获组}`，`bbox` 为**加回 ROI 偏移的绝对坐标**。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/core/recognizers/test_text_field.py
import numpy as np

from rok_assistant.core.recognizer import BBox
from rok_assistant.core.recognizers.text_field import TextFieldRecognizer

ROI = BBox(100, 470, 1040, 620)
PATTERN = r"^等级\s*[：:]\s*(\d+)$"
BLANK = np.zeros((1080, 1920, 3), dtype=np.uint8)


class _StubEngine:
    """按预设返回文本块，忽略裁剪内容。"""

    def __init__(self, blocks):
        self._blocks = list(blocks)

    def detect_text(self, img):
        return list(self._blocks)


def _rec(blocks):
    return TextFieldRecognizer("fortress_level", ROI, PATTERN,
                               engine=_StubEngine(blocks))


def test_whole_block_match_extracts_value_and_offsets_bbox():
    r = _rec([(BBox(200, 520, 300, 545), "等级：6", 0.97)]).recognize(BLANK)
    assert r.matched is True
    assert r.data["value"] == "6"
    assert r.data["text"] == "等级：6"
    assert r.confidence == 0.97
    # bbox 要加回 ROI 偏移（绝对坐标）：200+100, 520+470
    assert (r.bbox.x1, r.bbox.y1, r.bbox.x2, r.bbox.y2) == (300, 990, 400, 1015)


def test_long_sentence_containing_level_must_not_match():
    # 那次标注污染的复现：含「等级」的长句不得被当成年等级行
    r = _rec([(BBox(200, 520, 800, 545),
               "推荐兵力：1,400,000等级4的战斗单位集结进攻", 0.99)]).recognize(BLANK)
    assert r.matched is False
    assert r.data["text"] == ""


def test_leftmost_matching_block_wins():
    r = _rec([(BBox(500, 520, 600, 545), "等级：9", 0.99),
              (BBox(200, 520, 300, 545), "等级：4", 0.90)]).recognize(BLANK)
    assert r.data["value"] == "4"


def test_no_matching_block_is_a_miss():
    r = _rec([(BBox(10, 10, 60, 30), "城寨", 0.9)]).recognize(BLANK)
    assert r.matched is False
    assert r.bbox is None


def test_recognizer_id_defaults_to_field_id():
    r = _rec([(BBox(200, 520, 300, 545), "等级：6", 0.9)]).recognize(BLANK)
    assert r.recognizer_id == "fortress_level"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/recognizers/test_text_field.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'rok_assistant.core.recognizers.text_field'`

- [ ] **Step 3: 实现**

```python
# src/rok_assistant/core/recognizers/text_field.py
from __future__ import annotations

import re

import numpy as np

from ..recognizer import BBox, RecognizeResult


class TextFieldRecognizer:
    """按固定 ROI 裁剪 + OCR，用正则**整块**匹配取一个文本块。

    为什么整块匹配而不是子串：搜索面板里除「等级：6」之外还有
    「推荐兵力：1,400,000等级4的战斗单位集结进攻」这类含「等级」的长句，
    子串匹配会锚错对象——这正是 2026-10 那次标注污染的成因（见
    tools/fix_zhaizi_level_labels.py 的 docstring）。

    为什么 ROI 写死在 manifest 而不是靠 YOLO 定位：整条识别链的模板 ROI
    都是写死的，游戏一旦挪面板全部要重标，YOLO 腿换不到真实收益
    （spec §3.2）。

    `pattern` 必须**恰好一个捕获组**，它就是返回值里的 `value`。
    """

    def __init__(self, field_id: str, roi: BBox, pattern: str, engine,
                 name: str | None = None):
        self._id = field_id
        self._roi = roi
        self._pattern = re.compile(pattern)
        self._engine = engine
        self._name = name or field_id

    def recognize(self, screenshot: np.ndarray) -> RecognizeResult:
        x1, y1 = self._roi.x1, self._roi.y1
        crop = screenshot[y1:self._roi.y2, x1:self._roi.x2]
        hits = []
        for bbox, text, conf in self._engine.detect_text(crop):
            m = self._pattern.fullmatch(text.strip())
            if m is not None:
                hits.append((bbox, text, conf, m))
        if not hits:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   data={"text": ""}, recognizer_id=self._name)
        bbox, text, conf, m = min(hits, key=lambda h: h[0].x1)
        return RecognizeResult(
            matched=True,
            bbox=BBox(bbox.x1 + x1, bbox.y1 + y1, bbox.x2 + x1, bbox.y2 + y1),
            confidence=conf,
            data={"text": text, "value": m.group(1)},
            recognizer_id=self._name)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/recognizers/test_text_field.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add src/rok_assistant/core/recognizers/text_field.py tests/unit/core/recognizers/test_text_field.py
git commit -m "feat: 新增 TextFieldRecognizer（ROI + 整块正则读一个文本字段）"
```

---

### Task 2: manifest `text_fields:` 小节与装配

**Files:**
- Modify: `src/rok_assistant/core/template_registry.py`（`TextFieldSpec` 新增；`TemplateRegistry.__init__` / `load` / `build_recognizers` 各加一处）
- Modify: `templates/manifest.yaml`（顶层加 `text_fields:`）
- Test: `tests/unit/core/test_template_registry.py`（追加用例）

**Interfaces:**
- Consumes: Task 1 的 `TextFieldRecognizer(field_id, roi, pattern, engine, name=None)`。
- Produces: manifest 顶层 `text_fields:` → 识别器字典里出现 `out["fortress_level"]`（一个 `TextFieldRecognizer`），运行时由 `LeaderStateMachine` 通过 `self._rec.get("fortress_level")` 取用（Task 4）。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/unit/core/test_template_registry.py

_TEXT_FIELDS_MANIFEST = (
    "templates: []\n"
    "text_fields:\n"
    "- id: fortress_level\n"
    "  roi: [100, 470, 1040, 620]\n"
    "  pattern: '^等级\\s*[：:]\\s*(\\d+)$'\n"
)


def test_loads_text_fields_and_builds_recognizer(tmp_path):
    m = tmp_path / "manifest.yaml"
    m.write_text(_TEXT_FIELDS_MANIFEST, encoding="utf-8")
    reg = TemplateRegistry.load(m)
    recs = reg.build_recognizers(ocr_fallback=False)
    assert "fortress_level" in recs
    assert recs["fortress_level"]._roi.x1 == 100


def test_no_text_fields_section_builds_nothing_extra(tmp_path):
    m = tmp_path / "manifest.yaml"
    m.write_text("templates: []\n", encoding="utf-8")
    reg = TemplateRegistry.load(m)
    assert "fortress_level" not in reg.build_recognizers(ocr_fallback=False)


def test_text_field_survives_ocr_name_fallback_off(tmp_path):
    # 读面板数字不该被「车头名字要不要 OCR 兜底」这个开关门控
    m = tmp_path / "manifest.yaml"
    m.write_text(_TEXT_FIELDS_MANIFEST, encoding="utf-8")
    reg = TemplateRegistry.load(m)
    assert "fortress_level" in reg.build_recognizers(ocr_fallback=False)


def test_bad_text_field_roi_raises(tmp_path):
    m = tmp_path / "manifest.yaml"
    m.write_text(
        "templates: []\n"
        "text_fields:\n"
        "- id: fortress_level\n"
        "  roi: [1, 2, 3]\n"
        "  pattern: 'x'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="text_field fortress_level"):
        TemplateRegistry.load(m)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_template_registry.py -q -k "text_field"`
Expected: FAIL —— `TemplateRegistry` 没有 `text_fields` 支持，`fortress_level` 不在结果里

- [ ] **Step 3: 加 `TextFieldSpec` 与装配**

在 `template_registry.py` 的 `PixelStatSpec`（约 57-66 行）之后加：

```python
@dataclass(frozen=True)
class TextFieldSpec:
    """文本字段判据条目（manifest 顶层 `text_fields:` 小节）。

    与 PixelStatSpec 分开的理由相同：没有模板图，放进 `templates:` 会让
    `entry["file"]` KeyError，或被 auto_label_yolo / ingest_raw_imgs 逐个
    cv2.imread 后注入垃圾框。
    """
    id: str
    roi: ROI
    pattern: str
```

`TemplateRegistry.__init__` 加参数（保持 `pixel_stats` 位置不变，新参数追加在后）：

```python
    def __init__(self, templates: dict[str, TemplateSpec],
                 pixel_stats: list[PixelStatSpec] | None = None,
                 text_fields: list[TextFieldSpec] | None = None):
        self._t = templates
        self._pixel = list(pixel_stats or [])
        self._text = list(text_fields or [])
```

`build_recognizers` 里，把 `out.update(self._build_pixel_recognizers())`（现 167 行）改成：

```python
        out.update(self._build_pixel_recognizers())
        out.update(self._build_text_field_recognizers(ocr_engine))
        return out
```

在 `_build_pixel_recognizers` 之后加：

```python
    def _build_text_field_recognizers(self, ocr_engine) -> dict:
        """装配 manifest 顶层 `text_fields:` 小节（spec §3）。

        与 `ocr_name_fallback` **无关**：那个开关管的是「车头名字要不要 OCR
        兜底」，不是「能不能读面板上的数字」。engine 为 None 时自建一个——
        构造是懒的（不加载模型），且与名字判据共用实例时能吃到单帧缓存。
        """
        if not self._text:
            return {}
        from .recognizer import BBox
        from .recognizers.ocr_text import RapidOcrEngine
        from .recognizers.text_field import TextFieldRecognizer
        if ocr_engine is None:
            ocr_engine = RapidOcrEngine()
        out = {}
        for spec in self._text:
            out[spec.id] = TextFieldRecognizer(
                spec.id,
                BBox(spec.roi.x1, spec.roi.y1, spec.roi.x2, spec.roi.y2),
                spec.pattern, engine=ocr_engine)
        return out
```

`load` 里，在 `pixel_stats = [...]` 之后加：

```python
        text_fields = []
        for e in (raw.get("text_fields") or []):
            roi_raw = e.get("roi")
            if not (isinstance(roi_raw, list) and len(roi_raw) == 4):
                raise ValueError(f"Bad ROI in text_field {e['id']}: {roi_raw}")
            text_fields.append(TextFieldSpec(id=e["id"], roi=ROI(*roi_raw),
                                             pattern=e["pattern"]))
```

并把 `return TemplateRegistry(templates, pixel_stats)` 改成
`return TemplateRegistry(templates, pixel_stats, text_fields)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/core/test_template_registry.py -q`
Expected: PASS（既有用例 + 4 条新用例全绿）

- [ ] **Step 5: 加进 manifest**

在 `templates/manifest.yaml` **顶层**（与 `templates:` 同级，缩进 0）追加：

```yaml
# 面板上的文本字段：固定 ROI + OCR + 整块正则（见 core/recognizers/text_field.py）。
# 与 `templates:` / `pixel_stats:` 并列，不进 `templates:`——它没有模板图，
# 进去会让 entry["file"] KeyError，或被标注工具 cv2.imread 后注入垃圾框。
text_fields:
- id: fortress_level
  roi: [100, 470, 1040, 620]
  # 必须整块匹配。面板里另有「推荐兵力：1,400,000等级4的战斗单位集结进攻」
  # 这类含「等级」的长句，子串匹配会锚错对象——这正是那次标注污染的成因
  # （见 tools/fix_zhaizi_level_labels.py 的 docstring）。
  pattern: '^等级\s*[：:]\s*(\d+)$'
```

- [ ] **Step 6: 确认 manifest 仍能整体加载，并排查其它 `build_recognizers` 调用方**

Run: `.venv/Scripts/python.exe -X utf8 -c "from pathlib import Path; from rok_assistant.core.template_registry import TemplateRegistry; r=TemplateRegistry.load(Path('templates/manifest.yaml')); recs=r.build_recognizers(ocr_fallback=False); print('fortress_level' in recs, len(recs))"`
Expected: `True <N>`（N = 既有数量 + 1）

再确认 spec §10 第 4 条：

Run: `grep -rn "build_recognizers" src/ tools/ tests/ | grep -v template_registry.py`

对每个调用方确认「多出一个 `fortress_level` 识别器」无害（它不参与任何模板遍历、不读图、不被 `annotate_live` 画框）。若某个工具会遍历所有识别器做渲染或断言总数，把它加进白名单并在此步记录。

- [ ] **Step 7: 提交**

```bash
git add src/rok_assistant/core/template_registry.py templates/manifest.yaml tests/unit/core/test_template_registry.py
git commit -m "feat: manifest 顶层 text_fields 小节，装配 fortress_level 识别器"
```

---

### Task 3: 连点节奏 —— `rapid` 关键字与 `rapid_click_min/max`

**Files:**
- Modify: `src/rok_assistant/infra/anti_detection.py`（配置字段 + `HumanProfile._shaped` / `click_delay` / `rapid_click_delay` + `JitteringHandleSource.click`）
- Modify: `src/rok_assistant/core/handle_source.py`（`HandleSource` 协议 + `MockHandleSource` + `AdbHandleSource` + `Win32HandleSource`）
- Modify: `src/rok_assistant/coordination/replay.py`（`ReplayHandleSource.click`）
- Modify: `config.example.yaml`（`anti_detection:` 加两行）
- Test: `tests/unit/infra/test_anti_detection.py`（追加用例）、`tests/unit/core/test_handle_source_rapid.py`（新建，扫描测试）

**Interfaces:**
- Produces: `AntiDetectionConfig.rapid_click_min: float = 0.35` / `rapid_click_max: float = 0.8`；`HumanProfile.rapid_click_delay() -> float`；`HandleSource.click(x, y, anchor=None, rapid=False)`。
- 约定：`rapid` 只由 `JitteringHandleSource` 用来**选择延迟区间**，不向下转发；其余实现收下参数并忽略。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/unit/infra/test_anti_detection.py
import random

import numpy as np

from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.infra.anti_detection import (
    AntiDetectionConfig, HumanProfile, JitteringHandleSource,
)


def test_rapid_click_delay_uses_its_own_range():
    cfg = AntiDetectionConfig(action_delay_min=3.1, action_delay_max=5.5,
                              rapid_click_min=0.35, rapid_click_max=0.8,
                              delay_shape="uniform")
    prof = HumanProfile(cfg, rng=random.Random(0))
    vals = [prof.rapid_click_delay() for _ in range(300)]
    assert min(vals) >= 0.35
    assert max(vals) <= 0.8


def test_click_delay_is_unaffected_by_rapid_range():
    cfg = AntiDetectionConfig(action_delay_min=3.1, action_delay_max=5.5,
                              rapid_click_min=0.35, rapid_click_max=0.8,
                              delay_shape="uniform")
    prof = HumanProfile(cfg, rng=random.Random(0))
    vals = [prof.click_delay() for _ in range(300)]
    assert min(vals) >= 3.1
    assert max(vals) <= 5.5


def test_jittering_handle_picks_delay_by_rapid_flag(monkeypatch):
    slept = []
    monkeypatch.setattr("rok_assistant.infra.anti_detection.time.sleep",
                        lambda s: slept.append(s))
    cfg = AntiDetectionConfig(action_delay_min=3.1, action_delay_max=5.5,
                              rapid_click_min=0.35, rapid_click_max=0.8,
                              debug_no_jitter=True)
    inner = MockHandleSource(np.zeros((10, 10, 3), dtype=np.uint8))
    h = JitteringHandleSource(inner, HumanProfile(cfg))

    h.click(5, 5)
    assert slept[-1] == (3.1 + 5.5) / 2

    h.click(5, 5, rapid=True)
    assert slept[-1] == (0.35 + 0.8) / 2


def test_mock_handle_accepts_rapid_without_changing_recorded_clicks():
    # 既有 66 处调用方断言的是 (x, y) 二元组，形状不能变
    h = MockHandleSource(np.zeros((10, 10, 3), dtype=np.uint8))
    h.click(5, 5, rapid=True)
    assert h.clicks == [(5, 5)]
```

再建一个**扫描测试**（spec §9「rapid 参数漏实现」）。理由：漏改某个实现类只在运行时
炸 `TypeError`，而 `JitteringHandleSource` 是包装层——它先把 `rapid` 吃掉再调
`_inner.click`，所以漏改的那一类在单测里根本走不到。用 AST 扫源码，将来新增实现自动被覆盖：

```python
# tests/unit/core/test_handle_source_rapid.py
"""所有 HandleSource 实现都必须收下 `rapid` 关键字（spec §9）。"""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "rok_assistant"


def _click_impls():
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "click":
                    yield f"{path.name}:{node.name}", fn


def test_every_click_implementation_accepts_rapid():
    found = dict(_click_impls())
    assert len(found) >= 6, f"只扫到 {sorted(found)}，路径算错了"
    missing = sorted(where for where, fn in found.items()
                     if "rapid" not in {a.arg for a in fn.args.args})
    assert missing == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/infra/test_anti_detection.py tests/unit/core/test_handle_source_rapid.py -q`
Expected: FAIL —— `AntiDetectionConfig` 没有 `rapid_click_min`；`MockHandleSource.click` 不接受 `rapid`；扫描测试报出 6 个实现里缺 `rapid` 的那几个

- [ ] **Step 3: 加配置字段与 `rapid_click_delay`**

`AntiDetectionConfig` 里，在 `burst_scale` 之后加：

```python
    # 连点段（同一控件上的连续点击，如等级 +/-）的间隔。人手调数字盘是连着
    # 点好几下，不该套用跨动作延迟；而突发分支在 action_delay_min=3.1 下
    # 算出来只有 3.1–3.7s，等于没有突发（spec §5.2）。
    # 下限 0.35 有实测支撑：0.35s 间隔连点 19 次零丢失
    #（原 leader_sm._LEVEL_CLICK_PACE 的值）。
    rapid_click_min: float = 0.35
    rapid_click_max: float = 0.8
```

`HumanProfile` 里，把 `click_delay` 换成下面这一组（**形状逻辑抽成 `_shaped`，顺序逐字保持：
`hi <= lo` → `uniform` 短路 → 突发 → Beta**，既有 `test_anti_detection.py` 用例必须继续全绿）：

```python
    def _shaped(self, lo: float, hi: float) -> float:
        """同一套形状换一个区间（顺序即 spec §7 的回滚杠杆，别重排）。"""
        if hi <= lo:
            return lo
        if self._cfg.delay_shape == "uniform":
            return self._rng.uniform(lo, hi)
        if self._cfg.burst_prob > 0 and self._rng.random() < self._cfg.burst_prob:
            return lo + (hi - lo) * self._rng.uniform(0.0, self._cfg.burst_scale)
        return lo + (hi - lo) * self._rng.betavariate(_BETA_A, _BETA_B)

    # ---- 点击前延迟 ----
    def click_delay(self) -> float:
        cfg = self._cfg
        if cfg.debug_no_jitter:
            return (cfg.action_delay_min + cfg.action_delay_max) / 2
        return self._shaped(cfg.action_delay_min, cfg.action_delay_max)

    def rapid_click_delay(self) -> float:
        """连点段的间隔（见 AntiDetectionConfig.rapid_click_min）。"""
        cfg = self._cfg
        if cfg.debug_no_jitter:
            return (cfg.rapid_click_min + cfg.rapid_click_max) / 2
        return self._shaped(cfg.rapid_click_min, cfg.rapid_click_max)
```

`JitteringHandleSource.click` 改成：

```python
    def click(self, x: int, y: int, anchor: str | None = None,
              rapid: bool = False) -> None:
        delay = (self._profile.rapid_click_delay() if rapid
                 else self._profile.click_delay())
        time.sleep(delay)
        jx, jy = self._profile.disperse(int(x), int(y), anchor)
        # `anchor` 到此为止（既有约定，见类 docstring）；`rapid` 同理——
        # 两者都只对本层有意义，不往下传
        self._inner.click(jx, jy)
```

- [ ] **Step 4: 四个实现类收下 `rapid`**

`core/handle_source.py` 的协议（19 行）：

```python
    def click(self, x: int, y: int, anchor: str | None = None,
              rapid: bool = False) -> None:
        """Click at (x, y) in window-local pixel coordinates.

        `anchor` 是可选的目标名（模板 id），只用于让反检测层按目标选择
        散布 σ；实现类可以完全忽略它。

        `rapid=True` 表示这是**同一控件上的连续点击**（如等级 +/- 连点），
        反检测层据此换用更短的间隔区间（rapid_click_min/max）。同样只对
        反检测层有意义，实现类忽略即可。
        """
```

`MockHandleSource.click`（42 行）——**`self.clicks` 的记录形状保持 `(x, y)` 不变**：

```python
    def click(self, x: int, y: int, anchor: str | None = None,
              rapid: bool = False) -> None:
        self.clicks.append((x, y))
```

`AdbHandleSource.click`（142 行）与 `Win32HandleSource.click`（228 行）签名各加 `rapid: bool = False`，函数体不变。

`coordination/replay.py` 的 `ReplayHandleSource.click`（36 行）签名同样加 `rapid: bool = False`，函数体不变。

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/infra/test_anti_detection.py tests/unit/core/ tests/unit/coordination/test_replay.py -q`
Expected: PASS（既有用例全绿 + 4 条新用例 + 扫描测试）

- [ ] **Step 6: 更新示例配置**

`config.example.yaml` 的 `anti_detection:` 里，在 `burst_scale` 之后加：

```yaml
    rapid_click_min: 0.35   # 连点段（等级 +/- 连着点）间隔下限（秒）。
    rapid_click_max: 0.8    # 别低于 0.35：实测更快会丢点击。与 action_delay 独立
```

- [ ] **Step 7: 更新面向用户的配置说明**

`docs/配置说明.md` 里，在讲「防检测参数」的那一节补一段**只讲字段作用**的说明（不写具体取值）：
连点段间隔（`rapid_click_min/max`）管的是「同一个按钮上连着点好几下」的节奏，
和「每次动作前的延迟」（`action_delay_min/max`）是两回事；下限别调太低，否则游戏会丢点击。

- [ ] **Step 8: 提交**

```bash
git add src/rok_assistant/infra/anti_detection.py src/rok_assistant/core/handle_source.py src/rok_assistant/coordination/replay.py config.example.yaml docs/配置说明.md tests/unit/infra/test_anti_detection.py tests/unit/core/test_handle_source_rapid.py
git commit -m "feat: 连点段独立节奏 rapid_click_min/max，HandleSource.click 加 rapid 关键字"
```

---

### Task 4: 等级回读状态机（核心）

**Files:**
- Modify: `src/rok_assistant/workers/state_machine.py`（`_click_result` / `_click` 加 `rapid`）
- Modify: `src/rok_assistant/workers/leader_sm.py`（常量、`_read_level` / `_set_level` / `_cache_level` / `_blind_set_level` / `_verify_level` / `_select_level`、类 docstring）
- Modify: `tests/unit/workers/test_normalize_view.py:18`、`tests/unit/workers/test_leader_sm_gate.py:25`、`tests/unit/workers/test_either_sm_gate.py:15`、`tests/unit/workers/test_either_sm.py:13`、`tests/unit/workers/test_runner.py:153`、`tests/unit/workers/test_action_ledger_writes.py:14`、`tests/integration/test_end_to_end.py:50`（各删一行 `_LEVEL_CLICK_PACE` patch）
- Test: `tests/unit/workers/test_leader_sm.py`（改 fixture + 追加用例）

**Interfaces:**
- Consumes: Task 2 的 `self._rec.get("fortress_level")`（`TextFieldRecognizer`，`data["value"]` 是字符串）；Task 3 的 `self._click(rec_id, rapid=True)`。
- Produces: `LeaderStateMachine._read_level() -> int | None`、`_set_level(target: int, current: int) -> int`、`_cache_level(level: int) -> None`、`_blind_set_level(target: int) -> None`、`_verify_level(target: int) -> bool`。

- [ ] **Step 1: 加 `rapid` 透传到 `_click`**

`state_machine.py`：

```python
    def _click_result(self, r: RecognizeResult, rapid: bool = False) -> bool:
        x, y = r.bbox.center()
        self._handle.click(x, y, anchor=r.recognizer_id, rapid=rapid)
        return True

    def _click(self, rec_id: str, rapid: bool = False) -> bool:
        r = self._find(rec_id)
        if r is None:
            return False
        return self._click_result(r, rapid=rapid)
```

（其余 14 处 `_click(...)` 调用点因默认值而**逐字不变**。）

- [ ] **Step 2: 写失败测试**

先改 `tests/unit/workers/test_leader_sm.py` 的 autouse fixture（现 30-34 行）——
`_LEVEL_CLICK_PACE` 即将删除，改成一个只吃 sleep 的替身（`time.time()` 保持真实，
`_launch` 还在用它盖 rally_id）：

```python
class _NoSleepTime:
    """只吞掉 sleep 的 time 替身。`time()` 保持真实——_launch 用它盖 rally_id。"""

    def __init__(self, real):
        self._real = real
        self.sleeps = []

    def sleep(self, s):
        self.sleeps.append(s)

    def time(self):
        return self._real.time()


@pytest.fixture(autouse=True)
def _fast_time(monkeypatch):
    monkeypatch.setattr("rok_assistant.workers.state_machine.time", _FakeTime())
    # 等级回读的重读间隔在单测里置 0。连点节奏现由 anti_detection 持有，
    # 而这里的 handle 是裸 MockHandleSource（不经过 JitteringHandleSource），
    # 所以没有真实睡眠。
    monkeypatch.setattr("rok_assistant.workers.leader_sm.time",
                        _NoSleepTime(time))
```

顶部补 `import time`。

然后追加用例：

```python
from rok_assistant.core.recognizer import BBox, RecognizeResult


class _LevelStub:
    """假等级识别器：按调用顺序依次返回 levels，用尽后重复最后一个。
    None 表示读不出（matched=False）。"""

    def __init__(self, levels):
        self._levels = list(levels)
        self._i = 0

    def recognize(self, _img):
        lv = self._levels[min(self._i, len(self._levels) - 1)]
        self._i += 1
        if lv is None:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   data={"text": ""},
                                   recognizer_id="fortress_level")
        return RecognizeResult(
            matched=True, bbox=BBox(200, 520, 300, 545), confidence=0.9,
            data={"text": f"等级：{lv}", "value": str(lv)},
            recognizer_id="fortress_level")


def _make_sm_with_level(levels, target_levels=(7,)):
    """_make_sm + 注入 fortress_level 假识别器。"""
    sm, handle = _make_sm(target_levels=target_levels)
    sm._rec["fortress_level"] = _LevelStub(levels)
    return sm, handle


def _to_select_level(sm):
    sm.step()   # IDLE -> NORMALIZE
    sm.step()   # NORMALIZE -> SEARCH_FORTRESS
    sm.step()   # SEARCH_FORTRESS -> SELECT_LEVEL（执行 _select_level）


def test_select_level_skips_when_readback_equals_target():
    sm, handle = _make_sm_with_level([7], target_levels=(7,))
    _to_select_level(sm)
    # search_icon 1 + tab_fortress 1；一次 level_plus/minus 都没有
    assert len(handle.clicks) == 2


def test_select_level_clicks_exact_delta_up():
    sm, handle = _make_sm_with_level([3], target_levels=(6,))
    _to_select_level(sm)
    # search_icon 1 + tab 1 + plus 3 = 5（不是固定 12+N）
    assert len(handle.clicks) == 5


def test_select_level_clicks_exact_delta_down():
    sm, handle = _make_sm_with_level([9], target_levels=(4,))
    _to_select_level(sm)
    assert len(handle.clicks) == 1 + 1 + 5


def test_out_of_range_readback_falls_back_to_blind():
    sm, handle = _make_sm_with_level([15, 15, 15], target_levels=(7,))
    _to_select_level(sm)
    assert len(handle.clicks) == 1 + 1 + 12 + 6


def test_unreadable_level_falls_back_to_blind():
    sm, handle = _make_sm_with_level([None, None, None], target_levels=(7,))
    _to_select_level(sm)
    assert len(handle.clicks) == 1 + 1 + 12 + 6


def test_missing_recognizer_keeps_old_blind_behaviour():
    # 老配置 / 未更新 manifest：没有 fortress_level → 与改动前逐字相同
    sm, handle = _make_sm(target_levels=(7,))
    assert "fortress_level" not in sm._rec
    _to_select_level(sm)
    assert len(handle.clicks) == 1 + 1 + 12 + 6


def test_verify_corrects_a_lost_click():
    # 读序：初读 3 → 校验仍 3（点击被吞）→ 再校验 6（补点生效）
    sm, handle = _make_sm_with_level([3, 3, 6], target_levels=(6,))
    _to_select_level(sm)
    assert len(handle.clicks) == 1 + 1 + 3 + 3


def test_verify_gives_up_after_bounded_rounds_without_raising():
    sm, handle = _make_sm_with_level([3, 3, 3], target_levels=(6,))
    _to_select_level(sm)
    # 初读 3 + 两轮修正各 3 次，用尽 _LEVEL_VERIFY_ROUNDS 后只 warning
    assert len(handle.clicks) == 1 + 1 + 3 + 3 + 3
    assert not sm.is_terminal()


def test_readback_writes_cache_only_after_confirmation():
    from rok_assistant.workers.leader_sm import _LEVEL_CACHE
    sm, handle = _make_sm_with_level([6], target_levels=(6,))
    _to_select_level(sm)
    assert _LEVEL_CACHE.get(handle) == 6

    sm2, h2 = _make_sm_with_level([3, 3, 3], target_levels=(6,))
    _to_select_level(sm2)
    assert _LEVEL_CACHE.get(h2) is None      # 未确认 → 不写缓存
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/workers/test_leader_sm.py -q`
Expected: FAIL —— `_read_level` 不存在；`_LevelStub` 注入后 `_select_level` 仍走盲降，点击数对不上

- [ ] **Step 4: 改常量块**

`leader_sm.py` 的 22-30 行替换为：

```python
# 等级按钮连点太快游戏会丢点击（2026-09-11 实机验收：目标7实际4、目标8实际6；
# 0.35s 间隔实测 19 连点零丢失）。节奏值现由 anti_detection.rapid_click_min
# 持有（spec §5），这里不再有第二处硬编码 sleep。
_LEVEL_BLIND_RESET = 12          # 读不出等级时的降底点击数（原 12 次 minus）
_LEVEL_READ_ATTEMPTS = 3         # 读等级的重读次数
_LEVEL_VERIFY_ROUNDS = 2         # 回读校验 + 修正的轮数上限
# 搜索面板会记住上次等级。**2026-10-07 起本缓存只服务盲降回退路径**
# （_blind_set_level）——主路径改为回读面板实际等级，不再需要它。
# 保留而不是删除的原因：盲降就是改动前的代码，缓存命中时它只点差量；
# 删掉会让「OCR 读不出」的每一轮都退回 12 连点降底，那是回归（spec §4.4）。
# 弱引用键随句柄回收自动失效；锁保护两个 worker 线程的并发读写。
# 已知限制：若玩家在 GUI 运行期间手动改过面板等级，缓存会偏一轮。
_LEVEL_CACHE: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_LEVEL_CACHE_LOCK = threading.Lock()
```

- [ ] **Step 5: 换掉 `_select_level`，加五个新方法**

`leader_sm.py` 的 `_select_level`（现 362-391 行）整段替换为下面这一组：

```python
    def _read_level(self) -> int | None:
        """读搜索面板上的当前城寨等级；读不出返回 None。

        manifest 没配 `fortress_level`（旧配置 / 未更新模板）时直接返回
        None，调用方退回盲降——与改动前逐字相同的行为。
        """
        rec = self._rec.get("fortress_level")
        if rec is None:
            return None
        for attempt in range(_LEVEL_READ_ATTEMPTS):
            img = self._handle.capture()
            self.last_image = img          # 失败截图要能看到当时读到的是什么
            r = rec.recognize(img)
            if r.matched:
                raw = (r.data or {}).get("value", "")
                try:
                    lv = int(raw)
                except (TypeError, ValueError):
                    lv = None
                if lv is not None and 1 <= lv <= 10:
                    return lv
                # 读出个不在 1..10 的东西：面板多半不在城寨页（tab 切换失败）。
                # 不猜也不钳制——静默钳制会把「读错对象」伪装成「等级就是 10」，
                # 正是最难查的那类问题。
                logger.warning("[车头] 等级文本读出 %r（不在 1..10），视为读失败",
                               raw)
            if attempt < _LEVEL_READ_ATTEMPTS - 1:
                time.sleep(self._pause(None))
        return None

    def _set_level(self, target: int, current: int) -> int:
        """从 current 点差量到 target，返回实际点击次数（不写日志）。

        不加次数上限：两个端点都落在 1..10（`_read_level` 校验读值，
        `_current_level` 来自配置），差量天然有界。多一个上限只会让盲降
        路径不再与改动前等价，而「最坏情况与现状相同」是本次设计的前提。
        """
        delta = target - current
        btn = "level_plus" if delta > 0 else "level_minus"
        for _ in range(abs(delta)):
            self._click(btn, rapid=True)
        return abs(delta)

    def _cache_level(self, level: int) -> None:
        with _LEVEL_CACHE_LOCK:
            _LEVEL_CACHE[self._handle] = level

    def _blind_set_level(self, target: int) -> None:
        """等级读不出时的降级路径 = 改动前 _select_level 的主体，逐字保留。

        spec §4.4：**不删缓存**。缓存命中就只点差量，否则 12 连点降底再升。
        这条路径只在 OCR 失败时走到，保留缓存才能兑现「最坏情况与改动前相同」。
        与原实现的唯一差别是：每点一下的停顿不再由这里 sleep，改由
        JitteringHandleSource 按 `rapid=True` 用 rapid_click_min/max 承担
        （spec §5.2）——点击次数与顺序逐字未变。
        """
        with _LEVEL_CACHE_LOCK:
            cached = _LEVEL_CACHE.get(self._handle)
        if cached == target:
            logger.info("[车头] 面板等级已是 %s 级，跳过调整", target)
            return
        if cached is None:
            logger.info("[车头] 面板等级未知，先降到底再升到 %s 级", target)
            for _ in range(_LEVEL_BLIND_RESET):
                self._click("level_minus", rapid=True)
            start = 1
        else:
            start = cached
        self._set_level(target, start)
        self._cache_level(target)
        logger.info("[车头] 面板等级 %s → %s 级（%s 次点击）", start, target,
                    (_LEVEL_BLIND_RESET if cached is None else 0)
                    + abs(target - start))

    def _verify_level(self, target: int) -> bool:
        """回读校验 + 补点。返回 True = 已确认面板在 target。

        最后只 warning 不抛错：等级偏差会被后续 no_result 计数自然兜住
        （_check_result 的既有机制），不该为此直接烧掉一轮。
        """
        for _ in range(_LEVEL_VERIFY_ROUNDS):
            read = self._read_level()
            if read is None:
                return False
            if read == target:
                logger.info("[车头] 等级回读确认 %s 级", target)
                return True
            logger.warning("[车头] 等级回读 %s 级 ≠ 目标 %s 级，补点 %s 次",
                           read, target, abs(target - read))
            self._set_level(target, read)
        logger.warning("[车头] 等级回读仍未确认（目标 %s 级），继续本轮", target)
        return False

    def _select_level(self, ctx):
        # 面板记住上次的 Tab（实测落在「野蛮人」上，2026-09-11 实机验收发现）。
        # tab_fortress 模板采的是未选中（灰色）态：匹配到 ⇔ 当前不在城寨页，
        # 点它切换；已在城寨页（棕色选中态）不匹配，_click 自动跳过。
        self._click("tab_fortress")
        target = self._current_level(ctx)

        current = self._read_level()
        if current is None:
            logger.warning("[车头] 等级文本读不出（面板可能不在城寨页），退回盲降")
            self._blind_set_level(target)
            return
        if current == target:
            logger.info("[车头] 面板等级已是 %s 级，跳过调整", target)
            self._cache_level(target)
            return
        n = self._set_level(target, current)
        logger.info("[车头] 面板等级 %s → %s 级（%s 次点击）", current, target, n)
        if self._verify_level(target):
            self._cache_level(target)
```

**注意**：`_check_result` 里清缓存那段（现 411-412 行）**保持不动**——它属于盲降回退路径的既有语义。

- [ ] **Step 6: 更新类 docstring 的「v1 已知限制」**

`leader_sm.py` 的 64-65 行：

```
    v1 已知限制（接受，与 member_sm 同类）：等级设置盲进——level_minus ×12 /
    level_plus ×N 不回读结果等级，模板误点无法被检测。
```

改成：

```
    等级设置（2026-10-07 改）：优先**回读**面板上的「等级：N」文本
    （manifest 的 text_fields.fortress_level），据此点差量并回读校验，
    点击次数随当前等级自然变化。读不出时退回盲降（12 次 level_minus 降底
    再升，见 _blind_set_level），此时仍是改动前的盲进行为。
    已知限制：读出的等级可能来自非城寨页（面板会记住上次 Tab，而野蛮人页
    也有等级）——同一 ROI 上若两页都能读出合法数字，回读自洽、不会被自纠
    机制发现。待实机确认（spec §9）。
```

- [ ] **Step 7: 删掉 8 处 `_LEVEL_CLICK_PACE` patch**

从下面每个文件里删掉 `monkeypatch.setattr("rok_assistant.workers.leader_sm._LEVEL_CLICK_PACE", 0.0)` 那一行（若删后文件顶部 `import` 变成未使用则一并清理）：

- `tests/unit/workers/test_normalize_view.py:18`
- `tests/unit/workers/test_leader_sm_gate.py:25`
- `tests/unit/workers/test_either_sm_gate.py:15`
- `tests/unit/workers/test_either_sm.py:13`
- `tests/unit/workers/test_runner.py:153`
- `tests/unit/workers/test_action_ledger_writes.py:14`
- `tests/integration/test_end_to_end.py:50`

确认没有残留：`grep -rn "_LEVEL_CLICK_PACE" src/ tests/` → 无输出。

若某个测试自己构造了 `JitteringHandleSource`（会真睡），确认它用 `debug_no_jitter=True` 或已 patch 掉 `anti_detection.time.sleep`；否则改成裸 `MockHandleSource`。

- [ ] **Step 8: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/workers/ tests/unit/integration/ tests/integration/ -q`
Expected: PASS。

**必须全绿的三个护栏**（盲降回退路径没被改坏的证据）：
`test_select_level_reuses_cached_level`、`test_no_result_invalidates_level_cache_and_resyncs_on_retry`、`test_switch_order_follows_config_not_sorted` —— 这三个**一行都不改**。

- [ ] **Step 9: 记一条待实机验证**

在 `docs/PROGRESS.md` 的「待办」里加一条（**不要**写成已完成）：

```
- [ ] **等级回读的野蛮人页守卫（spec §9）**：面板记住上次 Tab，而野蛮人页也有
      等级。若 `tab_fortress` 那次点击失败、且野蛮人页的等级行落在同一 ROI
      （100,470,1040,620），回读会读出一个**看似合法**的数字，且因为回读自洽
      而不会被自纠机制发现。**实机在城寨页与野蛮人页各截一帧**，确认该 ROI
      只在城寨页读出「等级：N」。两页都读得出才需要加守卫。
```

- [ ] **Step 10: 提交**

```bash
git add src/rok_assistant/workers/state_machine.py src/rok_assistant/workers/leader_sm.py tests/ docs/PROGRESS.md
git commit -m "feat: 等级设置改为回读面板实际等级，点击次数随等级变化

主路径读 manifest 的 fortress_level（Task 1/2），据此点差量并回读校验，
消掉「固定 12 连点降底再升」这个固定步数签名，也消掉类 docstring 里
「等级设置盲进」那条已知限制。

读不出时逐字退回改动前的盲降路径；_LEVEL_CACHE 保留但降级为只服务该
路径（回读路径仅在确认成功时写它），所以既有的三个缓存测试一行未改、
继续当回退路径的回归护栏。

实机待验：野蛮人页同 ROI 也可能读出合法等级（spec §9）。"
```

---

### Task 5: 轮数暴露到 GUI + 跑完自动复位

**Files:**
- Modify: `src/rok_assistant/gui/config_dialog.py`（全局页加「运行」组）
- Modify: `src/rok_assistant/workers/runner.py`（主循环退出后上报 `worker_finished`）
- Modify: `src/rok_assistant/coordination/runtime.py`（订阅 + `all_workers_done`）
- Modify: `src/rok_assistant/gui/controller.py`（`run_finished` 信号）
- Modify: `src/rok_assistant/gui/main_window.py`（接信号复位按钮）
- Test: `tests/unit/workers/test_runner.py`、`tests/unit/coordination/test_runtime_finish.py`（新建）、`tests/integration/test_gui_smoke.py`（追加）

**Interfaces:**
- Produces:
  - EventBus 事件 `worker_finished`，payload `{"instance_id", "char_id", "char_name", "stopped_reason", "rounds_done", "ts"}`；**仅在 `stopped_reason is not None` 时发**。
  - EventBus 事件 `all_workers_done`，payload `{"reasons": {runner_key: stopped_reason}}`。
  - `GuiController.run_finished = pyqtSignal(dict)`。

- [ ] **Step 1: 写失败测试 —— runner 上报**

```python
# 追加到 tests/unit/workers/test_runner.py（沿用本文件的 _member_factory 与
# 构造风格，见 test_runner_stops_after_max_rounds 那一份）

def test_runner_publishes_worker_finished_on_natural_stop():
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    got = []
    bus.subscribe("worker_finished", got.append)
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(),
                     handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=bus, poll_interval=0.01, restart_cooldown=0.05,
                     max_rounds=1)
    r.sm.on_rally_launched({"rally_id": "r1"})
    r.start()
    deadline = time.time() + 5
    while time.time() < deadline and not got:
        time.sleep(0.02)
    r.stop()
    assert len(got) == 1
    assert got[0]["instance_id"] == "i1" and got[0]["char_id"] == "c1"
    assert "轮数上限" in got[0]["stopped_reason"]
    assert got[0]["rounds_done"] == 1


def test_runner_does_not_publish_worker_finished_on_user_stop():
    # 用户点 Stop 时 stopped_reason 保持 None —— 不能触发界面复位
    from rok_assistant.coordination.event_bus import EventBus
    bus = EventBus()
    got = []
    bus.subscribe("worker_finished", got.append)
    r = WorkerRunner(instance_id="i1", char_id="c1", char_name="x",
                     sm_factory=_member_factory(),
                     handle_source=MockHandleSource(
                         screenshot=np.zeros((100, 100, 3), dtype=np.uint8)),
                     event_bus=bus, poll_interval=0.01, restart_cooldown=0.05,
                     max_rounds=99)
    r.sm.on_rally_launched({"rally_id": "r1"})
    r.start()
    time.sleep(0.05)          # 让主循环真的转起来再停
    r.stop()
    assert r.stopped_reason is None
    assert got == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/workers/test_runner.py -q -k "worker_finished"`
Expected: FAIL —— 没有任何 `worker_finished` 事件

- [ ] **Step 3: runner 上报**

`runner.py` 的 `_run` 方法末尾（主循环 `while` 之后、`_check_stop_conditions` 定义之前）加：

```python
        # 主循环退出（三个 break 出口统一走到这里）。stopped_reason 非 None
        # 才算「自然收工」——用户点 Stop 时它保持 None，不能触发 GUI 复位。
        if self.stopped_reason is not None and self._bus:
            self._bus.publish("worker_finished", {
                "instance_id": self.instance_id, "char_id": self.char_id,
                "char_name": self.char_name,
                "stopped_reason": self.stopped_reason,
                "rounds_done": self.rounds_done,
                "ts": datetime.now().isoformat(timespec="seconds"),
            })
```

- [ ] **Step 4: 写失败测试 —— runtime 汇总**

```python
# tests/unit/coordination/test_runtime_finish.py
from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.coordination.runtime import RuntimeCoordinator
from rok_assistant.infra.config import RootConfig

CFG = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe"},
    "instances": [
        {"id": "mumu0", "mumu_index": 0,
         "characters": [{"id": "c0", "name": "车头", "role": "leader",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"]}]},
        {"id": "mumu1", "mumu_index": 1,
         "characters": [{"id": "c1", "name": "填兵", "role": "member",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"],
                         "fill_target_leaders": [{"instance": "mumu0",
                                                  "name": "车头"}]}]},
    ],
}


def _coord(bus):
    coord = RuntimeCoordinator(RootConfig.model_validate(CFG), event_bus=bus)
    # 不真启动：只放两个占位 runner，测汇总逻辑
    coord.runners = {"mumu0:c0": object(), "mumu1:c1": object()}
    return coord


def test_all_workers_done_only_after_every_runner_reports():
    bus = EventBus()
    done = []
    bus.subscribe("all_workers_done", done.append)
    _coord(bus)

    bus.publish("worker_finished", {"instance_id": "mumu0", "char_id": "c0",
                                    "stopped_reason": "已完成 10 轮，达到轮数上限"})
    assert done == []                      # 还差一台

    bus.publish("worker_finished", {"instance_id": "mumu1", "char_id": "c1",
                                    "stopped_reason": "已完成 10 轮，达到轮数上限"})
    assert len(done) == 1
    assert set(done[0]["reasons"]) == {"mumu0:c0", "mumu1:c1"}
    assert done[0]["reasons"]["mumu0:c0"] == "已完成 10 轮，达到轮数上限"


def test_all_workers_done_not_published_for_unknown_runner():
    bus = EventBus()
    done = []
    bus.subscribe("all_workers_done", done.append)
    _coord(bus)
    bus.publish("worker_finished", {"instance_id": "mumu9", "char_id": "x",
                                    "stopped_reason": "r"})
    assert done == []      # 不在 self.runners 里的事件不能凑数
```

- [ ] **Step 5: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/coordination/test_runtime_finish.py -q`
Expected: FAIL —— 没有 `all_workers_done` 事件

- [ ] **Step 6: runtime 汇总**

`runtime.py` 的 `__init__` 里（`self._running = False` 之前）加：

```python
        # 自然收工的 worker 逐个上报；全部报过 → 通知 GUI 复位按钮。
        # 用户点 Stop 的路径不上报（runner 只在 stopped_reason 非 None 时发）。
        self._stopped: dict[str, str] = {}
        self._bus.subscribe("worker_finished", self._on_worker_finished)
```

加方法：

```python
    def _on_worker_finished(self, payload: dict) -> None:
        """一台 worker 自然收工。全部收工 → 发 all_workers_done（spec §6.2）。

        只在 payload 里的 key 确实在 self.runners 里时才计入，否则
        「上一次运行遗留的迟到事件」会凑数提前复位按钮。
        """
        key = f"{payload.get('instance_id')}:{payload.get('char_id')}"
        if key not in self.runners:
            return
        self._stopped[key] = payload.get("stopped_reason", "")
        if not set(self.runners) <= set(self._stopped):
            return
        logger.info("全部 worker 已收工：%s", self._stopped)
        self._bus.publish("all_workers_done", {"reasons": dict(self._stopped)})
        self._running = False
```

`_rollback()` 与 `stop()` 里各加一行 `self._stopped.clear()`（下次 start 从头计）。

- [ ] **Step 7: 写失败测试 —— GUI 复位**

**不要新建测试文件**：`tests/integration/test_gui_smoke.py` 已有 `qapp` fixture 和 `FakeController`（离屏 `QT_QPA_PLATFORM=offscreen` 也在那个文件顶部设好了）。给 `FakeController` 加一个信号，再追加一条用例：

```python
# tests/integration/test_gui_smoke.py —— FakeController 类体内加一行
    status_changed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    run_finished = pyqtSignal(dict)          # 新增：all_workers_done 转发的信号


# 文件末尾追加
def test_run_finished_resets_buttons(qapp):
    from rok_assistant.gui.main_window import MainWindow
    ctrl = FakeController()
    w = MainWindow(controller=ctrl)
    w.start_btn.setEnabled(False)
    w.stop_btn.setEnabled(True)

    ctrl.run_finished.emit({"reasons": {"inst0:boss": "已完成 10 轮，达到轮数上限"}})

    assert w.start_btn.isEnabled() is True
    assert w.stop_btn.isEnabled() is False
    assert "已完成 10 轮" in w.statusBar().currentMessage()
```

（`MainWindow.__init__` 会往 root logger 挂 `QtLogHandler`，并起一个 2s 的刷新 `QTimer`；该文件既有的用例就是这么用的，照抄即可，不必额外清理。）

- [ ] **Step 8: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_gui_smoke.py -q -k run_finished`
Expected: FAIL —— `FakeController` 没有 `run_finished`，或 `MainWindow` 没连它（按钮不复位）

- [ ] **Step 9: 接 GUI 信号**

`controller.py`：在 `error_occurred = pyqtSignal(str)` 之后加

```python
    run_finished = pyqtSignal(dict)
```

在 `__init__` 的 `self._bus.subscribe("status_update", self._on_bus_status)` 之后加

```python
        self._bus.subscribe("all_workers_done", self._on_bus_all_done)
```

加方法：

```python
    def _on_bus_all_done(self, payload: dict) -> None:
        """全部 worker 自然收工 → 通知界面复位（spec §6.2）。"""
        self.run_finished.emit(payload)
```

`main_window.py`：在 `_connect_controller` 里加

```python
        self._controller.run_finished.connect(self._on_run_finished)
```

加方法：

```python
    def _on_run_finished(self, payload: dict):
        """全部 worker 跑完（自然收工）：按钮复位到停止态。

        用户点 Stop 走的不是这条路——runner 只在 stopped_reason 非 None
        时上报 worker_finished。不弹模态框：跑完是正常结束，打断无人值守
        场景反而添乱。
        """
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        reasons = "；".join(f"{k}: {v}" for k, v
                            in (payload.get("reasons") or {}).items())
        self.statusBar().showMessage(f"已收工 —— {reasons}" if reasons else "已收工")
```

- [ ] **Step 10: 配置对话框加「运行」组**

`config_dialog.py` 的 `_make_global_page` 里，在 `outer.addLayout(form)`（现 229 行）之后、
`anti = self._data["app"]["anti_detection"]` 之前插入：

```python
        # 运行参数：max_rounds / max_consecutive_failures 早就在配置模型里
        # （infra/config.py），但界面上一直没暴露，只能手改 yaml。
        run = QGroupBox("运行")
        rf = QFormLayout(run)
        rf.addRow("最多轮数", self._spin(("app", "max_rounds"),
                                        app["max_rounds"], 1, 9999))
        rf.addRow("连续失败上限", self._spin(("app", "max_consecutive_failures"),
                                          app["max_consecutive_failures"], 1, 99))
        outer.addWidget(run)
```

- [ ] **Step 11: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/workers/test_runner.py tests/unit/coordination/ tests/integration/test_gui_smoke.py tests/integration/test_controller.py -q`
Expected: PASS

- [ ] **Step 12: 更新面向用户的配置说明**

`docs/配置说明.md` 里补一段：配置界面的「运行」组管两件事——「最多轮数」（每角色跑完多少轮自动收工）
与「连续失败上限」（连着失败多少次自动收工）；跑完后界面会自动回到停止状态，状态栏写明停机原因。

- [ ] **Step 13: 提交**

```bash
git add src/rok_assistant/gui/config_dialog.py src/rok_assistant/gui/controller.py src/rok_assistant/gui/main_window.py src/rok_assistant/workers/runner.py src/rok_assistant/coordination/runtime.py docs/配置说明.md tests/
git commit -m "feat: 轮数/失败上限暴露到配置界面，跑完自动复位按钮

runner 主循环退出且 stopped_reason 非 None 时报 worker_finished（用户点
Stop 时它保持 None，不会误触发）；runtime 收齐全部 runner 后发
all_workers_done，controller 转成 run_finished 信号，界面复位按钮并把
停机原因写进状态栏。"
```

---

### Task 6: 启动预检

**Files:**
- Create: `src/rok_assistant/coordination/preflight.py`
- Modify: `src/rok_assistant/coordination/runtime.py`（`start()` 前置预检 + 消费返回的 handle，删掉原 `create_handle_source` 的 try/except）
- Test: `tests/unit/coordination/test_preflight.py`（新建）、`tests/integration/test_runtime_preflight.py`（新建）

**Interfaces:**
- Produces: `preflight(instances, app_config) -> dict[instance_id, HandleSource]`；失败抛 `RuntimeError`，文案形如
  `模拟器「阑珊填1」（mumu1，MuMu 编号 1）连不上：<最后一条异常>`。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/coordination/test_preflight.py
import numpy as np
import pytest

from rok_assistant.coordination import preflight as PF
from rok_assistant.infra.config import RootConfig

CFG = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe",
            "screen_width": 1920, "screen_height": 1080},
    "instances": [
        {"id": "mumu0", "name": "如愿", "mumu_index": 0,
         "characters": [{"id": "c0", "name": "车头", "role": "leader",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"]}]},
        {"id": "mumu1", "name": "阑珊填1", "mumu_index": 1,
         "characters": [{"id": "c1", "name": "填兵", "role": "member",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"],
                         "fill_target_leaders": [{"instance": "mumu0",
                                                  "name": "车头"}]}]},
    ],
}


class _FakeHandle:
    def __init__(self, frame=None, error=None):
        self._frame = frame
        self._error = error

    def capture(self):
        if self._error is not None:
            raise self._error
        return self._frame

    def click(self, x, y, anchor=None, rapid=False):
        pass


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(PF.time, "sleep", lambda _s: None)


def _cfg():
    return RootConfig.model_validate(CFG)


def test_preflight_returns_handles_for_all_instances(monkeypatch):
    frames = {"mumu0": _FakeHandle(np.zeros((1080, 1920, 3), dtype=np.uint8)),
              "mumu1": _FakeHandle(np.zeros((1080, 1920, 3), dtype=np.uint8))}
    monkeypatch.setattr(PF, "create_handle_source",
                        lambda **kw: frames[f"mumu{kw['mumu_index']}"])
    handles = PF.preflight(_cfg().instances, _cfg().app)
    assert set(handles) == {"mumu0", "mumu1"}


def test_preflight_retries_then_names_the_instance(monkeypatch):
    calls = []

    def _factory(**kw):
        calls.append(kw["mumu_index"])
        return _FakeHandle(error=RuntimeError("device not found"))

    monkeypatch.setattr(PF, "create_handle_source", _factory)
    with pytest.raises(RuntimeError) as ei:
        PF.preflight(_cfg().instances, _cfg().app)
    msg = str(ei.value)
    assert "如愿" in msg and "mumu0" in msg and "MuMu 编号 0" in msg
    assert "device not found" in msg
    assert len(calls) == 3          # 最多尝试 3 次


def test_preflight_rejects_wrong_frame_shape(monkeypatch):
    monkeypatch.setattr(
        PF, "create_handle_source",
        lambda **kw: _FakeHandle(np.zeros((1920, 1080, 3), dtype=np.uint8)))
    with pytest.raises(RuntimeError) as ei:
        PF.preflight(_cfg().instances, _cfg().app)
    assert "(1920, 1080, 3)" in str(ei.value)


def test_preflight_succeeds_after_a_transient_failure(monkeypatch):
    state = {"n": 0}

    def _factory(**kw):
        state["n"] += 1
        if state["n"] == 1:
            return _FakeHandle(error=RuntimeError("adb: device offline"))
        return _FakeHandle(np.zeros((1080, 1920, 3), dtype=np.uint8))

    monkeypatch.setattr(PF, "create_handle_source", _factory)
    handles = PF.preflight(_cfg().instances, _cfg().app)
    assert set(handles) == {"mumu0", "mumu1"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/coordination/test_preflight.py -q`
Expected: FAIL —— `No module named 'rok_assistant.coordination.preflight'`

- [ ] **Step 3: 实现 preflight**

```python
# src/rok_assistant/coordination/preflight.py
from __future__ import annotations

import time

from ..core.handle_source import create_handle_source
from ..infra.logger import get_logger

logger = get_logger(__name__)

# 每台模拟器最多尝试几次（首次 + 重试）。断线是常态而非异常：adb server
# 重启、模拟器刚唤醒都会让首次 capture 失败，重试通常就好了。
ATTEMPTS = 3
RETRY_BACKOFF = (1.0, 2.0)      # 第 2、3 次尝试前的等待（秒）


def _where(inst) -> str:
    """「这台模拟器怎么指认」的人类可读说法。

    与 runtime.start 里那段点名文案是同一套（2026-10-05：配了两台时裸异常
    只有「模拟器 1 可能没有启动」，用户不知道该去开哪个）。
    """
    if inst.mumu_index is not None:
        return f"MuMu 编号 {inst.mumu_index}"
    if inst.adb_address:
        return f"adb {inst.adb_address}"
    return f"窗口 {inst.window_title_pattern!r}"


def preflight(instances, app_config) -> dict:
    """逐台建句柄并真截一帧；失败点名抛 RuntimeError。

    返回 {instance_id: HandleSource}，供 RuntimeCoordinator.start() 复用——
    create_handle_source 走 mumu_index 时要调 MuMuManager（冻结包里实测
    0.67–1.11s，见 PROGRESS 已知问题 10），不该建两遍。

    为什么用 capture() 而不是 is_alive()：后者只查 `adb devices` 的状态字段
    （core/handle_source.py），而实机上真正会炸的是 screencap。

    为什么判定分辨率：竖屏/登录页/认错窗口会让门槛白等 900s（运行手册
    Step 1），与其静默烧 15 分钟，不如启动时就说清楚实际尺寸。
    """
    expected = (app_config.screen_height, app_config.screen_width, 3)
    handles: dict = {}
    for inst in instances:
        last: Exception | None = None
        t0 = time.monotonic()
        for attempt in range(ATTEMPTS):
            if attempt:
                time.sleep(RETRY_BACKOFF[attempt - 1])
            try:
                handle = create_handle_source(
                    mumu_index=inst.mumu_index,
                    mumu_manager_path=app_config.mumu_manager_path,
                    adb_address=inst.adb_address,
                    adb_path=app_config.adb_path,
                    window_title_pattern=inst.window_title_pattern)
                frame = handle.capture()
            except Exception as e:                  # noqa: BLE001 - 逐次重试
                last = e
                logger.warning("预检：模拟器「%s」第 %s/%s 次失败：%s",
                               inst.name, attempt + 1, ATTEMPTS, e)
                continue
            shape = getattr(frame, "shape", None)
            if shape != expected:
                last = RuntimeError(
                    f"截到的画面尺寸是 {shape}，期望 {expected}"
                    f"（竖屏 / 未进入地图界面 / 认错窗口）")
                logger.warning("预检：模拟器「%s」尺寸异常：%s", inst.name, shape)
                continue
            handles[inst.id] = handle
            break
        else:
            where = _where(inst)
            elapsed = time.monotonic() - t0
            # 这段**整个落在 worker 日志之外**：worker 还没起来，运行日志里
            # 一个字都没有（用户的 logs/ 里那次就是 0 字节）。所以这里既点名
            # 又写日志（同 runtime.start 的教训）。
            logger.error("模拟器「%s」（%s，%s）预检失败（耗时 %.1fs）：%s",
                         inst.name, inst.id, where, elapsed, last)
            raise RuntimeError(
                f"模拟器「{inst.name}」（{inst.id}，{where}）连不上"
                f"（已试 {ATTEMPTS} 次，耗时 {elapsed:.1f}s）：{last}")
    # 成功也要报一句，让用户知道连接**真的测过了**，而不是「没报错」。
    # 主线程 + 非 worker 线程名 → QtLogHandler 的 char_id 为空 →
    # MainWindow._on_log_line 直接落到状态栏（log_handler.py:60-61）。
    logger.info("预检通过：%s 台模拟器", len(handles))
    return handles
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/coordination/test_preflight.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 写失败测试 —— runtime 里预检先于识别器装配**

```python
# tests/integration/test_runtime_preflight.py
import pytest

from rok_assistant.coordination import runtime as RT
from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.infra.config import RootConfig

from tests.unit.coordination.test_preflight import CFG


def test_start_runs_preflight_before_building_recognizers(monkeypatch):
    order = []

    def _fake_preflight(instances, app_config):
        order.append("preflight")
        raise RuntimeError("模拟器「如愿」（mumu0，MuMu 编号 0）连不上：boom")

    def _fake_load(*_a, **_kw):
        order.append("recognizers")
        raise AssertionError("预检失败时不该装配识别器")

    monkeypatch.setattr(RT, "preflight", _fake_preflight)
    monkeypatch.setattr(RT.TemplateRegistry, "load", _fake_load)
    coord = RT.RuntimeCoordinator(RootConfig.model_validate(CFG),
                                  event_bus=EventBus())
    with pytest.raises(RuntimeError, match="连不上"):
        coord.start()
    assert order == ["preflight"]
    assert coord.runners == {}          # 没有任何 worker 被拉起
    assert coord._running is False      # 回滚干净，可再次 start
```

- [ ] **Step 6: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_preflight.py -q`
Expected: FAIL —— `RuntimeCoordinator.start()` 还没调 preflight

- [ ] **Step 7: 接进 `start()`**

`runtime.py` 顶部加 `from .preflight import preflight`（与既有 import 同组）。

`start()` 的 `try:` 块开头（`fill_names = sorted({...})` **之前**）插入：

```python
            # 预检先行：在任何 worker 诞生之前确认每台模拟器都截得到
            # screen_width×screen_height 的画面。放在装配识别器之前——
            # 识别器要加载 ONNX，好几秒，连不上的时候不该白花（spec §7.3）。
            handles = preflight(self._config.instances, self._config.app)
```

并把原来那段 `for inst in ...: try: handle = create_handle_source(...) except Exception as e: ... raise RuntimeError(...)`（现 124-147 行）替换为：

```python
            for inst in self._config.instances:
                # 预检已经建好并验过帧，这里直接复用——见 preflight 的 docstring
                handle = handles[inst.id]
                profile = HumanProfile(self._config.app.anti_detection)
                handle = JitteringHandleSource(handle, profile)
                for char in inst.characters[:1]:
                    self._spawn(inst, char, handle, recognizers, profile)
```

（那段注释里关于「报错必须点名是哪一台」的教训**不要丢**——它现在活在
`preflight._where` / `preflight` 的 `raise` 处，本步把注释里「见 runtime.start
的历史注释」的指引留在 `_where` 的 docstring 里即可。）

- [ ] **Step 8: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_preflight.py tests/integration/ tests/unit/coordination/ -q`
Expected: PASS

**注意**：既有的 `tests/integration/` 里若有真正调用 `RuntimeCoordinator.start()` 的用例，
它们现在会先走预检 → 需要 monkeypatch 掉 `RT.preflight`（返回假 handle）。
逐一按上面的方式处理，**不要**为了绕过而把预检挪到 `start()` 之后。

- [ ] **Step 9: 更新运行手册与配置说明**

- `docs/PROGRESS.md` 的「实机运行手册」Step 3 之前补一句：点 Start 会先自动预检每台模拟器
  （建句柄 + 真截一帧 + 校验 1920×1080），失败会点名是哪一台、并说明实际截到的尺寸；
  预检通过时状态栏会写「预检通过：N 台模拟器」。
- `docs/配置说明.md` 里补一段：Start 前会自动测试连接，连不上会直接弹窗说明是哪台、
  什么原因；**不需要**再先去配置页点「测试连接」。

- [ ] **Step 10: 提交**

```bash
git add src/rok_assistant/coordination/preflight.py src/rok_assistant/coordination/runtime.py tests/ docs/
git commit -m "feat: Start 前自动预检每台模拟器（capture + 分辨率 + 最多 3 次）

预检在任何 worker 诞生之前跑，失败点名抛错 → 界面弹窗，半启动状态从根上
消失（不再需要为连接失败走 _rollback）。返回建好的 handle 供 start 复用，
避免走 mumu_index 时把 MuMuManager 调两遍。

用 capture() 而非 is_alive()：后者只查 adb devices 状态，实机炸的是
screencap。顺带判定 1920×1080——竖屏/登录页会让门槛白等 900s，启动时
说清楚比静默烧 15 分钟好。"
```

---

### Task 7: 收尾 —— 文档同步与全量回归

**Files:**
- Modify: `docs/PROGRESS.md`（当前状态表 + 待办）
- Modify: `docs/HISTORY.md`（append-only，写本次会话流水）

**Interfaces:**
- Consumes: Task 1-6 的全部产出。
- Produces: 无代码接口。

- [ ] **Step 1: 更新 PROGRESS 的「已落地」表**

在 `docs/PROGRESS.md` 的「已落地」表格顶部加一行（日期 10-07），并**在「实机」列写「待实机」**（本次没有跑真模拟器）：

```
| 10-07 | **等级回读 + 连点节奏 + 轮数界面 + 启动预检** | 等级设置改读面板「等级：N」→ 点差量 → 回读校验（点击次数随等级变化）；连点段独立节奏 rapid_click_min/max；max_rounds/失败上限进配置界面 + 跑完自动复位；Start 前自动预检（capture + 1920×1080 + 最多 3 次） | 待实机 |
```

同时更新「核心闭环链路」表里「车头开集结」那一行的实现描述（`设等级（缓存差量）` → `设等级（回读差量 + 回读校验，读不出退回盲降）`）。

- [ ] **Step 2: 核对「已知问题」与阈值参考**

- 检查「已知问题」里是否有条目被本次改动解决或改变（尤其任何提到等级缓存失步、等级盲进的措辞）。
- 检查「阈值参考」小节：本次**没有**改模板图、没有换 YOLO 权重，所以阈值**不需要**重跑
  `calibrate_yolo_threshold`。若发现文档里暗示要重跑，在此纠正。
- 确认 `text_fields` 的 `fortress_level` **没有**被误加进 `templates:`（那是被四个工具
  `cv2.imread` 注入垃圾框的坑，见记忆 `rok-yolo-dataset-v5`）：
  Run: `grep -n "fortress_level" templates/manifest.yaml`
  Expected: 只出现在 `text_fields:` 小节内。

- [ ] **Step 3: 写 HISTORY 流水**

在 `docs/HISTORY.md` 末尾追加本次记录（append-only），内容包括：风控警告只给了笼统判据、
因此按「消除机器签名」取向设计；等级回读为何用固定 ROI + OCR 而非 YOLO 腿；
**为什么 `_LEVEL_CACHE` 最终保留而不是删除**（原设计删它，会让 OCR 读不出时每轮退回 12 连点，
是回归——见 spec §4.4）；连点节奏为何必须是独立旋钮（`lo=3.1` 下突发分支只有 3.1–3.7s，等于空转）；
以及「野蛮人页同 ROI」这个待实机验证的未知。

- [ ] **Step 4: 全量回归**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 全绿（本分支在 711 条基础上新增约 30 条）。

若出现**批量 setup 阶段的 `E`**：那是 `.pytest_tmp` 被上一次被强杀的 pytest 毒化了——
杀光孤儿 `python.exe` → `rm -rf .pytest_tmp` → 重跑（PROGRESS 已知问题 7），**不要**当成回归。

- [ ] **Step 5: 提交**

```bash
git add docs/PROGRESS.md docs/HISTORY.md
git commit -m "docs: 记录防检测加固落地（等级回读/连点节奏/轮数界面/启动预检）与实机待验项"
```

---

## 完成后的实机待验清单（不在本计划内，交给用户）

本计划全部用假件验证，**没有任何一条经过真模拟器**。合并后需要实机确认：

1. **野蛮人页守卫**（Task 4 Step 9 记入 PROGRESS 的那条）——本设计唯一的实质性未知。
2. 等级回读在真机上读得准（`zhaizi_level_text` 是离线脚本验证的，不是运行时验证的）。
3. 连点节奏 0.35s 下限在真机上不丢点击（沿用原 `_LEVEL_CLICK_PACE` 的实测值，但当时是配 3.1s 动作延迟 + 0.35s 硬编码 sleep 的组合，现在组合变了）。
4. 预检能拦住「模拟器没起」「竖屏」两类，且文案确实点名到台。
5. 跑满轮数后按钮真的自动复位（两号轮次不同长，需等到**都**收工）。
