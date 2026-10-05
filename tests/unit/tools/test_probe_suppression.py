# -*- coding: utf-8 -*-
"""tools/probe_suppression.py —— 帧源解析、权重解析、汇总统计。

不碰 torch/ultralytics：只测推理之外的那几件纯逻辑。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from tools import probe_suppression as P


def _mk_png(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.full((size[1], size[0], 3), 20, dtype=np.uint8)
    Image.fromarray(arr[:, :, ::-1]).save(path)


def test_weights_accepts_a_run_name():
    assert P._weights("gpu_1080_v9") == P.ROOT / "runs" / "gpu_1080_v9" / "weights" / "best.pt"


def test_weights_accepts_an_absolute_pt_path(tmp_path):
    p = tmp_path / "best.pt"
    assert P._weights(str(p)) == p


def test_weights_resolves_a_relative_pt_path_against_the_repo():
    assert P._weights("runs/x/best.pt") == P.ROOT / "runs" / "x" / "best.pt"


def test_rows_of_a_missing_label_file_is_empty(tmp_path):
    assert P._rows(tmp_path / "nope.txt") == []


def test_resolve_frames_from_a_directory(tmp_path):
    _mk_png(tmp_path / "a.png", (10, 10))
    _mk_png(tmp_path / "b.png", (10, 10))
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    assert [p.name for p in P._resolve_frames(tmp_path, tmp_path)] == ["a.png", "b.png"]


def test_resolve_frames_from_a_txt_list(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    lst = tmp_path / "frames.txt"
    lst.write_text(f"{a}\n\n{b}\n", encoding="utf-8")
    assert P._resolve_frames(lst, tmp_path) == [a, b]


def test_default_frames_picks_zero_label_non_native_only(tmp_path):
    ds = tmp_path / "dataset"
    _mk_png(ds / "images" / "crop_empty.png", (270, 210))     # 要：0 框 + 非标准尺寸
    _mk_png(ds / "images" / "crop_labeled.png", (270, 210))   # 不要：有标签
    _mk_png(ds / "images" / "full_empty.png", (1920, 1080))   # 不要：标准尺寸
    (ds / "labels").mkdir(parents=True)
    (ds / "labels" / "crop_labeled.txt").write_text("3 0.5 0.5 0.1 0.1\n", encoding="utf-8")
    assert [p.name for p in P._default_frames(ds)] == ["crop_empty.png"]


def test_default_frames_falls_back_to_the_backup_dir(tmp_path, capsys):
    ds = tmp_path / "dataset"
    _mk_png(ds / "images" / "crop_labeled.png", (270, 210))
    (ds / "labels").mkdir(parents=True)
    (ds / "labels" / "crop_labeled.txt").write_text("3 0.5 0.5 0.1 0.1\n", encoding="utf-8")
    bak = ds / "_emptyfix_backup_20261003-120000" / "images"
    _mk_png(bak / "scenes___z_join.png", (270, 210))
    got = P._default_frames(ds)
    assert [p.name for p in got] == ["scenes___z_join.png"]
    assert "备份目录" in capsys.readouterr().out


def test_summary_counts_fired_frames():
    rows = [{"peak": 0.0, "n": 0}, {"peak": 0.9, "n": 3}, {"peak": 0.05, "n": 0}]
    s = P._summary(rows, 3)
    assert s["fire"] == 1
    assert s["total"] == 3
    assert s["peak_max"] == 0.9
    assert s["peak_med"] == 0.05


def test_summary_on_no_frames_is_all_zero():
    assert P._summary([], 0) == {"fire": 0, "peak_med": 0.0, "peak_max": 0.0, "total": 0}
