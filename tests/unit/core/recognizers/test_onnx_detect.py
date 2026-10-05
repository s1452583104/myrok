"""ONNX 后端单测。

venv 里没有 `onnx` 包（只有 onnxruntime），造不出真的 ONNX 图，所以
`InferenceSession` 一律 stub —— 与 test_yolo_detect.py 的 FakeYolo 同风格。
纯 numpy 的 letterbox / NMS / 反变换则直接测真值。
"""
import json

import numpy as np
import pytest

from rok_assistant.core.recognizer import BBox
from rok_assistant.core.recognizers import onnx_detect
from rok_assistant.core.recognizers.onnx_detect import (
    OnnxYoloModel, postprocess, letterbox, preprocess, xywh_to_xyxy,
    scale_boxes, nms, parse_class_names, load_class_names)
from rok_assistant.core.recognizers.yolo_detect import YoloClassAdapter


# ---- 预处理 ----

def test_letterbox_1080p_geometry():
    """1920x1080 -> 640x640：比例 1/3，上下各补 140，内容落在 140..500 行。"""
    img = np.full((1080, 1920, 3), 200, dtype=np.uint8)
    out, ratio, pad = letterbox(img, (640, 640))
    assert out.shape == (640, 640, 3)
    assert ratio == pytest.approx(1 / 3, abs=1e-6)
    assert pad == pytest.approx((0.0, 140.0), abs=1e-6)
    assert (out[0] == 114).all()          # 上边距是中性灰（三通道都要是 114）
    assert (out[639] == 114).all()        # 下边距
    assert (out[300] == 200).all()        # 中间是原图内容


def test_letterbox_square_no_pad():
    img = np.full((640, 640, 3), 200, dtype=np.uint8)
    out, ratio, pad = letterbox(img, (640, 640))
    assert ratio == pytest.approx(1.0)
    assert pad == pytest.approx((0.0, 0.0))
    assert out.shape == (640, 640, 3)


def test_preprocess_is_nchw_rgb_normalized():
    img = np.zeros((640, 640, 3), dtype=np.uint8)
    img[:, :] = (10, 20, 30)              # BGR
    blob, _, _ = preprocess(img, 640)
    assert blob.shape == (1, 3, 640, 640)
    assert blob.dtype == np.float32
    assert blob[0, 0, 0, 0] == pytest.approx(30 / 255)   # R 通道拿到 BGR 的第三个
    assert blob[0, 2, 0, 0] == pytest.approx(10 / 255)   # B 通道拿到第一个
    assert 0.0 <= blob.min() and blob.max() <= 1.0


# ---- 几何反变换 ----

def test_xywh_to_xyxy():
    out = xywh_to_xyxy(np.array([[10.0, 20.0, 4.0, 6.0]], dtype=np.float32))
    assert out[0] == pytest.approx([8.0, 17.0, 12.0, 23.0])


def test_scale_boxes_roundtrip():
    """letterbox 空间的框映射回原图，再正变换回去应当回到原点。"""
    ratio, pad, orig = 1 / 3, (0.0, 140.0), (1080, 1920)
    # 原图中心 (960, 540) 在 letterbox 空间是 (320, 320)
    boxes = np.array([[960 - 30, 540 - 15, 960 + 30, 540 + 15]], dtype=np.float32)
    lb = boxes * ratio
    lb[:, [0, 2]] += pad[0]
    lb[:, [1, 3]] += pad[1]
    assert lb[0] == pytest.approx([310.0, 315.0, 330.0, 325.0], abs=1e-3)
    back = scale_boxes(lb, ratio, pad, orig)
    assert back[0] == pytest.approx(boxes[0], abs=1e-3)


def test_scale_boxes_clips_to_frame():
    ratio, pad, orig = 1.0, (0.0, 0.0), (100, 100)
    boxes = np.array([[-50.0, -50.0, 500.0, 500.0]], dtype=np.float32)
    out = scale_boxes(boxes, ratio, pad, orig)
    assert out[0] == pytest.approx([0.0, 0.0, 100.0, 100.0])


# ---- NMS ----

def test_nms_suppresses_same_class_overlap():
    boxes = np.array([[0, 0, 100, 100], [5, 5, 105, 105]], dtype=np.float32)
    scores = np.array([0.9, 0.8])
    classes = np.array([0, 0])
    keep = nms(boxes, scores, classes, iou_thr=0.7)
    assert list(keep) == [0]


def test_nms_keeps_different_class_overlap():
    """agnostic=False：不同类的重合框不互相抑制（锁住 ultralytics 的语义）。"""
    boxes = np.array([[0, 0, 100, 100], [0, 0, 100, 100]], dtype=np.float32)
    scores = np.array([0.9, 0.8])
    classes = np.array([0, 1])
    keep = nms(boxes, scores, classes, iou_thr=0.7)
    assert sorted(keep) == [0, 1]


def test_nms_keeps_below_iou():
    boxes = np.array([[0, 0, 100, 100], [200, 200, 300, 300]], dtype=np.float32)
    scores = np.array([0.9, 0.8])
    classes = np.array([0, 0])
    assert len(nms(boxes, scores, classes, iou_thr=0.7)) == 2


def test_nms_empty():
    keep = nms(np.empty((0, 4), dtype=np.float32), np.empty(0),
               np.empty(0, dtype=int))
    assert len(keep) == 0


# ---- 后处理 ----

def _make_pred(entries, nc=64, n=8400):
    """entries: [(cx, cy, w, h, cls, score)]，其余 anchor 全 0 分。"""
    pred = np.zeros((1, 4 + nc, n), dtype=np.float32)
    for i, (cx, cy, w, h, k, s) in enumerate(entries):
        pred[0, 0, i] = cx
        pred[0, 1, i] = cy
        pred[0, 2, i] = w
        pred[0, 3, i] = h
        pred[0, 4 + k, i] = s
    return pred


def test_postprocess_maps_box_back_to_frame():
    pred = _make_pred([(320.0, 320.0, 60.0, 60.0, 3, 0.9)])
    boxes, scores, classes = postprocess(
        pred, 1 / 3, (0.0, 140.0), (1080, 1920))
    assert len(boxes) == 1
    assert classes[0] == 3
    assert scores[0] == pytest.approx(0.9)
    # letterbox 空间 (320,320) 是原图 (960,540)；边长 60 在 letterbox 空间
    # 对应原图 180，所以是 [870, 450, 1050, 630]。
    assert boxes[0] == pytest.approx([870.0, 450.0, 1050.0, 630.0], abs=1e-3)


def test_postprocess_filters_below_conf():
    pred = _make_pred([(320.0, 320.0, 60.0, 60.0, 3, 0.9),
                       (100.0, 100.0, 60.0, 60.0, 5, 0.1)])
    boxes, _, _ = postprocess(pred, 1.0, (0.0, 0.0), (640, 640))
    assert len(boxes) == 1


def test_postprocess_all_below_conf_returns_empty():
    pred = _make_pred([(320.0, 320.0, 60.0, 60.0, 3, 0.01)])
    boxes, scores, classes = postprocess(pred, 1.0, (0.0, 0.0), (640, 640))
    assert len(boxes) == 0 and len(scores) == 0 and len(classes) == 0


def test_postprocess_accepts_transposed_layout():
    """万一导出成 (1, N, 4+nc)，也要认。"""
    pred = _make_pred([(320.0, 320.0, 60.0, 60.0, 3, 0.9)]).transpose(0, 2, 1)
    boxes, _, classes = postprocess(pred, 1.0, (0.0, 0.0), (640, 640))
    assert len(boxes) == 1 and classes[0] == 3


# ---- 类别名 ----

def test_parse_class_names_from_metadata():
    assert parse_class_names("{0: 'a', 1: 'b'}") == {0: "a", 1: "b"}


def test_parse_class_names_garbage_raises():
    with pytest.raises(ValueError):
        parse_class_names("not a dict")


class _Meta:
    def __init__(self, meta):
        self.custom_metadata_map = meta


class _Session:
    """stub InferenceSession：可指定输出张量、元数据、调用计数。"""

    def __init__(self, output=None, meta=None):
        self._output = output
        self._meta = meta if meta is not None else {}
        self.runs = 0

    def get_inputs(self):
        return [type("In", (), {"name": "images"})()]

    def get_modelmeta(self):
        return _Meta(self._meta)

    def run(self, _outputs, _feed):
        self.runs += 1
        return [self._output]


def test_load_class_names_falls_back_to_sidecar(tmp_path):
    model = tmp_path / "detect.onnx"
    model.write_bytes(b"")
    model.with_suffix(".names.json").write_text(
        json.dumps({"0": "a", "1": "b"}), encoding="utf-8")
    names = load_class_names(_Session(meta={}), model)
    assert names == {0: "a", 1: "b"}


def test_load_class_names_missing_raises(tmp_path):
    model = tmp_path / "detect.onnx"
    model.write_bytes(b"")
    with pytest.raises(RuntimeError, match="类别名"):
        load_class_names(_Session(meta={}), model)


# ---- OnnxYoloModel ----

def test_pt_path_rejected():
    with pytest.raises(ValueError, match="export_onnx"):
        OnnxYoloModel("runs/gpu_1080_v10/weights/best.pt")


def test_onnx_detector_frame_cache(monkeypatch):
    """同帧多次查询只推理一次；新帧重新推理。"""
    session = _Session(output=_make_pred([(320.0, 320.0, 60.0, 60.0, 3, 0.9)]),
                       meta={"names": str({3: "search_icon"})})
    monkeypatch.setattr(onnx_detect, "_new_session", lambda path: session)

    model = OnnxYoloModel("unused.onnx")
    from rok_assistant.core.recognizers.yolo_detect import SharedYoloDetector
    shared = SharedYoloDetector("unused.onnx")
    shared._yolo = model

    frame = np.zeros((640, 640, 3), dtype=np.uint8)
    shared.detect(frame)
    shared.detect(frame)
    shared.detect(frame)
    assert session.runs == 1
    shared.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert session.runs == 2


def test_detector_result_feeds_yolo_class_adapter(monkeypatch):
    """证明鸭子类型契约：ONNX 结果能直接喂给未改动的 YoloClassAdapter。"""
    session = _Session(output=_make_pred([(320.0, 320.0, 60.0, 60.0, 3, 0.9)]),
                       meta={"names": str({3: "search_icon"})})
    monkeypatch.setattr(onnx_detect, "_new_session", lambda path: session)

    from rok_assistant.core.recognizers.yolo_detect import SharedYoloDetector
    shared = SharedYoloDetector("unused.onnx")
    shared._yolo = OnnxYoloModel("unused.onnx")

    adapter = YoloClassAdapter(shared, class_name="search_icon",
                               roi=BBox(900, 400, 1100, 700), threshold=0.5)
    r = adapter.recognize(np.zeros((1080, 1920, 3), dtype=np.uint8))
    assert r.matched
    assert r.bbox.x1 == 870 and r.bbox.y1 == 450

    # 同一帧换个 ROI 应当被中心判据挡掉
    miss = YoloClassAdapter(shared, class_name="search_icon",
                            roi=BBox(0, 0, 100, 100), threshold=0.5)
    assert not miss.recognize(np.zeros((1080, 1920, 3), dtype=np.uint8)).matched
