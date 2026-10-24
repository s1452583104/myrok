"""RuntimeCoordinator.snapshot()：交给 GUI 缩略图的那一帧。

以前是把 1920×1080 的原帧整个编码成 JPEG 送过去，GUI 再解码 + 缩到
298×150 —— 按面积算白烧了 16 倍的编码与传输。缩略图只有卡片那么大，
编码前先缩。
"""
import cv2
import numpy as np

from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.coordination.runtime import RuntimeCoordinator
from rok_assistant.infra.config import RootConfig

from .test_runtime_stats import CFG

FRAME_W, FRAME_H = 1920, 1080


class _FrameRunner:
    """只带 `char_id` 与 `last_frame` 的占位 runner。"""

    def __init__(self, char_id, frame):
        self.char_id = char_id
        self.last_frame = frame


def _coord(runners):
    coord = RuntimeCoordinator(RootConfig.model_validate(CFG),
                               event_bus=EventBus())
    coord.runners = runners
    return coord


def _frame():
    # 棋盘格：缩放后仍有细节，不是一整块纯色
    img = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    img[::40, :] = 255
    img[:, ::40] = 255
    return img


def _decoded(blob):
    img = cv2.imdecode(np.frombuffer(blob, dtype=np.uint8),
                       cv2.IMREAD_COLOR)
    assert img is not None, "返回的不是能解码的 JPEG"
    return img


def test_snapshot_is_downscaled_before_encoding():
    coord = _coord({"mumu0:c0": _FrameRunner("c0", _frame())})
    blob = coord.snapshot("c0")
    h, w = _decoded(blob).shape[:2]
    assert (w, h) == (480, 270), f"缩略图仍是 {w}x{h}，编码前没缩"


def test_snapshot_keeps_aspect_ratio_for_non_16_9_frames():
    """模拟器给了非 16:9 的画面（分辨率没调对）时不能拉伸变形。

    缩放是「塞进 480×270 的框里」：1920×1200 按高卡住 → 432×270，
    而不是拉成 480×300（那会把 4:2.5 的画面压扁）。
    """
    frame = np.zeros((1200, 1920, 3), dtype=np.uint8)
    coord = _coord({"mumu0:c0": _FrameRunner("c0", frame)})
    h, w = _decoded(coord.snapshot("c0")).shape[:2]
    assert (w, h) == (432, 270)


def test_snapshot_does_not_mutate_the_source_frame():
    """缩放不能就地改 `runner.last_frame` —— 识别链还在读那一份原帧。

    原帧尺寸一变，所有 ROI 坐标全错位。
    """
    frame = _frame()
    coord = _coord({"mumu0:c0": _FrameRunner("c0", frame)})
    coord.snapshot("c0")
    assert frame.shape == (FRAME_H, FRAME_W, 3)


def test_snapshot_without_frame_returns_none():
    coord = _coord({"mumu0:c0": _FrameRunner("c0", None)})
    assert coord.snapshot("c0") is None


def test_snapshot_of_unknown_character_returns_none():
    coord = _coord({})
    assert coord.snapshot("nobody") is None
