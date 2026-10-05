"""YOLO 检测的 onnxruntime 后端（CPU）。

模型仍然是 YOLO（yolov8n / 64 类 / imgsz 640），换掉的只是**执行后端**：
从 ultralytics+torch 换成 onnxruntime。发行包因此不必携带 3~4GB 的 torch，
ultralytics 只在训练与导出时需要（tools/train_yolo.py、tools/export_onnx.py）。

对外契约与原来的 `SharedYoloDetector._model()` 返回值逐位一致：
- 可调用：`model(screenshot, device=None, verbose=False) -> [Detections]`
- 带 `.names` 属性：`{int: 类别名}`

`YoloClassAdapter` / `template_registry.build_recognizers` 因此一行都不用改。

预处理与后处理必须与 ultralytics 对齐（conf 0.25 / iou 0.7 / agnostic_nms=False
/ max_det 300 / multi_label=False），否则 `tools/calibrate_yolo_threshold.py`
标定出来的阈值（DEFAULT_YOLO_THRESHOLD 与 manifest 里的 yolo_threshold 覆盖）
会集体失效。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import cv2
import numpy as np

# ultralytics 的常量：NMS 里按类别偏移，保证不同类的框不会互相抑制。
_MAX_WH = 7680


def letterbox(img: np.ndarray, new_shape=(640, 640), color=(114, 114, 114),
              stride: int = 32, auto: bool = False):
    """等比缩放 + 居中补边，复刻 ultralytics 的 letterbox（auto=False）。

    返回 `(padded, ratio, (dw, dh))`，其中 `dw, dh` 是**半**边距（左/上），
    与 ultralytics 的返回约定一致，供 `scale_boxes` 反变换用。

    `color` 必须是三元组：`cv2.copyMakeBorder` 收到标量只会填第一个通道，
    补边会变成 (114,0,0) 的蓝色而不是中性灰。
    """
    shape = img.shape[:2]                      # h, w
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)
    if isinstance(color, int):
        color = (color, color, color)

    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    new_unpad = (int(round(shape[1] * r)), int(round(shape[0] * r)))
    dw = (new_shape[1] - new_unpad[0]) / 2
    dh = (new_shape[0] - new_unpad[1]) / 2
    if auto:
        dw, dh = np.mod(dw, stride), np.mod(dh, stride)

    if shape[::-1] != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)

    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right,
                             cv2.BORDER_CONSTANT, value=color)
    return img, r, (dw, dh)


def preprocess(img: np.ndarray, imgsz: int = 640):
    """BGR HWC uint8 -> NCHW float32 [0,1] 的 `(1,3,imgsz,imgsz)` blob。

    补边色是中性灰（114），对通道对称，所以「先补边再 BGR->RGB」与
    ultralytics 的顺序等价。
    """
    padded, ratio, pad = letterbox(img, (imgsz, imgsz))
    rgb = padded[:, :, ::-1]
    blob = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32) / 255.0
    return blob[None], ratio, pad


def xywh_to_xyxy(xywh: np.ndarray) -> np.ndarray:
    """中心点式 (cx,cy,w,h) -> 角点式 (x1,y1,x2,y2)。"""
    out = np.empty_like(xywh, dtype=np.float32)
    out[:, 0] = xywh[:, 0] - xywh[:, 2] / 2
    out[:, 1] = xywh[:, 1] - xywh[:, 3] / 2
    out[:, 2] = xywh[:, 0] + xywh[:, 2] / 2
    out[:, 3] = xywh[:, 1] + xywh[:, 3] / 2
    return out


def scale_boxes(boxes: np.ndarray, ratio: float, pad, orig_shape) -> np.ndarray:
    """把 letterbox 空间里的框映射回原图，并裁剪到画面内。"""
    h, w = orig_shape[:2]
    out = boxes.astype(np.float32).copy()
    out[:, [0, 2]] -= pad[0]
    out[:, [1, 3]] -= pad[1]
    out /= ratio
    out[:, [0, 2]] = out[:, [0, 2]].clip(0, w)
    out[:, [1, 3]] = out[:, [1, 3]].clip(0, h)
    return out


def _iou_of(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    a1 = (box[2] - box[0]) * (box[3] - box[1])
    a2 = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return inter / (a1 + a2 - inter + 1e-9)


def nms(boxes: np.ndarray, scores: np.ndarray, classes: np.ndarray,
        iou_thr: float = 0.7, agnostic: bool = False) -> np.ndarray:
    """贪心 NMS，返回保留的下标（按分数降序）。

    `agnostic=False` 时按类别偏移坐标，不同类的框永不互相抑制——对应
    ultralytics 的 `agnostic_nms=False`（训练 args 里就是这个值）。
    """
    if len(boxes) == 0:
        return np.empty(0, dtype=int)
    boxes = boxes.astype(np.float32)
    if not agnostic:
        boxes = boxes + classes.astype(np.float32)[:, None] * _MAX_WH
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        ious = _iou_of(boxes[i], boxes[order[1:]])
        order = order[1:][ious <= iou_thr]
    return np.asarray(keep, dtype=int)


def postprocess(pred: np.ndarray, ratio: float, pad, orig_shape,
                conf: float = 0.25, iou: float = 0.7, max_det: int = 300):
    """`(1, 4+nc, N)` -> `(xyxy Nx4, scores N, classes N)`（原图坐标系）。"""
    p = np.asarray(pred)
    if p.ndim == 3:
        p = p[0]
    # 导出图通常是 (4+nc, N)；万一导出成 (N, 4+nc) 也认。
    if p.shape[0] < p.shape[1]:
        p = p.T

    xywh = p[:, :4]
    class_scores = p[:, 4:]
    classes = class_scores.argmax(1)
    scores = class_scores[np.arange(len(classes)), classes]

    keep = scores >= conf
    xywh, scores, classes = xywh[keep], scores[keep], classes[keep]
    if len(scores) == 0:
        return (np.empty((0, 4), dtype=np.float32), scores, classes)

    boxes = scale_boxes(xywh_to_xyxy(xywh), ratio, pad, orig_shape)
    idx = nms(boxes, scores, classes, iou_thr=iou, agnostic=False)[:max_det]
    return boxes[idx], scores[idx], classes[idx]


def parse_class_names(raw: str) -> dict[int, str]:
    """解析 ONNX 元数据里的 `names`（ultralytics 写入的是 Python dict 的 str）。"""
    try:
        data = ast.literal_eval(raw)
    except (ValueError, SyntaxError) as e:
        raise ValueError(f"无法解析 ONNX 元数据 names: {raw[:120]!r}") from e
    if not isinstance(data, dict):
        raise ValueError(f"ONNX 元数据 names 不是 dict: {type(data).__name__}")
    return {int(k): str(v) for k, v in data.items()}


def load_class_names(session, model_path) -> dict[int, str]:
    """类别名优先取 ONNX 元数据，其次取同名 `.names.json` sidecar。

    元数据由 ultralytics 导出时写入（engine/exporter.py 的 metadata_props），
    所以正常路径下不需要 sidecar；simplify 若把元数据洗掉，导出工具会补写。
    """
    meta = {}
    try:
        meta = session.get_modelmeta().custom_metadata_map or {}
    except Exception:                                    # noqa: BLE001 - 元数据缺失不该致命
        meta = {}
    raw = meta.get("names")
    if raw:
        return parse_class_names(raw)

    sidecar = Path(model_path).with_suffix(".names.json")
    if sidecar.is_file():
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return {int(k): str(v) for k, v in data.items()}

    raise RuntimeError(
        f"ONNX 模型缺少类别名元数据：{model_path}。"
        f"请用 tools/export_onnx.py 重新导出（会写入 names 元数据或 .names.json）")


def _new_session(model_path):
    """建 InferenceSession。单独抽出来是为了测试能 monkeypatch 掉它。"""
    import onnxruntime as ort
    # venv 里的 onnxruntime 是 CPU-only 构建，只有 CPU/Azure provider。
    return ort.InferenceSession(str(model_path),
                                providers=["CPUExecutionProvider"])


class Box:
    """与 ultralytics 结果对象同构的轻量框：`.xyxy`/`.conf`/`.cls` 都是长度 1 的序列。"""

    __slots__ = ("xyxy", "conf", "cls")

    def __init__(self, xyxy, conf, cls):
        self.xyxy = [np.asarray(xyxy, dtype=np.float64)]
        self.conf = [float(conf)]
        self.cls = [int(cls)]


class Detections:
    """`result.boxes` 的容器；`YoloClassAdapter` 只读 `.boxes`。"""

    __slots__ = ("boxes",)

    def __init__(self, boxes):
        self.boxes = boxes


class OnnxYoloModel:
    """YOLO 的 onnxruntime 推理封装，接口对齐 ultralytics 的 `YOLO` 对象。

    懒加载：只有真正推理时才建 `InferenceSession`，所以 import 本模块
    （以及跑整个测试套件）不需要装 onnxruntime。
    """

    def __init__(self, model_path, conf: float = 0.25, iou: float = 0.7,
                 imgsz: int = 640):
        path = Path(model_path)
        if path.suffix.lower() == ".pt":
            raise ValueError(
                f"检测模型还是 torch 权重（{path}），运行时 ONNX 后端不认。"
                f"请先导出：.venv/Scripts/python.exe -X utf8 "
                f"tools/export_onnx.py --weights {path}")
        self._path = path
        self._conf = conf
        self._iou = iou
        self._imgsz = imgsz
        self._session = None
        self._input_name = None
        self._names = None

    def _sess(self):
        if self._session is None:
            self._session = _new_session(self._path)
            self._input_name = self._session.get_inputs()[0].name
        return self._session

    @property
    def names(self) -> dict:
        """类别下标 -> 类别名（模型元数据，首次访问会触发加载）。"""
        if self._names is None:
            self._names = load_class_names(self._sess(), self._path)
        return self._names

    def __call__(self, screenshot: np.ndarray, device=None,
                 verbose: bool = False) -> list:
        """签名与 ultralytics 的 `YOLO.__call__` 一致；`device` 仅为兼容而保留。"""
        blob, ratio, pad = preprocess(screenshot, self._imgsz)
        outputs = self._sess().run(None, {self._input_name: blob})
        xyxy, scores, classes = postprocess(
            outputs[0], ratio, pad, screenshot.shape[:2],
            conf=self._conf, iou=self._iou)
        return [Detections([Box(b, c, k)
                            for b, c, k in zip(xyxy, scores, classes)])]
