"""tools/fix_zhaizi_level_labels.py 的锚点判据与整库扫描测试。

锁的是 2026-09-24 用户报的「寨子等级 1-6 级不识别」的根因：`zhaizi_level_text`
的标注分裂成两套尺寸——紧框 ~95x30 只圈「等级：N」，宽框 286~802px 把后面那句
「您的城市附近暂未找到符合条件的野蛮人城寨。」一起圈了进来。同一位置两种差 8 倍
的框，YOLO 只能回归到折中：实测 v8 在实机 1~10 级帧上，只在 7/8/9/10 出框且置信度
仅 0.12~0.28（默认阈值 0.5 下等于不出框），1~6 级一个框都没有。

判据必须是「OCR 块文字**整块**是 `等级：N`」——含「等级」的长句一律不算锚点。
这不是洁癖：另有两帧（世界地图上的城寨信息弹窗）的预标注正是锚到了
「推荐兵力：1,400,000等级4的战斗单位集结进攻」这行里的「等级4」。放松判据等于
把这两条污染再放进来。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from rok_assistant.core.recognizer import BBox
from tools.fix_zhaizi_level_labels import (
    MAX_W_PX,
    PAD,
    anchor_from_blocks,
    main,
    scan,
)

FULL = (1920, 1080)


class _FakeEngine:
    """返回预设文本块；记录被调了几次，用来验证紧框帧根本不该惊动 OCR。"""

    def __init__(self, blocks=()):
        self._blocks = list(blocks)
        self.calls = 0

    def detect_text(self, img):
        self.calls += 1
        return self._blocks


# --- 锚点判据 -------------------------------------------------------------

def test_clean_level_block_is_the_anchor():
    """搜索面板的等级文本就是一个独立的「等级：N」块。"""
    got = anchor_from_blocks([(100, 500, 200, 530, "等级：7")])
    assert got == (100 - PAD, 500 - PAD, 200 + PAD, 530 + PAD)


def test_anchor_rejects_the_rally_line_containing_a_level():
    """真实污染：弹窗提示行里的「等级4」不是搜索面板的等级文本。

    这两条（220414-378 / 220422-847）的预标注就锚在这行上，直接删——改成紧框
    也是错的，因为画面里根本没有搜索面板。
    """
    assert anchor_from_blocks([
        (413, 596, 940, 620, "推荐兵力：1,400,000等级4的战斗单位集结进攻")]) is None


def test_anchor_requires_the_whole_block_to_be_the_level_text():
    """「等级：3 您的城市附近暂未…」整块也不合格——它把提示文字也圈进去了。"""
    assert anchor_from_blocks([(156, 520, 959, 545, "等级：3 您的城市附近暂未找到符合条")]) is None


@pytest.mark.parametrize("text", ["等级：1", "等级:10", "等级 ： 8", "等级： 0"])
def test_anchor_tolerates_colon_and_space_variants(text):
    """OCR 出来的冒号半角/全角、有无空格都见过，别因为一个空格就不认。"""
    assert anchor_from_blocks([(10, 20, 110, 50, text)]) is not None


def test_anchor_takes_the_leftmost_when_several_qualify():
    """取最靠左的合格块（等级数字在「等级：」右侧的布局保证不该有多块）。"""
    got = anchor_from_blocks([(300, 500, 400, 530, "等级：3"),
                              (100, 500, 200, 530, "等级：3")])
    assert got[0] == 100 - PAD


def test_anchor_is_none_when_nothing_qualifies():
    assert anchor_from_blocks([(10, 10, 60, 40, "您的城市附近暂未找到")]) is None
    assert anchor_from_blocks([]) is None


# --- 整库扫描 -------------------------------------------------------------

def _mk_frame(dataset: Path, stem: str, rows: list[str]):
    (dataset / "images").mkdir(parents=True, exist_ok=True)
    (dataset / "labels").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", FULL).save(dataset / "images" / f"{stem}.png")
    (dataset / "labels" / f"{stem}.txt").write_text("\n".join(rows) + "\n",
                                                    encoding="utf-8")


def _mk_dataset(tmp_path: Path) -> Path:
    d = tmp_path / "dataset"
    d.mkdir()
    (d / "dataset.yaml").write_text("names:\n  0: search_icon\n  52: zhaizi_level_text\n",
                                    encoding="utf-8")
    (d / "train.txt").write_text("", encoding="utf-8")
    (d / "val.txt").write_text("", encoding="utf-8")
    return d


def _row(cid: int, x1: int, y1: int, x2: int, y2: int) -> str:
    return (f"{cid} {(x1 + x2) / 2 / 1920:.6f} {(y1 + y2) / 2 / 1080:.6f} "
            f"{(x2 - x1) / 1920:.6f} {(y2 - y1) / 1080:.6f}")


def test_wide_label_is_retightened_to_the_ocr_anchor(tmp_path: Path):
    """801px 的宽框（等级文本 + 提示文字）要改成 ~100px 的紧框。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "wide", [_row(52, 157, 523, 958, 544)])
    eng = _FakeEngine([(BBox(400, 45, 495, 74), "等级：1", 0.99)])  # ROI 内坐标

    fixes, emptied = scan(d, engine=eng)

    assert [f.action for f in fixes] == ["retighten"]
    x1, y1, x2, y2 = fixes[0].new_px
    # ROI 左上 (100, 470) 要加回去：OCR 块是 ROI 局部坐标
    assert (x1, y1, x2, y2) == (500 - PAD, 515 - PAD, 595 + PAD, 544 + PAD)
    assert emptied == []


def test_frame_without_a_clean_anchor_gets_the_label_dropped(tmp_path: Path):
    """弹窗帧：画面里没有搜索面板的等级文本，锚点找不到 → 整条删。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "popup", [_row(0, 40, 763, 136, 859),
                           _row(52, 413, 584, 940, 609)])
    eng = _FakeEngine([(BBox(313, 126, 840, 150), "推荐兵力：1,400,000等级4的战斗单位集结进攻", 0.9)])

    fixes, _emptied = scan(d, engine=eng)

    assert [f.action for f in fixes] == ["drop"]
    assert fixes[0].new_px is None


def test_tight_labels_are_not_touched_and_do_not_need_ocr(tmp_path: Path):
    """现有 33 条紧框一律不碰——把好标注拿去重算就是自找的漂移。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "tight", [_row(52, 473, 515, 568, 545)])   # 95px
    eng = _FakeEngine([])

    fixes, emptied = scan(d, engine=eng)

    assert fixes == [] and emptied == []
    assert eng.calls == 0, "紧框帧不该跑 OCR"


def test_threshold_sits_in_the_gap_between_tight_and_wide():
    """200 是筛可疑项的阈值，不是判据：现有紧框最宽 123，最小宽框 286。"""
    assert 123 < MAX_W_PX < 286


def test_apply_backs_up_labels_before_rewriting(tmp_path: Path, monkeypatch):
    """改之前整份 labels 必须进备份——回滚靠它。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "wide", [_row(52, 157, 523, 958, 544)])
    monkeypatch.setattr("sys.argv", ["fix_zhaizi_level_labels.py",
                                     "--dataset", str(d), "--apply"])
    monkeypatch.setattr("tools.fix_zhaizi_level_labels.scan",
                        lambda *a, **k: ([_retighten_fix()], []))

    assert main() == 0

    backups = list(d.glob("_levelfix_backup_*"))
    assert len(backups) == 1
    assert (backups[0] / "labels" / "wide.txt").exists()
    # 改的是第 0 行，写回的是紧框（宽 95px = 500..595，不再含 PAD 之外的提示文字）
    written = (d / "labels" / "wide.txt").read_text(encoding="utf-8").split()
    assert written[0] == "52"
    assert float(written[3]) * 1920 == pytest.approx(95, abs=0.5)
    # 备份里必须还是那条 801px 的宽框 —— 回滚靠它
    old = (backups[0] / "labels" / "wide.txt").read_text(encoding="utf-8").split()
    assert float(old[3]) * 1920 == pytest.approx(801, abs=0.5)


def _retighten_fix():
    from tools.fix_zhaizi_level_labels import Fix
    return Fix("wide", 0, "retighten", (157, 523, 958, 544), (500, 515, 595, 544), "")
