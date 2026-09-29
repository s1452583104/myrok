import cv2
import numpy as np
import pytest
from pathlib import Path
from rok_assistant.core.recognizers.ocr_text import OCRText
from rok_assistant.core.recognizer import RecognizeResult, BBox

FIX = Path(__file__).parent.parent.parent.parent / "fixtures"

class StubOcrBackend:
    """Pretends to be PaddleOCR. Returns canned result for hello world."""
    def __init__(self):
        self.calls = []
    def __call__(self, img, cls=True):
        self.calls.append(img.shape)
        # Pretend we found "hello world" at a fixed bbox
        return [[
            [[[10, 10], [190, 10], [190, 30], [10, 30]], ("hello world", 0.95)]
        ]]

def test_ocr_finds_text(monkeypatch):
    backend = StubOcrBackend()
    ocr = OCRText(expected_text="hello")
    monkeypatch.setattr(ocr, "_ensure_ocr", lambda: backend)
    img = cv2.imread(str(FIX / "text_hello.png"))
    r = ocr.recognize(img)
    assert r.matched
    assert "hello" in r.data.get("text", "").lower()

def test_ocr_no_match(monkeypatch):
    backend = StubOcrBackend()
    ocr = OCRText(expected_text="xyzzy_does_not_exist")
    monkeypatch.setattr(ocr, "_ensure_ocr", lambda: backend)
    blank = np.zeros((40, 200, 3), dtype=np.uint8)
    r = ocr.recognize(blank)
    assert not r.matched


# ---- RapidOCR 引擎注入路径（2026-09-17 三栈融合） ----

from rok_assistant.core.recognizers.ocr_text import RapidOcrEngine

class StubEngine:
    def __init__(self, lines):
        self._lines = lines
        self.queries = []
    def detect_text(self, frame):
        self.queries.append(frame.shape)
        return self._lines

def _bb(x1, y1, x2, y2):
    return BBox(x1, y1, x2, y2)

def test_ocr_engine_substring_match_with_roi():
    eng = StubEngine([(_bb(0, 0, 100, 30), "某某 [482A]Jy丶阑珊", 0.93)])
    ocr = OCRText(expected_text="Jy丶阑珊", roi=_bb(460, 240, 760, 660), engine=eng)
    img = np.zeros((700, 800, 3), dtype=np.uint8)
    r = ocr.recognize(img)
    assert r.matched
    assert "Jy丶阑珊" in r.data["text"]
    # ROI 裁剪：引擎拿到的是 300x420 子图
    assert eng.queries[0] == (420, 300, 3)

def test_ocr_engine_miss_returns_unmatched():
    eng = StubEngine([(_bb(0, 0, 100, 30), "别人家的名字", 0.9)])
    ocr = OCRText(expected_text="Jy丶阑珊", engine=eng)
    r = ocr.recognize(np.zeros((100, 200, 3), dtype=np.uint8))
    assert not r.matched

def test_rapid_ocr_engine_smoke():
    """真实 RapidOCR 引擎空图跑通（无文字 -> 空列表）。"""
    eng = RapidOcrEngine()
    img = np.full((60, 200, 3), 210, dtype=np.uint8)
    out = eng.detect_text(img)
    assert isinstance(out, list)


def test_rapid_ocr_cache_holds_frame_reference():
    """缓存命中后必须持有该帧的强引用（同 yolo_detect.py:54 的不变量）。

    缓存键含 `id(screenshot)`，若引擎不持有帧，调用方释放裁剪图后新数组会复用
    同一地址 -> 键碰撞 -> 直接返回**上一帧**的 OCR 结果（静默错误）。直接断言
    不变量本身：强制 CPython 地址复用不可靠，行为式复现会时灵时不灵。
    """
    class _FakeEngine:
        def __call__(self, img):
            return [([[0, 0], [50, 0], [50, 20], [0, 20]], "某文本", 0.9)], 0.0

    eng = RapidOcrEngine()
    eng._eng = _FakeEngine()  # 跳过真实 RapidOCR 的加载
    frame = np.zeros((40, 120, 3), dtype=np.uint8)

    assert eng.detect_text(frame)[0][1] == "某文本"

    assert any(v is frame for v in vars(eng).values()), (
        "detect_text 缓存后未持有帧的强引用：id() 被复用时会返回上一帧的 OCR 结果")
