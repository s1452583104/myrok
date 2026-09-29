"""tools/ingest_raw_imgs.py 的纯逻辑测试。

只测「写错了会静默污染数据集」的部分：路径清单的增量合并、原子写、
以及位置先验的负向门控（放错了等于拿同一片像素教两个类）。
不测 cv2 / OCR / ultralytics 本身。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from rok_assistant.core.template_registry import ROI
from tools.ingest_raw_imgs import (
    MERGE_GAP_MIN,
    NATIVE_H,
    NATIVE_W,
    PRIORS,
    _index_images,
    _load_dataset_yaml,
    _merge_line,
    _merge_split,
    _orphans,
    _prune_split,
    _twin_of,
    _write_list,
    prelabel,
)


# --- 同行合并的间隙上界（zhaizi_level_text 宽框污染的根因）-----------------
#
# 2026-09-24 实测：`zhaizi_level_text` 的 50 条标注里 17 条是 286~802px 的宽框，
# 把「等级：N」和后面那句「您的城市附近暂未找到符合条件的野蛮人城寨。」圈在了
# 一起。同一位置两种差 8 倍的框，YOLO 只能回归到折中 → 实机 1~6 级一个框都不出
# （7~10 级的紧框以约 16:1 压过宽框，才侥幸还能检出）。
# 标注已经改紧，但**工具没修就会在下次入库时重新长出来**——这几条锁的就是工具。

def test_merge_line_joins_the_adjacent_level_digits():
    """「等级：」+ 紧跟的「1」是同一段文字被 DBNet 切成两块 → 合并成一条。"""
    anchor = (157, 523, 246, 548, "等级：", 0.99)
    digit = (250, 523, 268, 548, "1", 0.99)
    assert _merge_line([anchor, digit], anchor) == (157, 523, 268, 548)


def test_merge_line_refuses_the_far_away_hint_block():
    """真实污染：353px 外那句提示语绝不能被并进来（实测锚点右缘 246、块左缘 599）。"""
    anchor = (157, 523, 246, 548, "等级：", 0.99)
    hint = (599, 520, 959, 545, "您的城市附近暂未找到符合条件的野蛮人城寨。", 0.99)
    assert _merge_line([anchor, hint], anchor) == (157, 523, 246, 548)


def test_merge_line_gap_bound_scales_with_the_anchor_height():
    """上界 = max(行高, 16)：行高 60 时上界 60。"""
    tall = (100, 500, 300, 560, "等级：", 0.99)
    assert _merge_line([tall, (350, 500, 380, 560, "7", 0.99)], tall) == (100, 500, 380, 560)
    assert _merge_line([tall, (365, 500, 395, 560, "7", 0.99)], tall) == (100, 500, 300, 560)


def test_merge_line_short_row_falls_back_to_the_pixel_floor():
    """矮行（h=25）按 25 走，不再放宽到 16 以下——16 是兜底不是目标。"""
    anchor = (157, 523, 246, 548, "等级：", 0.99)
    assert MERGE_GAP_MIN == 16
    assert _merge_line([anchor, (266, 523, 280, 548, "1", 0.99)], anchor) == (157, 523, 280, 548)
    assert _merge_line([anchor, (280, 523, 294, 548, "1", 0.99)], anchor) == (157, 523, 246, 548)


def test_merge_line_bounds_the_left_side_too():
    """锚点左边同行的块同样受间隙上界约束（重叠算 0，够近才并）。"""
    anchor = (500, 500, 600, 540, "等级", 0.99)
    assert _merge_line([anchor, (480, 500, 500, 540, "x", 0.99)], anchor) == (480, 500, 600, 540)
    assert _merge_line([anchor, (300, 500, 400, 540, "x", 0.99)], anchor) == (500, 500, 600, 540)


def test_merge_line_ignores_other_rows():
    """纵向超出锚点行高 ±50% 的块不参与合并（那是别的行）。"""
    anchor = (157, 523, 246, 548, "等级：", 0.99)
    below = (250, 600, 268, 625, "1", 0.99)
    assert _merge_line([anchor, below], anchor) == (157, 523, 246, 548)


# --- dataset.yaml（只读类表）---------------------------------------------

def test_load_dataset_yaml_maps_ids_to_names(tmp_path: Path):
    p = tmp_path / "dataset.yaml"
    p.write_text("names:\n  0: alpha\n  1: beta\n", encoding="utf-8")
    names, inv = _load_dataset_yaml(p)
    assert names == {0: "alpha", 1: "beta"}
    assert inv == {"alpha": 0, "beta": 1}


# --- train/val 路径清单的增量合并 -----------------------------------------

def test_merge_split_appends_without_touching_existing(tmp_path: Path):
    p = tmp_path / "train.txt"
    p.write_text("A\nB\n", encoding="utf-8")
    n, lines = _merge_split(p, ["C", "D"])
    assert n == 2
    assert lines == ["A", "B", "C", "D"]


def test_merge_split_is_idempotent(tmp_path: Path):
    """第二次入库同一批图不该把路径重复追加（main 里 merge + write 是两步）。"""
    p = tmp_path / "train.txt"
    p.write_text("A\nB\n", encoding="utf-8")
    _, lines = _merge_split(p, ["C"])
    _write_list(p, lines)
    n, lines = _merge_split(p, ["C"])
    assert n == 0
    assert lines == ["A", "B", "C"]


def test_merge_split_never_moves_a_path_across_splits(tmp_path: Path):
    """`--force` 重跑时 val 抽签流会偏移，同一帧可能这次抽进 val、上次已在 train。

    不拦就是同帧既训练又验证。帧一旦分好就不再搬家。
    """
    p = tmp_path / "val.txt"
    p.write_text("A\n", encoding="utf-8")
    n, lines = _merge_split(p, ["A", "B"], taken=["A"])
    assert n == 1
    assert lines == ["A", "B"]


def test_merge_split_skips_paths_taken_by_the_other_split(tmp_path: Path):
    p = tmp_path / "val.txt"
    p.write_text("A\n", encoding="utf-8")
    n, lines = _merge_split(p, ["B", "C"], taken=["B"])
    assert n == 1
    assert lines == ["A", "C"]


def test_merge_split_dedupes_case_insensitively(tmp_path: Path):
    """Windows 路径大小写不敏感，同一文件不该以不同大小写重复入库。"""
    p = tmp_path / "train.txt"
    p.write_text(r"C:\Data\Img.PNG" + "\n", encoding="utf-8")
    n, lines = _merge_split(p, [r"c:\data\img.png"])
    assert n == 0
    assert lines == [r"C:\Data\Img.PNG"]


def test_merge_split_on_missing_file_starts_empty(tmp_path: Path):
    n, lines = _merge_split(tmp_path / "nope.txt", ["A"])
    assert n == 1
    assert lines == ["A"]


# --- 原子写 ---------------------------------------------------------------

def test_write_list_round_trips_byte_for_byte(tmp_path: Path):
    """既有行必须原样保留：ultralytics 只对 './' 前缀的行按 txt 目录解析，
    任何路径规整都会改变解析结果。"""
    p = tmp_path / "val.txt"
    original = "\n".join(f"line{i}" for i in range(5)) + "\n"
    p.write_text(original, encoding="utf-8")
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln]
    _write_list(p, lines)
    assert p.read_text(encoding="utf-8") == original


def test_write_list_leaves_no_tmp_and_ends_with_newline(tmp_path: Path):
    p = tmp_path / "train.txt"
    _write_list(p, ["A", "B"])
    assert p.read_text(encoding="utf-8") == "A\nB\n"
    assert list(tmp_path.glob("*.tmp")) == []


# --- 失效行摘除 -----------------------------------------------------------

def test_prune_split_drops_lines_whose_image_is_gone(tmp_path: Path):
    """--force 重跑把某帧撤掉后，train/val 里不能留下指向缺失文件的行。"""
    keep = tmp_path / "keep.png"
    keep.write_bytes(b"x")
    lines = [str(keep), str(tmp_path / "gone.png")]
    kept, dropped = _prune_split(lines)
    assert kept == [str(keep)]
    assert dropped == 1


def test_prune_split_leaves_relative_lines_alone(tmp_path: Path):
    """相对路径的解析基准是 CWD 或 txt 所在目录，不能在这儿猜，原样保留。"""
    lines = ["images/a.png", "./images/b.png"]
    kept, dropped = _prune_split(lines)
    assert kept == lines
    assert dropped == 0


# --- 内容级去重（孪生帧）--------------------------------------------------
#
# 2026-09-27 实测：raw_imgs/04_march_preset 有 7 帧与已入库的 manual3_formation_*
# **逐字节相同**（同一个画面被存了两遍、换了个文件名）。文件名不同挡不住这件事，
# 而孪生帧一个落 train 一个落 val 就是 val 指标虚高（dedupe_dataset.py 事后才
# 能发现，且只看 dataset/ 这一侧）。闸开在入库入口。

def _md5_of(p: Path) -> str:
    import hashlib
    return hashlib.md5(p.read_bytes()).hexdigest()


def test_index_images_maps_content_to_the_smallest_name(tmp_path: Path):
    """同内容取名字最小的那份，结果不随目录遍历顺序漂。"""
    (tmp_path / "b.png").write_bytes(b"same")
    (tmp_path / "a.png").write_bytes(b"same")
    (tmp_path / "c.png").write_bytes(b"other")

    idx = _index_images(tmp_path)

    assert len(idx) == 2
    assert idx[_md5_of(tmp_path / "a.png")] == "a"


def test_twin_of_flags_a_renamed_copy(tmp_path: Path):
    """换名的同像素帧要拦下来，并把孪生帧名报出来（方便人工确认）。"""
    (tmp_path / "manual3_formation_222851.png").write_bytes(b"pixels")
    idx = _index_images(tmp_path)

    twin = _twin_of(_md5_of(tmp_path / "manual3_formation_222851.png"), idx,
                    "04_march_preset__MuMu-20260918-222851-190")

    assert twin == "manual3_formation_222851"


def test_twin_of_ignores_the_same_frame_under_its_own_name(tmp_path: Path):
    """同名帧不是孪生：那是「已入库」，报成孪生会让人以为存在两个文件。"""
    (tmp_path / "04_march_preset__x.png").write_bytes(b"pixels")
    idx = _index_images(tmp_path)

    assert _twin_of(_md5_of(tmp_path / "04_march_preset__x.png"), idx,
                    "04_march_preset__x") is None


def test_twin_of_passes_a_genuinely_new_frame(tmp_path: Path):
    (tmp_path / "old.png").write_bytes(b"old")
    idx = _index_images(tmp_path)

    assert _twin_of(_md5_of(tmp_path / "old.png") + "0", idx,
                    "06_home_map__new") is None


def test_index_images_on_empty_dir_is_empty(tmp_path: Path):
    assert _index_images(tmp_path) == {}


# --- 孤儿帧（有图、不在任何 split 里）-------------------------------------
#
# 2026-09-27 实测：入库中途崩在「写完硬链接、还没写 split 行」之间，留下 1 帧
# 有图却不在 train/val 里的孤儿。它不报错、不告警，只是静默地不参与训练——
# 所以入库收尾必须显式对一次账。

def test_orphans_finds_a_frame_missing_from_every_split(tmp_path: Path):
    (tmp_path / "a.png").write_bytes(b"a")
    (tmp_path / "b.png").write_bytes(b"b")

    orph = _orphans(tmp_path, [str(tmp_path / "a.png")])

    assert orph == ["b.png"]


def test_orphans_compares_resolved_paths_not_names(tmp_path: Path):
    """train/val 里两种路径形态并存（老帧指向 recordings/，入库帧指向
    dataset/images/），按文件名比会把两边都判错。"""
    sub = tmp_path / "images"
    sub.mkdir()
    (sub / "x.png").write_bytes(b"x")

    assert _orphans(sub, [str(sub / ".." / "images" / "x.png")]) == []


def test_orphans_is_empty_when_everything_is_referenced(tmp_path: Path):
    (tmp_path / "a.png").write_bytes(b"a")
    assert _orphans(tmp_path, [str(tmp_path / "a.png")]) == []


# --- 位置先验的负向门控 ---------------------------------------------------

class _Spec:
    """够 prelabel 用的最小 TemplateSpec 替身。"""

    def __init__(self, threshold: float = 0.9, roi: ROI | None = None):
        self.threshold = threshold
        self.roi = roi if roi is not None else ROI(0, 0, 0, 0)


class _OcrStub:
    """固定返回一批文本块，不跑真实 OCR。块格式同 _Ocr.text_blocks。"""

    def __init__(self, blocks):
        self._blocks = blocks

    def text_blocks(self, img, roi):
        return self._blocks


NAMES_INV = {"tab_fortress": 6, "barb_search_tab": 51}


def _tab_text_block(y1: int, y2: int):
    # barb_search_tab 先验 cy = 0.3292 → 355.5px，容差 gate_dy 0.05 = 54px
    return [(400, y1, 520, y2, "野蛮人", 0.9)]


def _frame_with_tab_fortress():
    """在野蛮人页签先验的框位附近贴一块噪声模板，让 tab_fortress 匹配到 1.0。"""
    rng = np.random.RandomState(0)
    tmpl = (rng.rand(40, 80, 3) * 255).astype(np.uint8)
    img = np.zeros((NATIVE_H, NATIVE_W, 3), dtype=np.uint8)
    img[330:370, 400:480] = tmpl
    return img, tmpl


def _emitted(prov: list[str]) -> set[str]:
    return {p.rsplit("<-", 1)[0] for p in prov}


def test_prior_suppressed_when_same_rectangle_class_present():
    """tab_fortress 与 barb_search_tab 实测是同一矩形（cx 0.2909/0.2891）且从不共存。

    城寨页帧上若还放出野蛮人页签的框，等于拿同一片像素教两个互斥的类。
    """
    img, tmpl = _frame_with_tab_fortress()
    _boxes, prov, _best = prelabel(
        img, "01_zhaizi_search", NAMES_INV,
        templates={"tab_fortress": tmpl},
        specs={"tab_fortress": _Spec()},
        ocr=_OcrStub(_tab_text_block(340, 370)))

    assert "tab_fortress" in _emitted(prov)        # 模板层照常出框
    assert "barb_search_tab" not in _emitted(prov)  # 先验层被负向门控拦下


def test_prior_emitted_when_blocker_absent():
    """反向：没有城寨页签时，野蛮人页签先验应正常出框。"""
    img = np.zeros((NATIVE_H, NATIVE_W, 3), dtype=np.uint8)
    boxes, prov, _best = prelabel(img, "01_zhaizi_search", NAMES_INV,
                           templates={}, specs={},
                           ocr=_OcrStub(_tab_text_block(340, 370)))

    assert _emitted(prov) == {"barb_search_tab"}
    assert prov == ["barb_search_tab<-prior"]
    cid, cx, cy, _w, _h = boxes[0]
    assert cid == 51
    assert abs(cx - 0.2891) < 1e-3 and abs(cy - 0.3292) < 1e-3


def test_prior_gate_rejects_text_at_wrong_vertical_position():
    """门控还管纵向：同样的文本出现在别处（如收起的排序条）时不该放框。"""
    img = np.zeros((NATIVE_H, NATIVE_W, 3), dtype=np.uint8)
    boxes, prov, _best = prelabel(img, "01_zhaizi_search", NAMES_INV,
                           templates={}, specs={},
                           ocr=_OcrStub(_tab_text_block(900, 930)))  # cy=915，远离 355
    assert boxes == []
    assert prov == []


def test_prior_gate_rejects_when_gate_text_absent():
    """OCR 没找到门控文本 → 该 UI 状态不在这帧上，绝不硬放框。"""
    img = np.zeros((NATIVE_H, NATIVE_W, 3), dtype=np.uint8)
    boxes, prov, _best = prelabel(img, "01_zhaizi_search", NAMES_INV,
                           templates={}, specs={}, ocr=_OcrStub([]))
    assert boxes == []
    assert prov == []


def test_unknown_class_is_skipped_not_remapped():
    """模板比 dataset.yaml 新时跳过，绝不改类表、绝不退化成别的 id。"""
    img, tmpl = _frame_with_tab_fortress()
    boxes, prov, _best = prelabel(img, "01_zhaizi_search", {"something_else": 0},
                           templates={"tab_fortress": tmpl},
                           specs={"tab_fortress": _Spec()},
                           ocr=_OcrStub(_tab_text_block(340, 370)))
    assert boxes == []
    assert prov == []


def test_roi_gate_is_default_and_reports_the_miss():
    """ROI 默认开：模板在 ROI 外命中时**不出框**，但要把全帧分数报出来。

    ROI 是误报闸门（放开全帧后 preset_1..6 会互相串位，实测 958/1918 框越界），
    但它按某一版 UI 硬编码，弹窗一移位就整类静默归零——所以必须留一个可观测信号：
    全帧分数高 = ROI 错位，分数低 = 这帧真没这个元素。
    """
    rng = np.random.RandomState(2)
    tmpl = (rng.rand(47, 200, 3) * 255).astype(np.uint8)
    img = np.zeros((NATIVE_H, NATIVE_W, 3), dtype=np.uint8)
    img[40:87, 100:300] = tmpl  # 落在 spec.roi (800,20,1120,110) 之外

    spec = _Spec(roi=ROI(800, 20, 1120, 110))
    kw = dict(templates={"form_title": tmpl}, specs={"form_title": spec},
              ocr=_OcrStub([]))

    _b, prov_roi, st_roi = prelabel(img, "04_march_preset", {"form_title": 46}, **kw)
    _b, prov_ff, st_ff = prelabel(img, "04_march_preset", {"form_title": 46},
                                  use_roi=False, **kw)

    assert prov_roi == []                            # 默认不出框
    assert st_roi["best"]["form_title"] < 0.6        # ROI 内分数低
    assert st_roi["best_full"]["form_title"] > 0.99  # 但全帧分数高 → 可诊断为 ROI 错位

    assert prov_ff == ["form_title<-tmpl"]           # 显式 --full-frame 才出框


def test_no_full_frame_probe_when_roi_already_hit():
    """ROI 内已命中就不再多跑一遍全帧（那只是诊断信号，白花一次 matchTemplate）。"""
    img, tmpl = _frame_with_tab_fortress()
    _b, prov, st = prelabel(img, "01_zhaizi_search", NAMES_INV,
                            templates={"tab_fortress": tmpl},
                            specs={"tab_fortress": _Spec(roi=ROI(300, 300, 900, 420))},
                            ocr=_OcrStub([]))
    assert prov == ["tab_fortress<-tmpl"]
    assert "tab_fortress" not in st["best_full"]


def test_scene_template_whitelist_filters_out_of_scene_classes():
    """同一帧、同一模板：场景白名单里有它就出框，没有就一个框都不出。"""
    img, tmpl = _frame_with_tab_fortress()
    ocr = _OcrStub([])  # 空 OCR，让先验层不参与，只考察模板层

    _b_in, prov_in, _s_in = prelabel(img, "01_zhaizi_search", NAMES_INV,
                                     templates={"tab_fortress": tmpl},
                                     specs={"tab_fortress": _Spec()}, ocr=ocr)
    _b_out, prov_out, _s_out = prelabel(img, "02_warlist", NAMES_INV,
                                        templates={"tab_fortress": tmpl},
                                        specs={"tab_fortress": _Spec()}, ocr=ocr)

    assert prov_in == ["tab_fortress<-tmpl"]
    assert prov_out == []


def test_same_class_same_box_from_two_layers_is_deduped():
    """同一个类被模板层和先验层各命中一次时只出一个框（去重键含类 id）。"""
    cx_n, cy_n, w_n, h_n = PRIORS[0]["box"]
    # 先验层最终落到的整数框（复刻 prelabel 的截断方式），
    # 再把模板做成同样尺寸贴在同样位置，让模板层的框与它逐像素相等。
    px1, py1 = int((cx_n - w_n / 2) * NATIVE_W), int((cy_n - h_n / 2) * NATIVE_H)
    px2 = int((cx_n - w_n / 2) * NATIVE_W + w_n * NATIVE_W)
    py2 = int((cy_n - h_n / 2) * NATIVE_H + h_n * NATIVE_H)

    rng = np.random.RandomState(1)
    tmpl = (rng.rand(py2 - py1, px2 - px1, 3) * 255).astype(np.uint8)
    img = np.zeros((NATIVE_H, NATIVE_W, 3), dtype=np.uint8)
    img[py1:py2, px1:px2] = tmpl

    # 99_unsorted 的白名单是 None（全跑），PRIORS 与场景无关
    boxes, prov, _best = prelabel(img, "99_unsorted", {"barb_search_tab": 51},
                           templates={"barb_search_tab": tmpl},
                           specs={"barb_search_tab": _Spec(0.8)},
                           ocr=_OcrStub(_tab_text_block(py1, py2)))

    assert prov == ["barb_search_tab<-tmpl"]  # 先到的模板层胜出
    assert len(boxes) == 1
