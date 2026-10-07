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
