"""答完后「绿色 = 正确答案」的判定。

答对时所选项变绿；答错时所选项变红、正确项仍是绿——所以**答对答错都能
学到**答案（spec §4.3）。

用 cv2 而不是 PIL：项目已有 cv2，且 BBox 本来就是像素坐标。**色相刻度
必须换算**：PIL 的 H∈[0,255]（绿≈85），cv2 的 H∈[0,179]（绿 42~77）。
先在 BGR 空间缩采样再转 HSV——直接缩 HSV 会因插值产生伪色相。
"""
from __future__ import annotations

from collections.abc import Mapping

import cv2
import numpy as np

from ..recognizer import BBox

GREEN_LO, GREEN_HI = 42, 77          # cv2 色相
RED_HI, RED_LO = 11, 172             # 红 = H≤11 或 H≥172
SAT_MIN, VAL_MIN = 40, 40
# 素材实测：正确项 0.97/0.98/1.00，唯一的非选项绿色块（`日程`）0.35~0.36。
# 0.55 落在两者之间，留了两倍余量；参考实现的 0.35 太贴噪声底。
DEFAULT_MIN_RATIO = 0.55


def _ratios(frame: np.ndarray, box: BBox, *,
            sat_min: int = SAT_MIN, val_min: int = VAL_MIN) -> tuple[float, float]:
    h, w = frame.shape[:2]
    x1, y1 = max(0, box.x1), max(0, box.y1)
    x2, y2 = min(w, box.x2), min(h, box.y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0, 0.0
    crop = frame[y1:y2, x1:x2]
    ch, cw = crop.shape[:2]
    crop = crop[::max(1, ch // 60), ::max(1, cw // 120)]   # 先在 BGR 空间缩采样
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    valid = (sat >= sat_min) & (val >= val_min)
    total = hue.size
    if not total:
        return 0.0, 0.0
    green = ((hue >= GREEN_LO) & (hue <= GREEN_HI) & valid).sum() / total
    red = (((hue <= RED_HI) | (hue >= RED_LO)) & valid).sum() / total
    return float(green), float(red)


def green_ratio(frame: np.ndarray, box: BBox, *,
                sat_min: int = SAT_MIN, val_min: int = VAL_MIN) -> float:
    """box 内绿色像素占比。`sat_min` / `val_min` 只为测试与外层调参保留。"""
    return _ratios(frame, box, sat_min=sat_min, val_min=val_min)[0]


def red_ratio(frame: np.ndarray, box: BBox, *,
              sat_min: int = SAT_MIN, val_min: int = VAL_MIN) -> float:
    return _ratios(frame, box, sat_min=sat_min, val_min=val_min)[1]


def pick_correct_option(frame: np.ndarray,
                        boxes: Mapping[str, BBox],
                        *, min_ratio: float = DEFAULT_MIN_RATIO) -> str | None:
    """返回「绿色高亮」的选项字母；没有合格项返回 None（**不猜**）。"""
    scored: list[tuple[float, str]] = []
    for letter, box in boxes.items():
        green, red = _ratios(frame, box)
        if green >= min_ratio and green > red:
            scored.append((green, letter))
    if not scored:
        return None
    scored.sort(key=lambda s: (-s[0], s[1]))     # 绿色占比最大；同分按字母
    return scored[0][1]
