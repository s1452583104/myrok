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


class SharedYoloDetector:
    """One loaded YOLO model shared by all per-class adapters.

    Inference is cached per screenshot (single-entry: the cache holds a
    strong reference to the frame, so id() cannot be reused while cached —
    a new capture is always a new array). All state machines query the same
    frame several times per step (queue verdict checks 7 template ids);
    without the cache each query would re-run the network.
    """

    def __init__(self, model_path, device=None):
        self._path = model_path
        self._device = device
        self._yolo = None
        self._cache_key = None
        self._cache_val = None

    def _model(self):
        if self._yolo is None:
            from ultralytics import YOLO
            self._yolo = YOLO(str(self._path))
        return self._yolo

    @property
    def names(self) -> dict:
        """Class index -> name mapping (model metadata, may force load)."""
        return self._model().names

    def detect(self, screenshot: np.ndarray):
        key = (id(screenshot), screenshot.shape)
        if key == self._cache_key:
            return self._cache_val
        # callable 接口：YOLO 对象的 __call__ 即 predict，测试注入的 fake 也是 callable
        results = self._model()(screenshot, device=self._device, verbose=False)
        self._cache_key = key
        self._cache_val = results
        return results


class YoloClassAdapter:
    """Per-template-id view over SharedYoloDetector.

    Filters raw detections to one class (by id or model class name), conf >=
    threshold, and box center inside the template ROI. Used as the fallback
    leg of a template_match chain: the calibrated template is tried first,
    YOLO only gets a say when the template misses (catches animation frames /
    background shifts the pixel matcher can't).
    """

    def __init__(self, shared: SharedYoloDetector, class_name: str = "",
                 class_id: int | None = None, roi=None, threshold: float = 0.5,
                 name: str = "yolo_detect"):
        self._shared = shared
        self._class_name = class_name
        self._class_id = class_id
        self._roi = roi          # recognizer.BBox or None (full frame)
        self._threshold = threshold
        self._name = name

    def _resolve_class_id(self) -> int:
        if self._class_id is not None:
            return self._class_id
        names = self._shared.names
        for idx, nm in names.items():
            if nm == self._class_name:
                self._class_id = idx
                return idx
        raise KeyError(f"class {self._class_name!r} not in YOLO model "
                       f"(names={list(names.values())})")

    def recognize(self, screenshot: np.ndarray) -> RecognizeResult:
        cid = self._resolve_class_id()
        result = self._shared.detect(screenshot)[0]
        bboxes = []
        max_conf = 0.0
        if getattr(result, "boxes", None) is None:
            return RecognizeResult(matched=False, bbox=None, confidence=0.0,
                                   recognizer_id=self._name, bbox_list=[])
        for box in result.boxes:
            conf = float(box.conf[0])
            if int(box.cls[0]) != cid or conf < self._threshold:
                continue
            xyxy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy[0], "cpu") \
                else np.array(box.xyxy[0])
            b = BBox(int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3]))
            if self._roi is not None:
                cx, cy = b.center()
                if not (self._roi.x1 <= cx < self._roi.x2
                        and self._roi.y1 <= cy < self._roi.y2):
                    continue
            bboxes.append(b)
            max_conf = max(max_conf, conf)
        return RecognizeResult(
            matched=len(bboxes) > 0,
            bbox=bboxes[0] if bboxes else None,
            confidence=max_conf,
            data={"bbox_list": bboxes},
            recognizer_id=self._name,
            bbox_list=bboxes,
        )
