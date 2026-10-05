# -*- coding: utf-8 -*-
"""tools/view_dataset.py —— 数据集标注查看器的解析与筛选。"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from tools import view_dataset as V


def _mk_frame(dataset: Path, stem: str, size: tuple[int, int], rows: list[str],
              color=(10, 10, 10)) -> None:
    """造一帧：图 + 标签。rows 为空则不写标签文件（= 0 框帧的另一种形态）。"""
    (dataset / "images").mkdir(parents=True, exist_ok=True)
    (dataset / "labels").mkdir(parents=True, exist_ok=True)
    arr = np.full((size[1], size[0], 3), color, dtype=np.uint8)
    Image.fromarray(arr[:, :, ::-1]).save(dataset / "images" / f"{stem}.png")
    if rows:
        (dataset / "labels" / f"{stem}.txt").write_text("\n".join(rows) + "\n",
                                                        encoding="utf-8")


def _mk_dataset(tmp_path: Path) -> Path:
    d = tmp_path / "dataset"
    _mk_frame(d, "a_full", (1920, 1080), ["3 0.5 0.5 0.1 0.1"])
    _mk_frame(d, "b_full_empty", (1920, 1080), [])
    _mk_frame(d, "c_crop", (270, 210), ["7 0.5 0.5 0.4 0.4"])
    _mk_frame(d, "d_crop_empty", (100, 100), [])
    (d / "train.txt").write_text(str(d / "images" / "a_full.png") + "\n"
                                 + str(d / "images" / "b_full_empty.png") + "\n"
                                 + str(d / "images" / "d_crop_empty.png") + "\n",
                                 encoding="utf-8")
    (d / "val.txt").write_text(str(d / "images" / "c_crop.png") + "\n",
                               encoding="utf-8")
    (d / "dataset.yaml").write_text(
        "names:\n  3: level_minus\n  7: sort_selector\n", encoding="utf-8")
    return d


def test_read_rows_parses_yolo_lines(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("3 0.5 0.25 0.1 0.2\n7 0.1 0.2 0.3 0.4\n", encoding="utf-8")
    rows = V._read_rows(p)
    assert rows == [(3, 0.5, 0.25, 0.1, 0.2), (7, 0.1, 0.2, 0.3, 0.4)]


def test_read_rows_missing_file_is_an_empty_frame(tmp_path):
    assert V._read_rows(tmp_path / "nope.txt") == []


def test_dets_converts_normalized_to_pixels():
    dets = V._dets([(3, 0.5, 0.5, 0.1, 0.1)], {3: "level_minus"}, 1920, 1080)
    assert dets[0]["xyxy"] == (864, 486, 1056, 594)
    assert dets[0]["name"] == "level_minus"
    assert dets[0]["cid"] == 3


def test_dets_falls_back_to_the_id_when_the_name_is_unknown():
    dets = V._dets([(9, 0.5, 0.5, 0.1, 0.1)], {}, 100, 100)
    assert dets[0]["name"] == "9"


def test_collect_returns_every_frame_by_default(tmp_path):
    d = _mk_dataset(tmp_path)
    frames, names = V._collect(d, "all", "", False)
    assert [f[0] for f in frames] == ["a_full", "b_full_empty", "c_crop",
                                      "d_crop_empty"]
    assert names == {3: "level_minus", 7: "sort_selector"}


def test_collect_filters_by_split(tmp_path):
    d = _mk_dataset(tmp_path)
    assert [f[0] for f in V._collect(d, "val", "", False)[0]] == ["c_crop"]
    assert [f[0] for f in V._collect(d, "train", "", False)[0]] == [
        "a_full", "b_full_empty", "d_crop_empty"]


def test_collect_only_empty_keeps_zero_box_frames(tmp_path):
    d = _mk_dataset(tmp_path)
    frames, _ = V._collect(d, "all", "", True)
    assert [f[0] for f in frames] == ["b_full_empty", "d_crop_empty"]
    assert all(not f[3] for f in frames)


def test_collect_filters_by_substring(tmp_path):
    d = _mk_dataset(tmp_path)
    assert [f[0] for f in V._collect(d, "all", "crop", False)[0]] == [
        "c_crop", "d_crop_empty"]


def test_draw_scales_the_image_and_marks_the_box(tmp_path):
    d = _mk_dataset(tmp_path)
    img = cv2.imread(str(d / "images" / "a_full.png"))
    dets = V._dets([(3, 0.5, 0.5, 0.1, 0.1)], {3: "level_minus"}, 1920, 1080)
    out = V._draw(img, dets, 0.5)
    assert out.shape[:2] == (540, 960)               # 按 scale 缩了
    x1, y1 = int(864 * 0.5), int(486 * 0.5)
    assert tuple(int(v) for v in out[y1, x1]) != (10, 10, 10)   # 框角被画上了


def test_no_window_without_out_is_an_error(tmp_path, monkeypatch):
    d = _mk_dataset(tmp_path)
    monkeypatch.setattr(sys, "argv", ["view_dataset.py", "--dataset", str(d),
                                      "--no-window"])
    assert V.main() == 2


def test_no_window_exports_every_frame(tmp_path, monkeypatch):
    d = _mk_dataset(tmp_path)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["view_dataset.py", "--dataset", str(d),
                                      "--no-window", "--out", str(out)])
    assert V.main() == 0
    assert sorted(p.name for p in out.glob("*.png")) == [
        "a_full.png", "b_full_empty.png", "c_crop.png", "d_crop_empty.png"]
    assert cv2.imread(str(out / "d_crop_empty.png")).shape[:2] == (400, 400)


def test_no_matching_frames_is_not_an_error(tmp_path, monkeypatch, capsys):
    d = _mk_dataset(tmp_path)
    monkeypatch.setattr(sys, "argv", ["view_dataset.py", "--dataset", str(d),
                                      "--filter", "zzz-no-such-frame",
                                      "--no-window", "--out",
                                      str(tmp_path / "out")])
    assert V.main() == 0
    assert "没有匹配的帧" in capsys.readouterr().out
