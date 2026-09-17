import pytest
import numpy as np
from rok_assistant.core.recognizers.yolo_detect import YoloDetect
from rok_assistant.core.recognizer import BBox

class FakeBox:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = [np.array(list(xyxy), dtype=float)]
        self.conf = [conf]
        self.cls = [cls]

class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes

class FakeYolo:
    def __init__(self, detections):
        self._detections = detections
    def __call__(self, img):
        return [FakeResult([FakeBox(d[:4], d[4], d[5]) for d in self._detections])]

def test_yolo_returns_bboxes():
    fake = FakeYolo([(10, 20, 50, 60, 0.9, 0), (100, 200, 150, 250, 0.8, 0)])
    yd = YoloDetect(model=object(), threshold=0.5, classes=[0], _yolo=fake)
    r = yd.recognize(np.zeros((300, 300, 3), dtype=np.uint8))
    assert r.matched
    assert len(r.bbox_list) == 2

def test_yolo_filters_below_threshold():
    fake = FakeYolo([(10, 20, 50, 60, 0.3, 0)])
    yd = YoloDetect(model=object(), threshold=0.5, classes=[0], _yolo=fake)
    r = yd.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
    assert not r.matched


# ---- SharedYoloDetector + YoloClassAdapter（2026-09-17 三栈融合） ----

from rok_assistant.core.recognizers.yolo_detect import (
    SharedYoloDetector, YoloClassAdapter)
from rok_assistant.core.recognizer import BBox


class CountingYolo(FakeYolo):
    def __init__(self, detections):
        super().__init__(detections)
        self.calls = 0

    def __call__(self, img, device=None, verbose=False):
        self.calls += 1
        return super().__call__(img)

    @property
    def names(self):
        return {0: "queue_battle_icon", 1: "search_icon"}


def test_shared_detector_caches_per_frame():
    fake = CountingYolo([(10, 20, 50, 60, 0.9, 0)])
    shared = SharedYoloDetector("unused.pt")
    shared._yolo = fake
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    shared.detect(frame)
    shared.detect(frame)
    shared.detect(frame)
    assert fake.calls == 1          # 同帧多次查询只推理一次
    frame2 = np.zeros((100, 100, 3), dtype=np.uint8)
    shared.detect(frame2)
    assert fake.calls == 2          # 新帧重新推理


def test_adapter_filters_class_and_roi():
    fake = CountingYolo([(10, 20, 50, 60, 0.9, 0),      # battle, in ROI
                         (300, 300, 350, 350, 0.95, 0), # battle, outside ROI
                         (10, 20, 50, 60, 0.95, 1)])    # wrong class
    shared = SharedYoloDetector("unused.pt")
    shared._yolo = fake
    adapter = YoloClassAdapter(shared, class_name="queue_battle_icon",
                               roi=BBox(0, 0, 200, 200), threshold=0.5)
    r = adapter.recognize(np.zeros((400, 400, 3), dtype=np.uint8))
    assert r.matched
    assert len(r.bbox_list) == 1
    assert r.bbox.x1 == 10 and r.bbox.y1 == 20


def test_adapter_threshold_miss():
    fake = CountingYolo([(10, 20, 50, 60, 0.3, 0)])
    shared = SharedYoloDetector("unused.pt")
    shared._yolo = fake
    adapter = YoloClassAdapter(shared, class_id=0, threshold=0.5)
    r = adapter.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
    assert not r.matched


def test_adapter_unknown_class_raises():
    fake = CountingYolo([])
    shared = SharedYoloDetector("unused.pt")
    shared._yolo = fake
    adapter = YoloClassAdapter(shared, class_name="no_such_class")
    with pytest.raises(KeyError, match="no_such_class"):
        adapter.recognize(np.zeros((50, 50, 3), dtype=np.uint8))
