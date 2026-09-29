from __future__ import annotations
import numpy as np
from ..recognizer import Recognizer, RecognizeResult, BBox


class RapidOcrEngine:
    """Shared RapidOCR backend (PP-OCR models, ONNX runtime, models ship
    inside the wheel — no runtime download, works offline / py3.14 where
    paddlepaddle has no wheels). Single-entry frame cache: state machines
    query fill_<name> ids several times per screenshot.
    """

    def __init__(self):
        self._eng = None
        self._cache_key = None
        self._cache_val = None
        self._cache_img = None

    def _ensure(self):
        if self._eng is None:
            from rapidocr_onnxruntime import RapidOCR
            self._eng = RapidOCR()
        return self._eng

    def detect_text(self, screenshot: np.ndarray) -> list[tuple[BBox, str, float]]:
        key = (id(screenshot), screenshot.shape)
        if key == self._cache_key:
            return self._cache_val
        raw, _elapse = self._ensure()(screenshot)
        out: list[tuple[BBox, str, float]] = []
        if raw:
            for box_pts, text, conf in raw:
                xs = [p[0] for p in box_pts]
                ys = [p[1] for p in box_pts]
                out.append((BBox(int(min(xs)), int(min(ys)),
                                 int(max(xs)), int(max(ys))),
                            str(text), float(conf)))
        self._cache_key = key
        self._cache_val = out
        # 强引用帧：缓存键含 id(screenshot)，不持有引用则调用方释放裁剪图后
        # 新数组会复用同一地址 -> 键碰撞 -> 返回上一帧的 OCR 结果（同
        # yolo_detect.py 记录的不变量，那里通过 results 间接持有）。
        self._cache_img = screenshot
        return out


class OCRText:
    """OCR-based text recognizer.

    Two backends:
    - injected ``engine`` (RapidOcrEngine) — production path, ROI-cropped,
      frame-cached;
    - legacy PaddleOCR object behind ``_ensure_ocr`` — kept for backward
      compat (tests inject stubs via monkeypatch).

    Matching: substring of expected_text in the recognized line; best
    confidence wins. Without expected_text the single best-confidence line
    is returned (matched).
    """

    def __init__(self, expected_text: str = "", use_angle_cls: bool = True,
                 lang: str = "ch", roi: BBox | None = None,
                 engine: RapidOcrEngine | None = None,
                 name: str = "ocr_text"):
        self._expected = expected_text
        self._lang = lang
        self._use_angle_cls = use_angle_cls
        self._roi = roi
        self._engine = engine
        self._ocr = None
        self._name = name

    def _ensure_ocr(self):
        # legacy paddle path (unused in production while engine is injected)
        if self._ocr is None:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(use_angle_cls=self._use_angle_cls, lang=self._lang,
                                  show_log=False)
        return self._ocr

    def recognize(self, screenshot: np.ndarray) -> RecognizeResult:
        if self._engine is not None:
            return self._recognize_engine(screenshot)
        return self._recognize_legacy(screenshot)

    def _recognize_engine(self, screenshot: np.ndarray) -> RecognizeResult:
        ox, oy = (self._roi.x1, self._roi.y1) if self._roi else (0, 0)
        img = screenshot
        if self._roi is not None:
            img = screenshot[self._roi.y1:self._roi.y2, self._roi.x1:self._roi.x2]
        best = None
        for bbox, text, conf in self._engine.detect_text(img):
            if self._expected and self._expected in text:
                b = BBox(bbox.x1 + ox, bbox.y1 + oy, bbox.x2 + ox, bbox.y2 + oy)
                r = RecognizeResult(matched=True, bbox=b, confidence=conf,
                                    data={"text": text}, recognizer_id=self._name)
                if best is None or conf > best.confidence:
                    best = r
        if best is not None:
            return best
        if self._expected:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   data={"text": ""}, recognizer_id=self._name)
        # no expected_text: return highest-confidence line as matched
        lines = self._engine.detect_text(img)
        if not lines:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   recognizer_id=self._name)
        bbox, text, conf = max(lines, key=lambda t: t[2])
        return RecognizeResult(
            matched=True,
            bbox=BBox(bbox.x1 + ox, bbox.y1 + oy, bbox.x2 + ox, bbox.y2 + oy),
            confidence=conf, data={"text": text}, recognizer_id=self._name)

    def _recognize_legacy(self, screenshot: np.ndarray) -> RecognizeResult:
        ocr = self._ensure_ocr()
        # PaddleOCR object exposes .ocr(); stub test doubles are callables.
        if hasattr(ocr, "ocr"):
            results = ocr.ocr(screenshot, cls=self._use_angle_cls)
        else:
            results = ocr(screenshot, cls=self._use_angle_cls)
        if not results or not results[0]:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   recognizer_id=self._name)
        best = None
        for line in results[0]:
            bbox_pts, (text, conf) = line
            if self._expected and self._expected in text:
                xs = [p[0] for p in bbox_pts]; ys = [p[1] for p in bbox_pts]
                b = BBox(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
                if best is None or conf > best.confidence:
                    best = RecognizeResult(matched=True, bbox=b, confidence=conf,
                                           data={"text": text}, recognizer_id=self._name)
        if best is not None:
            return best
        # No match for expected_text. If we had an expected_text, this is a real miss.
        if self._expected:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   data={"text": ""}, recognizer_id=self._name)
        line = max(results[0], key=lambda l: l[1][1])
        bbox_pts, (text, conf) = line
        xs = [p[0] for p in bbox_pts]; ys = [p[1] for p in bbox_pts]
        return RecognizeResult(
            matched=True, bbox=BBox(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
            confidence=conf, data={"text": text}, recognizer_id=self._name
        )
