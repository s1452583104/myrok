"""tools/auto_label_yolo.py 的全量重建护栏测试。

auto_label_yolo 是**全量重建**工具（截断写 train/val + 重建 dataset.yaml），而
dataset/ 现在是手工维护的（63 类方案 B + 手工追加帧）。跑一次没护栏 = 类表缩回
50 + 手工帧全丢，而且是静默的。这里锁住「会丢东西就必须报错」。
"""
from __future__ import annotations

from pathlib import Path

from tools.auto_label_yolo import _preflight_guard


def _write_yaml(out: Path, names: list[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    body = "names:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(names))
    (out / "dataset.yaml").write_text(body, encoding="utf-8")


def test_clean_run_reports_nothing(tmp_path: Path):
    img = tmp_path / "images" / "a.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")
    _write_yaml(tmp_path, ["alpha", "beta"])
    (tmp_path / "train.txt").write_text(str(img.resolve()) + "\n", encoding="utf-8")

    assert _preflight_guard(tmp_path, ["alpha", "beta"], {str(img.resolve())}) == []


def test_extra_classes_in_dataset_yaml_are_reported(tmp_path: Path):
    """dataset.yaml 有本次类表之外的类 → 那些类的标注会全部作废。"""
    _write_yaml(tmp_path, ["alpha", "hand_added"])
    problems = _preflight_guard(tmp_path, ["alpha"], set())
    assert len(problems) == 1
    assert "hand_added" in problems[0]


def test_rows_outside_this_run_are_reported(tmp_path: Path):
    """train/val 里有本次输出范围外的行 → 会被截断丢掉（手工追加帧就是这么没的）。"""
    keep = tmp_path / "images" / "keep.png"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"x")
    manual = tmp_path / "images" / "manual_frame.png"
    manual.write_bytes(b"y")
    (tmp_path / "train.txt").write_text(
        f"{keep.resolve()}\n{manual.resolve()}\n", encoding="utf-8")

    problems = _preflight_guard(tmp_path, [], {str(keep.resolve())})
    assert len(problems) == 1
    assert "1/2" in problems[0]
    assert "manual_frame.png" in problems[0]


def test_path_comparison_is_case_insensitive(tmp_path: Path):
    """Windows 路径大小写不敏感：同一文件不该被误判成「不在范围内」。"""
    img = tmp_path / "images" / "A.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")
    (tmp_path / "val.txt").write_text(str(img.resolve()) + "\n", encoding="utf-8")

    assert _preflight_guard(tmp_path, [], {str(img.resolve()).lower()}) == []
