from __future__ import annotations
import numpy as np
from ..recognizer import RecognizeResult, BBox

class YoloDetect:
    def __init__(self, model, threshold: float = 0.5, classes: list | None = None,
                 _yolo=None, name: str = "yolo_detect"):
        self._model = model
        self._threshold = threshold
        self._classes = classes
        self._name = name
        self._yolo = _yolo

    def _load(self):
        if self._yolo is None:
            from ultralytics import YOLO
            self._yolo = YOLO(self._model)
        return self._yolo

    def recognize(self, screenshot: np.ndarray) -> RecognizeResult:
        yolo = self._load()
        results = yolo(screenshot)
        if not results:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   recognizer_id=self._name, bbox_list=[])
        r = results[0]
        bboxes = []
        max_conf = 0.0
        if hasattr(r, "boxes") and r.boxes is not None:
            for box in r.boxes:
                xyxy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy[0], "cpu") else np.array(box.xyxy[0])
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                if self._classes is not None and cls not in self._classes:
                    continue
                if conf < self._threshold:
                    continue
                bboxes.append(BBox(int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])))
                max_conf = max(max_conf, conf)
        return RecognizeResult(
            matched=len(bboxes) > 0,
            bbox=bboxes[0] if bboxes else None,
            confidence=max_conf,
            data={"bbox_list": bboxes},
            recognizer_id=self._name,
            bbox_list=bboxes,
        )
