import numpy as np
from rok_assistant.core.recognizer import Recognizer, RecognizeResult, BBox

def test_bbox_center():
    b = BBox(x1=10, y1=20, x2=30, y2=40)
    assert b.center() == (20, 30)

def test_recognize_result_helpers():
    r = RecognizeResult(matched=True, bbox=BBox(0,0,10,10), confidence=0.9, data={"text": "hi"})
    assert r.matched
    assert r.confidence > 0.8
    assert r.data["text"] == "hi"
