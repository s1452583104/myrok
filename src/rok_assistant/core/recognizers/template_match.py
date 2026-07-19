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
