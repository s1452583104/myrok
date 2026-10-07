import numpy as np

from rok_assistant.core.recognizer import BBox
from rok_assistant.core.recognizers.text_field import TextFieldRecognizer

ROI = BBox(100, 470, 1040, 620)
PATTERN = r"^等级\s*[：:]\s*(\d+)$"
BLANK = np.zeros((1080, 1920, 3), dtype=np.uint8)


class _StubEngine:
    """按预设返回文本块，忽略裁剪内容。"""

    def __init__(self, blocks):
        self._blocks = list(blocks)

    def detect_text(self, img):
        return list(self._blocks)


def _rec(blocks):
    return TextFieldRecognizer("fortress_level", ROI, PATTERN,
                               engine=_StubEngine(blocks))


def test_whole_block_match_extracts_value_and_offsets_bbox():
    r = _rec([(BBox(200, 520, 300, 545), "等级：6", 0.97)]).recognize(BLANK)
    assert r.matched is True
    assert r.data["value"] == "6"
    assert r.data["text"] == "等级：6"
    assert r.confidence == 0.97
    # bbox 要加回 ROI 偏移（绝对坐标）：200+100, 520+470
    assert (r.bbox.x1, r.bbox.y1, r.bbox.x2, r.bbox.y2) == (300, 990, 400, 1015)


def test_long_sentence_containing_level_must_not_match():
    # 那次标注污染的复现：含「等级」的长句不得被当成年等级行
    r = _rec([(BBox(200, 520, 800, 545),
               "推荐兵力：1,400,000等级4的战斗单位集结进攻", 0.99)]).recognize(BLANK)
    assert r.matched is False
    assert r.data["text"] == ""


def test_leftmost_matching_block_wins():
    r = _rec([(BBox(500, 520, 600, 545), "等级：9", 0.99),
              (BBox(200, 520, 300, 545), "等级：4", 0.90)]).recognize(BLANK)
    assert r.data["value"] == "4"


def test_no_matching_block_is_a_miss():
    r = _rec([(BBox(10, 10, 60, 30), "城寨", 0.9)]).recognize(BLANK)
    assert r.matched is False
    assert r.bbox is None


def test_recognizer_id_defaults_to_field_id():
    r = _rec([(BBox(200, 520, 300, 545), "等级：6", 0.9)]).recognize(BLANK)
    assert r.recognizer_id == "fortress_level"
