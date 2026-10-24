"""绿色 = 正确答案：判据来自素材实测（正确项 0.97~1.00，噪声块 0.35~0.36）。

**色相刻度是 cv2 的 0-179**。参考实现用 PIL 的 0-255（绿 60~110），
直接抄过来会落到青色区间，一行绿都数不出来——这里第一条用例就是它的哨兵。
"""
import numpy as np
import pytest

from rok_assistant.core.quiz.verify import green_ratio, pick_correct_option
from rok_assistant.core.recognizer import BBox

GREEN = (0, 200, 0)       # BGR：cv2 H≈60，S/V 都够
RED = (0, 0, 200)         # BGR：cv2 H≈0
GRAY = (128, 128, 128)    # S=0：被饱和度门槛排除

BOXES = {
    "A": BBox(10, 10, 50, 30),
    "B": BBox(60, 10, 100, 30),
    "C": BBox(10, 40, 50, 60),
    "D": BBox(60, 40, 100, 60),
}


def _frame(fills: dict[str, tuple[int, int, int]]) -> np.ndarray:
    frame = np.full((80, 120, 3), 40, dtype=np.uint8)
    for letter, color in fills.items():
        b = BOXES[letter]
        frame[b.y1:b.y2, b.x1:b.x2] = color
    return frame


def test_cv2_hue_scale_counts_green():
    """49..77 之外的色相不该被算成绿（PIL 的 60 在这里是青色）。"""
    assert green_ratio(_frame({"A": GREEN}), BOXES["A"]) == pytest.approx(1.0)
    assert green_ratio(_frame({"A": (200, 200, 0)}), BOXES["A"]) == pytest.approx(0.0)


def test_picks_the_green_option_regardless_of_the_clicked_one():
    frame = _frame({"A": GRAY, "B": GREEN, "C": RED, "D": GRAY})
    assert pick_correct_option(frame, BOXES) == "B"


def test_all_gray_returns_none_and_learns_nothing():
    assert pick_correct_option(_frame({k: GRAY for k in BOXES}), BOXES) is None


def test_red_is_not_green():
    """答错时所选项变红、正确项仍是绿：绝不能把红色当成正确答案。"""
    frame = _frame({"A": RED, "B": GRAY, "C": GRAY, "D": GRAY})
    assert pick_correct_option(frame, BOXES) is None


def test_half_green_is_below_the_default_threshold():
    frame = _frame({"A": GRAY, "B": GREEN, "C": GRAY, "D": GRAY})
    b = BOXES["B"]
    frame[b.y1:b.y1 + 10, b.x1:b.x2] = GRAY          # 只剩一半绿
    assert green_ratio(frame, b) == pytest.approx(0.5)
    assert pick_correct_option(frame, BOXES) is None
    # 放宽阈值就能认出来：阈值是旋钮，不是硬编码
    assert pick_correct_option(frame, BOXES, min_ratio=0.4) == "B"


def test_out_of_frame_box_is_zero_not_an_exception():
    assert green_ratio(_frame({}), BBox(-50, -50, -10, -10)) == 0.0
