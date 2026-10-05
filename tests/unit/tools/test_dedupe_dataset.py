"""tools/dedupe_dataset.py 的重复帧挑选逻辑测试。

同一张图出现两次、标注又不一致时，模型对同一份输入同时收到「有 X」和「没有 X」
两种监督——比多算一张图有害得多。幸存者必须挑标注更全的那份。
"""
from __future__ import annotations

from pathlib import Path

from tools.dedupe_dataset import find_duplicate_groups, main, pick_survivor


def _mk(images_dir: Path, labels_dir: Path, stem: str, content: bytes, n_labels: int):
    (images_dir / f"{stem}.png").write_bytes(content)
    lines = "\n".join(f"0 0.5 0.5 0.1 0.1" for _ in range(n_labels))
    (labels_dir / f"{stem}.txt").write_text(lines, encoding="utf-8")


def test_identical_content_is_grouped(tmp_path: Path):
    images, labels = tmp_path / "images", tmp_path / "labels"
    images.mkdir(), labels.mkdir()
    _mk(images, labels, "a", b"same", 1)
    _mk(images, labels, "b", b"same", 1)
    _mk(images, labels, "c", b"other", 1)

    assert find_duplicate_groups(images) == [["a", "b"]]


def test_no_duplicates_returns_empty(tmp_path: Path):
    images, labels = tmp_path / "images", tmp_path / "labels"
    images.mkdir(), labels.mkdir()
    _mk(images, labels, "a", b"1", 1)
    _mk(images, labels, "b", b"2", 1)

    assert find_duplicate_groups(images) == []


def test_survivor_is_the_richer_label_set(tmp_path: Path):
    """两遍标注同一张图往往互补，留标注少的那份等于丢标注。"""
    images, labels = tmp_path / "images", tmp_path / "labels"
    images.mkdir(), labels.mkdir()
    _mk(images, labels, "sparse", b"same", 2)
    _mk(images, labels, "rich", b"same", 7)

    assert pick_survivor(["sparse", "rich"], labels) == "rich"


def test_survivor_tie_break_is_deterministic(tmp_path: Path):
    images, labels = tmp_path / "images", tmp_path / "labels"
    images.mkdir(), labels.mkdir()
    _mk(images, labels, "zzz", b"same", 3)
    _mk(images, labels, "aaa", b"same", 3)

    # 并列时取名字最小的，保证同一份数据每次跑出同样的结果
    assert pick_survivor(["zzz", "aaa"], labels) == "aaa"
    assert pick_survivor(["aaa", "zzz"], labels) == "aaa"


def test_survivor_counts_missing_label_file_as_zero(tmp_path: Path):
    images, labels = tmp_path / "images", tmp_path / "labels"
    images.mkdir(), labels.mkdir()
    _mk(images, labels, "has_labels", b"same", 1)
    (images / "no_labels.png").write_bytes(b"same")

    assert pick_survivor(["has_labels", "no_labels"], labels) == "has_labels"


def test_apply_backs_up_the_images_of_removed_frames(tmp_path, monkeypatch):
    """删帧会连图一起删，图不在 labels/ 里。

    实测踩过（prune_labels）：只备份 labels，8 帧的图删掉后 recordings/ 里也没有
    原件，只剩标注无从复原。本工具同样必须连原图一起进备份。
    """
    d = tmp_path / "dataset"
    images, labels = d / "images", d / "labels"
    images.mkdir(parents=True), labels.mkdir()
    _mk(images, labels, "a", b"same", 1)
    _mk(images, labels, "b", b"same", 1)
    (d / "train.txt").write_text(
        "\n".join(str(images / f"{s}.png") for s in ("a", "b")) + "\n",
        encoding="utf-8")
    (d / "val.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["dedupe_dataset.py", "--dataset", str(d),
                                     "--apply"])

    assert main() == 0

    backups = list(d.glob("_dedupe_backup_*"))
    assert len(backups) == 1
    # 幸存者是 a（名字最小、标注并列）→ 备份里必须有 b 的原图
    assert (backups[0] / "images" / "b.png").exists()
    assert (backups[0] / "labels" / "b.txt").exists()
    assert not (images / "b.png").exists()
    assert (images / "a.png").exists()
