"""验收脚本的纯函数：素材索引 + 「素材缺失 → SKIP 退出 0」。

不碰真实素材、不加载 OCR——整屏识别属于人工运行（`tools/quiz_acceptance.py`）。
"""
import pytest

from rok_assistant.core.recognizer import BBox
from tools import quiz_acceptance as qa


def _touch(path, name):
    (path / name).write_bytes(b"x")


def test_index_materials_maps_every_slot(tmp_path):
    for name in (
        "微信图片_20261024090446_10_63.jpg",     # 活动页
        "微信图片_20261024090447_11_63.jpg",     # Q4
        "微信图片_20261024090449_12_63.jpg",     # Q1
        "微信图片_20261024090450_13_63.jpg",     # Q2
        "微信图片_20261024090451_14_63.jpg",     # Q3
        "9212bd3a5b52816d9ae9ac8c6b264816.mp4",
        "d343aa6157e41c72e5a34e95c8443d45.mp4",
    ):
        _touch(tmp_path, name)
    found = qa.index_materials(tmp_path)
    assert set(found) == {"activity", "q1", "q2", "q3", "q4", "video1", "video2"}
    assert found["q1"].name.endswith("_12_63.jpg")


def test_index_materials_ignores_unrelated_files(tmp_path):
    _touch(tmp_path, "readme.txt")
    assert qa.index_materials(tmp_path) == {}


def test_index_materials_missing_directory_is_empty(tmp_path):
    assert qa.index_materials(tmp_path / "nope") == {}


def test_missing_materials_is_a_skip_not_a_failure(tmp_path):
    """`dati/` 不入库：素材缺失必须 SKIP + 退出码 0（spec §11）。

    这条同时是「不许在 main 里先加载 OCR 再判断素材」的锁：tmp_path 是空的，
    若 main 先建 `RapidOcrEngine()` 再判素材，这条会变慢到几秒（且更脆）。
    """
    assert qa.main([str(tmp_path)]) == 0


def test_unknown_flag_is_a_usage_error_not_a_material_path():
    """`--help`、拼错的 flag 不能被当成素材目录打印 SKIP 退出 0。"""
    assert qa.main(["--help"]) == 2
    assert qa.main(["--materials"]) == 2


def _bb(x1, y1, x2, y2):
    return BBox(x1, y1, x2, y2)


def test_entry_hit_reports_the_label_and_box_behind_a_point():
    enter = _bb(100, 100, 160, 140)
    practice = _bb(400, 430, 530, 468)
    blocks = [(enter, "进入", 0.90), (practice, "习题演练", 0.76)]
    assert qa.entry_hit(blocks, enter.center()) == ("进入", enter)
    assert qa.entry_hit(blocks, practice.center()) == ("习题演练", practice)
    assert qa.entry_hit(blocks, (1, 2)) == (None, None)
    assert qa.entry_hit(blocks, None) == (None, None)


def test_practice_card_row_rejects_the_header():
    """栏目头在卡片行上方且更高；选中它说明又退回了按高度取块的老行为。"""
    header = _bb(1547, 388, 1688, 428)
    row = _bb(399, 431, 530, 468)
    blocks = [(header, "习题演练", 0.70), (row, "习题演练", 0.76),
              (_bb(1500, 560, 1800, 600), "每日习题演练来获取奖励", 0.95)]
    assert qa.is_practice_card_row(row, blocks) is True
    assert qa.is_practice_card_row(header, blocks) is False
