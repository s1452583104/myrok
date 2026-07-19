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
