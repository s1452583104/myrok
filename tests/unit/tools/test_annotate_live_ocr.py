"""`tools/annotate_live.py:_ocr_level_text` 的预处理与选块规则测试。

锁两件事，都是 2026-09-24 实测踩出来的：

1. **OCR 前必须补白边。** RapidOCR 的 DBNet 在文本贴住裁剪边界时会**整个失败**
   （返回空），而不是降级成低置信度。同一张肉眼无歧义的清晰裁剪图（"等级: 8"）：
   无留白 -> `[]`，白边 60px -> `等级：8`。而裁剪的 `pad_y` 只有框高的 10%
   （30px 的框 -> 3px），垂直留白几乎为零，所以白边不是可有可无的装饰——
   删掉它寨子等级就退回读不出。全库 42 个检出框实测：无白边 17/42，补白边 40/42。

2. **取最右含数字的文本块**，不是拼接全部文本。低置信度的杂讯数字（滑块边缘
   幻读）会把拼接结果污染成一个更长的错数——旧注释记的就是这个 bug。

注意判据是「含数字」而非「置信度最高」：OCR 常把「等级：」和数字切成两块，
数字那块置信度反而更低，按置信度挑会挑到没有数字的标签块。
"""
from __future__ import annotations

import numpy as np
import pytest

from rok_assistant.core.recognizer import BBox
from tools import annotate_live


class _FakeEngine:
    """记录收到的图，返回预设文本行。"""

    def __init__(self, lines=()):
        self._lines = list(lines)
        self.seen = None

    def detect_text(self, img):
        self.seen = img
        return self._lines


@pytest.fixture
def fake_engine(monkeypatch):
    def _install(lines=()):
        eng = _FakeEngine(lines)
        monkeypatch.setattr(annotate_live, "_ocr_engine", eng)
        return eng
    return _install


# --- 白边 -----------------------------------------------------------------

def test_crop_is_padded_with_a_white_border_before_ocr(fake_engine):
    """删掉 copyMakeBorder 这条就会失败——这正是它存在的意义。"""
    frame = np.full((200, 400, 3), 40, dtype=np.uint8)  # 深色底，白边才分辨得出
    eng = fake_engine()

    annotate_live._ocr_level_text(frame, 100, 80, 200, 110)

    seen = eng.seen
    assert seen is not None
    # 框 100x30 -> pad_x 15 / pad_y 3 -> 裁 130x36 -> 补 60 白边 -> 250x156
    # -> 2x -> 500x312。形状对上就说明裁剪和补边都在。
    assert seen.shape == (312, 500, 3), f"裁剪/补边口径变了：{seen.shape}"

    # 2x 后白边占 120px，四角必然全是白的
    for region in (seen[:100, :100], seen[:100, -100:],
                   seen[-100:, :100], seen[-100:, -100:]):
        assert np.all(region == 255), "四角不是白边——补边被删了？"

    # 中心是原图内容，不该被白边吃掉
    assert np.all(seen[140:170, 230:270] == 40), "原图内容被白边覆盖了"


def test_border_does_not_pull_in_neighbouring_pixels(fake_engine):
    """少外扩是**有意**的（防滑块像素卷入），所以修法是补白边而不是撑大裁剪框。

    把裁剪框之外的原图像素涂成 200（一个内容里不出现的值），只要 OCR 收到的图里
    一个 200 都没有，就证明白边是凭空加的、没有多裁原图。这比断言「边界是纯白」
    可靠——INTER_CUBIC 会把白边和内容混出中间值，边界像素本来就不是 255。
    """
    frame = np.full((200, 400, 3), 40, dtype=np.uint8)
    frame[:76, :] = 200     # 裁剪框上边界在 y=77
    frame[114:, :] = 200    # 下边界在 y=113
    eng = fake_engine()

    annotate_live._ocr_level_text(frame, 100, 80, 200, 110)

    seen = eng.seen
    assert not np.any(seen == 200), "OCR 图里出现了裁剪框外的像素——裁剪框被撑大了"
    assert np.all(seen[140:170, 230:270] == 40), "框内的原图内容应该原样保留"


# --- 选块 -----------------------------------------------------------------

def test_picks_the_rightmost_block_containing_a_digit(fake_engine):
    fake_engine([
        (BBox(10, 10, 60, 40), "等级：", 0.99),   # 置信度最高但没有数字
        (BBox(70, 10, 90, 40), "8", 0.40),        # 数字在这块，置信度最低
    ])
    assert annotate_live._ocr_level_text(np.zeros((200, 400, 3), np.uint8),
                                         100, 80, 200, 110) == "8"


def test_extracts_digits_from_a_merged_line(fake_engine):
    """OCR 常把标签和数字并成一块，这时要从整行里抠出数字。"""
    fake_engine([(BBox(10, 10, 120, 40), "等级：10", 0.8)])
    assert annotate_live._ocr_level_text(np.zeros((200, 400, 3), np.uint8),
                                         100, 80, 200, 110) == "10"


def test_returns_empty_when_no_block_has_a_digit(fake_engine):
    fake_engine([(BBox(10, 10, 60, 40), "等级：", 0.9)])
    assert annotate_live._ocr_level_text(np.zeros((200, 400, 3), np.uint8),
                                         100, 80, 200, 110) == ""


def test_returns_empty_when_ocr_finds_nothing(fake_engine):
    fake_engine([])
    assert annotate_live._ocr_level_text(np.zeros((200, 400, 3), np.uint8),
                                         100, 80, 200, 110) == ""


def test_fully_out_of_frame_box_does_not_crash(fake_engine):
    """框整个落在画面外时裁剪为空——必须返回空串而不是抛异常。"""
    fake_engine([(BBox(0, 0, 10, 10), "8", 0.9)])
    frame = np.zeros((100, 100, 3), np.uint8)
    # 100x100 的帧上取 [199:211, 199:211] -> 空切片
    assert annotate_live._ocr_level_text(frame, 200, 200, 210, 210) == ""
