from pathlib import Path
import shutil
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

@pytest.fixture
def image_manifest(tmp_path):
    # Manifest referencing a real (loadable) template image
    shutil.copy(FIX / "template_search.png", tmp_path / "template_search.png")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "templates:\n"
        "  - id: search\n"
        "    file: template_search.png\n"
        "    roi: full\n"
        "    threshold: 0.9\n"
        "  - id: search_roi\n"
        "    file: template_search.png\n"
        "    roi: [0, 0, 80, 80]\n"
        "    threshold: 0.9\n"
    )
    return manifest

def test_build_recognizers_returns_template_matches(image_manifest):
    from rok_assistant.core.recognizers.template_match import TemplateMatch
    reg = TemplateRegistry.load(image_manifest)
    recs = reg.build_recognizers()
    assert set(recs) == {"search", "search_roi"}
    assert all(isinstance(r, TemplateMatch) for r in recs.values())
    img = cv2.imread(str(FIX / "screenshot_with_template.png"))
    # full-screen ROI -> roi=None in the recognizer
    r = recs["search"].recognize(img)
    assert r.matched
    assert abs(r.bbox.x1 - 40) < 2
    # bounded ROI -> BBox, coords back in global image space
    r2 = recs["search_roi"].recognize(img)
    assert r2.matched
    assert abs(r2.bbox.x1 - 40) < 2

def test_build_recognizers_missing_image_raises(manifest_with_png):
    # btn_a.png is a stub of empty bytes -> cv2.imread returns None
    reg = TemplateRegistry.load(manifest_with_png)
    with pytest.raises(FileNotFoundError):
        reg.build_recognizers()

def test_build_recognizers_rejects_yolo(tmp_path):
    (tmp_path / "card.onnx").write_bytes(b"")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "templates:\n"
        "  - id: card\n"
        "    file: card.onnx\n"
        "    type: yolo_detect\n"
        "    classes: [0]\n"
        "    threshold: 0.7\n"
    )
    reg = TemplateRegistry.load(manifest)
    with pytest.raises(ValueError, match="unsupported template type for card: yolo_detect"):
        reg.build_recognizers()


# ---- 三识别栈融合（2026-09-17）：Chain(模板→YOLO/OCR 兜底) 装配 ----

class _FakeBoxes:
    def __init__(self, rows):
        self._rows = rows
    def __iter__(self):
        return iter(self._rows)
    def __len__(self):
        return len(self._rows)

class _FakeBox:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = [np.array(xyxy, dtype=float)]
        self.conf = [conf]
        self.cls = [cls]

class _FakeResult:
    def __init__(self, rows):
        # 行格式 (x1, y1, x2, y2, conf)，类别固定 0（fake 只覆盖单类命中路径）
        self.boxes = _FakeBoxes(
            [_FakeBox(r[:4], r[4], 0) for r in rows])

class _FakeSharedYolo:
    """Stub SharedYoloDetector: fixed detections, class-name -> id 0..n order."""
    def __init__(self, rows, names):
        self._rows = rows
        self.names = names
    def detect(self, frame):
        return [_FakeResult(self._rows)]

def test_build_recognizers_yolo_fallback_chain(image_manifest):
    from rok_assistant.core.recognizer import RecognizerChain
    reg = TemplateRegistry.load(image_manifest)
    recs = reg.build_recognizers(
        yolo_shared=_FakeSharedYolo([], {0: "search", 1: "search_roi"}))
    assert set(recs) == {"search", "search_roi"}
    assert all(isinstance(r, RecognizerChain) for r in recs.values())
    img = cv2.imread(str(FIX / "template_search.png"))  # 模板自身命中 -> 主路径
    r = recs["search"].recognize(cv2.imread(str(FIX / "screenshot_with_template.png")))
    assert r.matched

def test_yolo_fallback_fires_when_template_misses(image_manifest):
    reg = TemplateRegistry.load(image_manifest)
    # 模板在纯灰底上不命中 -> YOLO 兜底命中（fake 返回 0.9 置信框）
    fake = _FakeSharedYolo([(10, 10, 30, 30, 0.9)], {0: "search", 1: "search_roi"})
    recs = reg.build_recognizers(yolo_shared=fake)
    img = np.full((200, 200, 3), 128, dtype=np.uint8)
    r = recs["search"].recognize(img)
    assert r.matched
    assert r.bbox.x1 == 10

def test_yolo_fallback_respects_threshold(image_manifest):
    reg = TemplateRegistry.load(image_manifest)  # threshold 0.9
    fake = _FakeSharedYolo([(10, 10, 30, 30, 0.6)], {0: "search"})
    recs = reg.build_recognizers(yolo_shared=fake)
    img = np.full((200, 200, 3), 128, dtype=np.uint8)
    r = recs["search"].recognize(img)
    assert not r.matched   # YOLO 0.6 < 模板阈值 0.9 -> 整链未命中

def test_yolo_spec_builds_adapter_with_model(image_manifest):
    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8")
                        + "  - id: card\n    file: card.onnx\n"
                          "    type: yolo_detect\n    classes: [0]\n"
                          "    threshold: 0.7\n", encoding="utf-8")
    reg = TemplateRegistry.load(manifest)
    fake = _FakeSharedYolo([(10, 10, 30, 30, 0.8)], {0: "whatever"})
    recs = reg.build_recognizers(yolo_shared=fake)
    r = recs["card"].recognize(np.zeros((100, 100, 3), dtype=np.uint8))
    assert r.matched and abs(r.confidence - 0.8) < 1e-6


def test_yolo_fallback_skipped_when_class_not_in_model(image_manifest):
    # queue_recall_icon 类被 YOLO 排除训练：模板为主，不挂兜底
    # （挂了运行时 resolve 类名会 KeyError）
    reg = TemplateRegistry.load(image_manifest)
    recs = reg.build_recognizers(yolo_shared=_FakeSharedYolo([], {0: "unrelated"}))
    from rok_assistant.core.recognizers.template_match import TemplateMatch
    assert isinstance(recs["search"], TemplateMatch)
    # 类在模型里的 id 正常挂兜底
    recs2 = reg.build_recognizers(yolo_shared=_FakeSharedYolo([], {0: "search"}))
    from rok_assistant.core.recognizer import RecognizerChain
    assert isinstance(recs2["search"], RecognizerChain)


def test_fill_spec_gets_ocr_fallback(image_manifest):
    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8")
                        + "  - id: fill_Jy丶阑珊\n    file: template_search.png\n"
                          "    roi: [460, 240, 760, 660]\n    threshold: 0.9\n",
                        encoding="utf-8")
    from rok_assistant.core.recognizers.ocr_text import OCRText

    class StubOcrEngine:
        def __init__(self):
            self.queries = []
        def detect_text(self, frame):
            self.queries.append(frame.shape)
            from rok_assistant.core.recognizer import BBox
            return [(BBox(10, 10, 100, 30), "某某 [482A]Jy丶阑珊", 0.93)]

    engine = StubOcrEngine()
    reg = TemplateRegistry.load(manifest)
    recs = reg.build_recognizers(yolo_shared=_FakeSharedYolo([], {}),
                                 ocr_engine=engine)
    # 模板命中与否未知（灰底大概率未命中）→ OCR 兜底按名字文本命中
    img = np.full((700, 800, 3), 128, dtype=np.uint8)
    r = recs["fill_Jy丶阑珊"].recognize(img)
    assert r.matched
    assert "Jy丶阑珊" in r.data["text"]
    assert len(engine.queries) >= 1

def test_fill_spec_ocr_only_without_model(image_manifest):
    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8")
                        + "  - id: fill_某人\n    file: template_search.png\n"
                          "    roi: [460, 240, 760, 660]\n    threshold: 0.9\n",
                        encoding="utf-8")
    from rok_assistant.core.recognizers.template_match import TemplateMatch
    reg = TemplateRegistry.load(manifest)
    recs = reg.build_recognizers()   # 未配置 yolo_model：与旧版一致纯模板
    assert isinstance(recs["fill_某人"], TemplateMatch)
