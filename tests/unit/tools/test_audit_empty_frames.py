"""tools/audit_empty_frames.py 的裁决与落盘测试。

这里锁两件事，判错哪个方向都有害：

1. **该撤的别放过**——0 框帧是假负样本，留着教模型漏检。尤其是「与有标注的孪生
   帧近乎同图」那种：同一画面一边标了 `warning_panel`、一边 0 框，等于拿同一片
   像素教两个互斥答案。
2. **不该撤的一根汗毛别动**——带标注的裁剪帧（`sort_selector` / `sort_opt_*` 的
   唯一来源）绝不能因为「尺寸非标准」被带走。判据必须是「0 行标签」，不是「尺寸」。

整屏帧的近重复只是**概率证据**，所以默认不动：`--drop` 点名才撤。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from tools.audit_empty_frames import NATIVE, scan, main

CROP = (270, 210)


def _mk_frame(dataset: Path, stem: str, size: tuple[int, int],
              rows: list[str], color=(10, 10, 10)):
    (dataset / "images").mkdir(parents=True, exist_ok=True)
    (dataset / "labels").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(dataset / "images" / f"{stem}.png")
    (dataset / "labels" / f"{stem}.txt").write_text(
        "\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def _mk_dataset(tmp_path: Path) -> Path:
    d = tmp_path / "dataset"
    (d / "images").mkdir(parents=True)
    (d / "labels").mkdir(parents=True)
    (d / "dataset.yaml").write_text("names:\n  0: join_btn\n  1: warning_panel\n",
                                    encoding="utf-8")
    (d / "train.txt").write_text("", encoding="utf-8")
    (d / "val.txt").write_text("", encoding="utf-8")
    return d


# --- 分组判据 -------------------------------------------------------------

def test_crop_frame_with_no_labels_goes_to_the_crop_group(tmp_path: Path):
    """模板素材裁剪图混进了训练集：0 行标签 + 非 1920x1080。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "scenes___z_join", CROP, [])

    crops, fulls = scan(d)

    assert [f.stem for f in crops] == ["scenes___z_join"]
    assert crops[0].verdict == "crop" and crops[0].is_crop
    assert fulls == []


def test_labeled_crop_frame_is_not_touched(tmp_path: Path):
    """sort_selector / sort_opt_* 的实例 100% 来自裁剪帧——删了就归零。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "manual4_sort_open_nearest_a", CROP, ["0 0.5 0.5 0.2 0.1"])

    crops, fulls = scan(d)

    assert crops == [] and fulls == []


def test_missing_label_file_counts_as_an_empty_frame(tmp_path: Path):
    """标签文件整个缺失也是 0 框帧——按 labels/ 遍历会把它漏掉。"""
    d = _mk_dataset(tmp_path)
    Image.new("RGB", CROP, (10, 10, 10)).save(d / "images" / "no_label_file.png")

    crops, _ = scan(d)

    assert [f.stem for f in crops] == ["no_label_file"]


# --- 近重复（整屏组）------------------------------------------------------

def test_empty_fullscreen_frame_with_a_labeled_twin_is_flagged(tmp_path: Path):
    """mad≈0.008 的同图孪生帧：一边标了 warning_panel，一边 0 框 → 疑似漏标。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "twin_labeled", NATIVE, ["1 0.5 0.1 0.2 0.1"], color=(10, 10, 10))
    _mk_frame(d, "twin_empty", NATIVE, [], color=(12, 12, 12))

    _, fulls = scan(d)

    assert [f.stem for f in fulls] == ["twin_empty"]
    f = fulls[0]
    assert f.verdict == "false_negative"
    assert f.twin == "twin_labeled"
    assert f.twin_classes == ("warning_panel",)
    assert f.twin_mad < 0.03


def test_empty_fullscreen_frame_without_a_twin_is_background(tmp_path: Path):
    """画面完全不同的 0 框帧是合法背景样本，必须留着。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "twin_labeled", NATIVE, ["1 0.5 0.1 0.2 0.1"], color=(0, 0, 0))
    _mk_frame(d, "unrelated_empty", NATIVE, [], color=(255, 255, 255))

    _, fulls = scan(d)

    assert [f.verdict for f in fulls] == ["background"]
    assert fulls[0].twin_mad > 0.03


def test_only_fullscreen_frames_are_compared_for_near_duplicates(tmp_path: Path):
    """裁剪帧的 mad 高低不说明任何事——归一化坐标只在同尺寸帧间可迁移。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "crop_labeled", CROP, ["0 0.5 0.5 0.2 0.1"], color=(10, 10, 10))
    _mk_frame(d, "full_empty", NATIVE, [], color=(10, 10, 10))

    _, fulls = scan(d)

    # 颜色一模一样，但一个是裁剪帧 —— 不能拿它当孪生
    assert [f.verdict for f in fulls] == ["background"]
    assert fulls[0].nearest == ""


# --- 落盘 -----------------------------------------------------------------

def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch):
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "scenes___z_join", CROP, [])
    (d / "train.txt").write_text(
        str(d / "images" / "scenes___z_join.png") + "\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["audit_empty_frames.py", "--dataset", str(d)])

    assert main() == 0

    assert (d / "images" / "scenes___z_join.png").exists()
    assert not list(d.glob("_emptyfix_backup_*"))
    assert (d / "train.txt").read_text(encoding="utf-8").strip() != ""


def test_apply_removes_crop_frames_and_backs_up_the_images(tmp_path, monkeypatch):
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "scenes___z_join", CROP, [])
    _mk_frame(d, "manual4_sort_open_nearest_a", CROP, ["0 0.5 0.5 0.2 0.1"])
    (d / "train.txt").write_text(
        "\n".join(str(d / "images" / f"{s}.png") for s in
                  ("scenes___z_join", "manual4_sort_open_nearest_a")) + "\n",
        encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["audit_empty_frames.py", "--dataset", str(d),
                                     "--apply"])

    assert main() == 0

    backups = list(d.glob("_emptyfix_backup_*"))
    assert len(backups) == 1
    assert (backups[0] / "images" / "scenes___z_join.png").exists()
    assert (backups[0] / "labels" / "scenes___z_join.txt").exists()

    assert not (d / "images" / "scenes___z_join.png").exists()
    assert not (d / "labels" / "scenes___z_join.txt").exists()
    # 带标注的裁剪帧留在原地，标签一字未动
    assert (d / "images" / "manual4_sort_open_nearest_a.png").exists()
    assert (d / "labels" / "manual4_sort_open_nearest_a.txt").read_text(
        encoding="utf-8").strip() == "0 0.5 0.5 0.2 0.1"
    # train.txt 只剩那一行
    left = (d / "train.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(left) == 1 and "manual4_sort_open_nearest_a" in left[0]


def test_keep_flag_exempts_a_crop_frame(tmp_path: Path, monkeypatch):
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "scenes___z_join", CROP, [])
    monkeypatch.setattr("sys.argv", ["audit_empty_frames.py", "--dataset", str(d),
                                     "--apply", "--keep", "scenes___z_join"])

    assert main() == 0

    assert (d / "images" / "scenes___z_join.png").exists()


def test_drop_flag_removes_a_named_fullscreen_frame(tmp_path: Path, monkeypatch):
    """整屏帧是概率证据，脚本不替人拍板——点名才撤。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "twin_labeled", NATIVE, ["1 0.5 0.1 0.2 0.1"], color=(10, 10, 10))
    _mk_frame(d, "twin_empty", NATIVE, [], color=(12, 12, 12))
    monkeypatch.setattr("sys.argv", ["audit_empty_frames.py", "--dataset", str(d),
                                     "--apply", "--drop", "twin_empty"])

    assert main() == 0

    assert not (d / "images" / "twin_empty.png").exists()
    assert (d / "images" / "twin_labeled.png").exists()


def test_drop_rejects_a_stem_that_is_not_an_empty_frame(tmp_path: Path, monkeypatch):
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "scenes___z_join", CROP, [])
    monkeypatch.setattr("sys.argv", ["audit_empty_frames.py", "--dataset", str(d),
                                     "--apply", "--drop", "twin_labeled"])

    assert main() == 2
    assert (d / "images" / "scenes___z_join.png").exists()
