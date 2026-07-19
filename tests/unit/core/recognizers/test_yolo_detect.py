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
