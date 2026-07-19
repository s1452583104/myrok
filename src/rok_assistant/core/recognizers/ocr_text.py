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
        # PaddleOCR object exposes .ocr(); stub test doubles are callables.
        if hasattr(ocr, "ocr"):
            results = ocr.ocr(screenshot, cls=self._use_angle_cls)
        else:
            results = ocr(screenshot, cls=self._use_angle_cls)
        if not results or not results[0]:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   recognizer_id="ocr_text")
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
        # No match for expected_text. If we had an expected_text, this is a real miss.
        if self._expected:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   data={"text": ""}, recognizer_id="ocr_text")
        line = max(results[0], key=lambda l: l[1][1])
        bbox_pts, (text, conf) = line
        xs = [p[0] for p in bbox_pts]; ys = [p[1] for p in bbox_pts]
        return RecognizeResult(
            matched=True, bbox=BBox(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
            confidence=conf, data={"text": text}, recognizer_id="ocr_text"
        )
