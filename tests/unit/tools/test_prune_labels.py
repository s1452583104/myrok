"""tools/prune_labels.py 的裁决规则测试。

这里锁的是「什么样的标注在运行时永远用不上」。判错了两个方向都有害：
放行了越界框 → 模型被教去认一个 ROI 门控会丢掉的东西；误删了合法框 →
把弱类本来就少的样本再削一层。判 ROI 的判法必须与
`YoloClassAdapter.recognize`（拿框中心判）逐字一致，否则会出现
「标注留着、运行时却永远不采纳」的静默浪费。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from tools.prune_labels import (
    DEGENERATE_FRACTION,
    Violation,
    _fullscreen_classes,
    judge,
    load_class_rois,
    main,
    scan,
)

ROI = [1700, 150, 1920, 850]
FULL = (1920, 1080)
CROP = (1278, 719)


# --- 单条裁决 -------------------------------------------------------------

def test_degenerate_box_is_flagged():
    """框占满整幅 = 教模型「整张图就是它」，全屏推理时永不成立。"""
    v = judge("sort_selector", 0.5, 0.5, 0.99, 0.91, (261, 35), None)
    assert v is not None and v.reason == "退化框"


def test_ordinary_box_is_not_degenerate():
    """sort_selector 的正常框：1278x719 帧里 264x30。"""
    assert judge("sort_selector", 0.244, 0.149, 0.207, 0.042, CROP, None) is None


def test_degeneracy_needs_both_axes():
    """整条顶栏（宽满、高不满）是合法标注，不能当退化框删掉。"""
    assert DEGENERATE_FRACTION == 0.9
    assert judge("x", 0.5, 0.17, 1.0, 0.2, FULL, None) is None


def test_crop_frame_label_for_roi_class_is_flagged():
    """ROI 是 1920x1080 绝对像素，裁剪帧的归一化坐标不对应屏幕位置。"""
    v = judge("queue_battle_icon", 0.485, 0.28, 0.05, 0.07, CROP, ROI)
    assert v is not None and v.reason == "非全屏帧"


def test_crop_frame_label_for_roi_less_class_is_kept():
    """没有 ROI 的类不走这条：sort_selector 只有裁剪帧，删了就归零。"""
    assert judge("sort_selector", 0.244, 0.149, 0.207, 0.042, CROP, None) is None


def test_center_outside_roi_is_flagged():
    """全屏帧上 70x69 @cx960 —— 战争列表行图标，运行时会被 ROI 门控丢掉。"""
    v = judge("queue_battle_icon", 0.5, 0.296, 0.036, 0.064, FULL, ROI)
    assert v is not None and v.reason == "越出ROI"


def test_center_inside_roi_is_kept():
    """队列栏图标 33x33 @(1868,328)：ROI 内，留着。"""
    assert judge("queue_battle_icon", 1868 / 1920, 328 / 1080, 0.017, 0.031,
                 FULL, ROI) is None


def test_roi_judgement_uses_box_center_not_corner():
    """与 YoloClassAdapter.recognize 对齐：判的是中心。

    这条框左上角在 ROI 外、中心在 ROI 内 —— 运行时会被采纳，所以不能删。
    """
    roi = [100, 100, 300, 300]
    cx, cy = 0.08, 0.12          # 中心 (153.6, 129.6)，在 [100,300) 内
    w, h = 0.1, 0.1              # 框左上角 (57.6, 75.6)，在 ROI 外
    assert judge("x", cx, cy, w, h, FULL, roi) is None


# --- manifest 读取 --------------------------------------------------------

def test_load_class_rois_maps_classes_absent_from_manifest_to_none(tmp_path: Path):
    ds = tmp_path / "dataset.yaml"
    ds.write_text("names:\n  0: with_roi\n  1: no_roi\n", encoding="utf-8")
    mf = tmp_path / "manifest.yaml"
    mf.write_text("templates:\n  - id: with_roi\n    roi: [1, 2, 3, 4]\n",
                  encoding="utf-8")

    rois = load_class_rois(ds, mf)
    assert rois["with_roi"] == [1, 2, 3, 4]
    assert rois["no_roi"] is None


# --- 整库扫描 -------------------------------------------------------------

def _mk_frame(dataset: Path, stem: str, size: tuple[int, int], rows: list[str]):
    (dataset / "images").mkdir(parents=True, exist_ok=True)
    (dataset / "labels").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size).save(dataset / "images" / f"{stem}.png")
    (dataset / "labels" / f"{stem}.txt").write_text(
        "\n".join(rows) + "\n", encoding="utf-8")


def _mk_dataset(tmp_path: Path) -> Path:
    d = tmp_path / "dataset"
    d.mkdir()
    (d / "dataset.yaml").write_text("names:\n  0: roi_cls\n  1: plain_cls\n",
                                    encoding="utf-8")
    return d


def test_scan_flags_emptied_frames(tmp_path: Path):
    """摘完一条不剩的帧必须报出来：0 框帧是负样本，而它其实是正样本。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "only_bad", FULL, ["0 0.5 0.296 0.036 0.064"])   # 越界，唯一一条
    _mk_frame(d, "has_good", FULL, ["0 0.97 0.3 0.017 0.031",      # ROI 内
                                    "0 0.5 0.296 0.036 0.064"])    # 越界

    violations, emptied = scan(d, {"roi_cls"}, rois={"roi_cls": ROI, "plain_cls": None})

    assert emptied == ["only_bad"]
    assert len(violations) == 2


def test_scan_ignores_classes_not_asked_for(tmp_path: Path):
    """只动点名的类：别的类里也有同类问题，但改动面要由调用方决定。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "other", FULL, ["0 0.5 0.296 0.036 0.064"])

    violations, emptied = scan(d, {"plain_cls"}, rois={"roi_cls": ROI, "plain_cls": None})

    assert violations == [] and emptied == []


def test_scan_keeps_roi_less_class_boxes_on_crops(tmp_path: Path):
    """整库扫描下也要保住 sort_selector 这类「只有裁剪帧」的类。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "crop", CROP, ["1 0.244 0.149 0.207 0.042"])

    violations, emptied = scan(d, {"plain_cls"}, rois={"plain_cls": None})

    assert violations == [] and emptied == []


# --- 无 ROI 类的「两套坐标系」判据 ----------------------------------------
#
# 2026-09-25：`sort_selector` / `sort_opt_*` 的 18 条标注全在 279x162 这类裁剪帧
# 上，`roi is None` 的早退把它们全保了下来。在整屏帧上补标之后，同一个类就有了
# 两套归一化基准——框的宽高比能差一个数量级，YOLO 只能回归到折中，实机一个都检
# 不出（寨子宽框同款）。判据是「这个类在整屏帧上另有可用实例」，不是「无 ROI 就删」。

def test_crop_label_is_flagged_when_the_class_also_has_fullscreen_labels():
    v = judge("sort_selector", 0.244, 0.149, 0.207, 0.042, CROP, None,
              has_fullscreen=True)
    assert v is not None and v.reason == "非全屏帧"
    assert "两套坐标系" in v.detail


def test_crop_label_survives_when_the_class_has_no_fullscreen_labels():
    """保守默认：判不了就不删。这条锁住 `judge` 的 has_fullscreen 默认值。"""
    assert judge("sort_selector", 0.244, 0.149, 0.207, 0.042, CROP, None) is None
    assert judge("sort_selector", 0.244, 0.149, 0.207, 0.042, CROP, None,
                 has_fullscreen=False) is None


def test_fullscreen_label_is_unaffected_by_the_fullscreen_flag():
    """判据只针对裁剪帧；整屏帧上无 ROI 的类照留。"""
    assert judge("sort_selector", 0.244, 0.149, 0.207, 0.042, FULL, None,
                 has_fullscreen=True) is None


def test_fullscreen_evidence_excludes_degenerate_boxes():
    """退化框自己就要被摘，不能拿它证明「这个类在整屏帧上站得住」。"""
    names = {1: "plain_cls"}
    frames = [("full", FULL, [["1", "0.5", "0.5", "0.99", "0.91"]]),
              ("crop", CROP, [["1", "0.244", "0.149", "0.207", "0.042"]])]

    assert _fullscreen_classes(frames, names, {"plain_cls"}) == set()


def test_fullscreen_evidence_needs_a_fullscreen_frame():
    """裁剪帧上的同类实例不算证据——那正是要被撤的那批。"""
    names = {1: "plain_cls", 0: "roi_cls"}
    frames = [("crop", CROP, [["1", "0.244", "0.149", "0.207", "0.042"]]),
              ("full", FULL, [["0", "0.97", "0.3", "0.017", "0.031"]])]

    assert _fullscreen_classes(frames, names, {"plain_cls"}) == set()
    assert _fullscreen_classes(frames, names, {"roi_cls"}) == {"roi_cls"}
    # 没点名的类不参与：`--classes` 之外的行不该被这条判据带下水
    assert _fullscreen_classes(frames, names, set()) == set()


def test_scan_withdraws_crop_frames_once_the_class_has_fullscreen_labels(tmp_path: Path):
    """补标后重跑：裁剪帧整幅只剩这类标注 → 摘空 → 连帧一起撤。"""
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "crop", CROP, ["1 0.244 0.149 0.207 0.042"])
    _mk_frame(d, "full", FULL, ["1 0.244 0.149 0.207 0.042"])

    violations, emptied = scan(d, {"plain_cls"}, rois={"plain_cls": None})

    assert emptied == ["crop"]
    assert [v.frame for v in violations] == ["crop"]


def test_apply_backs_up_the_images_of_removed_frames(tmp_path, monkeypatch):
    """撤帧会连图一起删，图不在 labels/ 里。

    实测踩过：只备份 labels，8 帧的图删掉后 recordings/ 里也没有原件，只剩标注
    无从复原——那 2 帧全屏预警图到底是不是「同一个面板换了位置」再也没法验。
    撤帧必须连原图一起进备份。
    """
    d = _mk_dataset(tmp_path)
    _mk_frame(d, "only_bad", FULL, ["0 0.5 0.296 0.036 0.064"])   # 唯一一条且越界
    (d / "train.txt").write_text(str(d / "images" / "only_bad.png") + "\n",
                                 encoding="utf-8")
    (d / "val.txt").write_text("", encoding="utf-8")
    mf = tmp_path / "manifest.yaml"
    mf.write_text(f"templates:\n  - id: roi_cls\n    roi: {ROI}\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["prune_labels.py", "--dataset", str(d),
                                     "--manifest", str(mf),
                                     "--classes", "roi_cls", "--apply"])

    assert main() == 0

    backups = list(d.glob("_prune_backup_*"))
    assert len(backups) == 1
    assert (backups[0] / "images" / "only_bad.png").exists()
    assert (backups[0] / "labels" / "only_bad.txt").exists()
    assert not (d / "images" / "only_bad.png").exists()
    # 撤帧要同时摘掉 train/val 行；_write_list 对空表写的是一个换行
    assert (d / "train.txt").read_text(encoding="utf-8").strip() == ""


def test_violation_detail_names_the_frame_class_and_reason():
    v = judge("queue_battle_icon", 0.5, 0.296, 0.036, 0.064, FULL, ROI)
    assert isinstance(v, Violation)
    assert v.class_name == "queue_battle_icon"
    assert "(960,319)" in v.detail          # 中心坐标写进 detail，方便定位
