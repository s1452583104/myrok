from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable, Any
import numpy as np

@dataclass(frozen=True)
class BBox:
    x1: int; y1: int; x2: int; y2: int
    def center(self) -> tuple:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)
    def area(self) -> int:
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)

@dataclass
class RecognizeResult:
    matched: bool
    bbox: BBox | None
    confidence: float
    data: dict = field(default_factory=dict)
    recognizer_id: str = ""
    bbox_list: list = field(default_factory=list)

@runtime_checkable
class Recognizer(Protocol):
    """Single-strategy recognizer. Returns RecognizeResult."""
    def recognize(self, screenshot: np.ndarray) -> RecognizeResult: ...


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
        best = None
        for rec in self._recognizers:
            r = rec.recognize(screenshot)
            if best is None or r.confidence > best.confidence:
                best = r
        return best or RecognizeResult(matched=False, bbox=None, confidence=0.0)
