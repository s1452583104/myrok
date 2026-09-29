"""tools/relabel_extra_classes.py 的补标判据测试。

锁的三件事，各自对应一处**已实测过的漏标根因**：

1. `fit_slots` 必须由**槽位编号**反推列基准。第一版用 `min(cy)` 当首槽，选中槽
   若是 1 号（`preset_*` 里就没有它），整列错一格——10 个已知帧只对 4 个。
2. `preset` pass 的亮度判据必须只在**真有一个白底高亮槽**时才动手。选中的是
   `preset_N` → `selected_preset_N` 的**替换**（互斥，manual2/manual3 逐帧核对过），
   不是两个类都留。
3. `sort` pass 只能整屏帧上按整屏约定重标：`sort_opt_*` 既有 18 条全来自 279x162
   等裁剪帧，坐标是相对裁剪的，两套坐标系就是寨子宽框那种病。
"""
from __future__ import annotations

import numpy as np
import pytest

from rok_assistant.core.template_registry import ROI
from tools.relabel_extra_classes import (
    HOME_BOXES,
    HOME_GATE_MIN,
    NATIVE_H,
    NATIVE_W,
    PRESET_MIN_FRAC,
    SORT_DARK_MAX,
    SORT_OPT_YS,
    SORT_SELECTOR_PX,
    SORT_YELLOW_MIN,
    _yellow_frac,
    plan_home,
    plan_preset,
    plan_sort,
)

FULL = (NATIVE_W, NATIVE_H)
# 实测固定几何（`pixel_stat.PRESET_*`）。**曾经这里是 391.0 —— 那是顶部那个恒定
# 亮菱形的 y**（恰在槽 1 上方一个槽距），合成帧照着菱形画、判据也就跟着错一格。
CX, TOP, STEP = 1655.0, 474.0, 82.0


class _Spec:
    def __init__(self, threshold: float = 0.9, roi: ROI | None = None):
        self.threshold = threshold
        self.roi = roi if roi is not None else ROI(0, 0, 0, 0)


def _mk(dataset, stem: str, img: np.ndarray, rows: list[str]):
    (dataset / "images").mkdir(parents=True, exist_ok=True)
    (dataset / "labels").mkdir(parents=True, exist_ok=True)
    import cv2
    cv2.imwrite(str(dataset / "images" / f"{stem}.png"), img)
    (dataset / "labels" / f"{stem}.txt").write_text("\n".join(rows) + "\n",
                                                    encoding="utf-8")


def _row(cid, cx, cy, w=44, h=44) -> str:
    return (f"{cid} {cx / NATIVE_W:.6f} {cy / NATIVE_H:.6f} "
            f"{w / NATIVE_W:.6f} {h / NATIVE_H:.6f}")


def _preset_frame(selected: int | None) -> np.ndarray:
    """6 个槽，蓝底 (140,140,140)（只判亮度）；`selected` 号槽刷成白底。"""
    img = np.full((NATIVE_H, NATIVE_W, 3), 30, np.uint8)
    for n in range(1, 7):
        cy = TOP + (n - 1) * STEP
        img[int(cy) - 22:int(cy) + 22, int(CX) - 22:int(CX) + 22] = (
            255 if n == selected else 140)
    return img


# --- 列基准反推 -----------------------------------------------------------

def test_fit_slots_uses_slot_numbers_so_a_missing_first_slot_does_not_shift():
    """选中槽是 1 号时 `preset_*` 从 2 号起；首槽要落在 2 号**上一格**。"""
    from tools.relabel_extra_classes import fit_slots
    slots = {n: (CX, TOP + (n - 1) * STEP) for n in (2, 3, 4, 5, 6)}

    cx, top, step = fit_slots(slots)

    assert cx == pytest.approx(CX)
    assert step == pytest.approx(STEP, abs=0.5)
    assert top == pytest.approx(TOP, abs=1.0), "拿 min(cy) 当首槽就会得到 2 号的 y"


def test_fit_slots_absorbs_slot_pitch_drift():
    """实测槽距在帧间有 ±4px 漂移，最小二乘拟合要吸收掉，不能钉死 82。"""
    from tools.relabel_extra_classes import fit_slots
    slots = {n: (CX, TOP + (n - 1) * 84.0) for n in (1, 2, 3, 4, 5, 6)}

    _cx, top, step = fit_slots(slots)

    assert step == pytest.approx(84.0, abs=0.1)
    assert top == pytest.approx(TOP, abs=0.5)


# --- pass preset ----------------------------------------------------------

def test_preset_pass_replaces_the_bright_slot_label(tmp_path):
    """白底槽的 `preset_N` 换成 `selected_preset_N`，两个类不共存。"""
    d = tmp_path / "dataset"
    d.mkdir()
    rows = [_row(n, CX, TOP + (n - 1) * STEP) for n in range(1, 7)]
    _mk(d, "04_march_preset__a", _preset_frame(selected=4), rows)
    names = {n: f"preset_{n}" for n in range(1, 7)}
    names.update({n + 52: f"selected_preset_{n}" for n in range(1, 7)})
    inv = {v: k for k, v in names.items()}

    plan, edits = plan_preset(d / "images", d / "labels", names, inv)

    out = plan["04_march_preset__a"]
    assert len(out) == 6
    cids = [int(ln.split()[0]) for ln in out]
    assert names[55] in [] or True
    assert cids.count(inv["selected_preset_4"]) == 1
    assert cids.count(inv["preset_4"]) == 0, "互斥：选中槽不保留 preset_N"
    assert cids.count(inv["preset_3"]) == 1
    assert edits[0].action == "replace"


def test_preset_pass_adds_when_the_selected_slot_has_no_label(tmp_path):
    """预标注漏掉选中槽时（模板匹配不上白底）要补一条，而不是不动。"""
    d = tmp_path / "dataset"
    d.mkdir()
    rows = [_row(n, CX, TOP + (n - 1) * STEP) for n in (1, 2, 4, 5, 6)]
    _mk(d, "04_march_preset__b", _preset_frame(selected=3), rows)
    names = {n: f"preset_{n}" for n in range(1, 7)}
    names.update({n + 52: f"selected_preset_{n}" for n in range(1, 7)})
    inv = {v: k for k, v in names.items()}

    plan, edits = plan_preset(d / "images", d / "labels", names, inv)

    out = plan["04_march_preset__b"]
    assert len(out) == 6
    assert [int(ln.split()[0]) for ln in out].count(inv["selected_preset_3"]) == 1
    assert edits[0].action == "add"


def test_preset_pass_does_not_duplicate_an_existing_selected_label(tmp_path):
    """**回归测试**：`selected_preset_N` 已在标注里（缺的是它的 `preset_N` 孪生）时，
    必须吸附那一条，**不能**再追加——追加就是同一个槽两条 `selected_preset_N`。

    实测 04_march_preset 的 44 帧全是这个形状（选中槽没有 preset_N 孪生），
    没有这道守卫会把 36 帧全写成重复标注。
    """
    d = tmp_path / "dataset"
    d.mkdir()
    rows = [_row(n, CX, TOP + (n - 1) * STEP) for n in range(1, 6)]        # preset_1..5
    rows.append(_row(58, CX, TOP + 5 * STEP))                              # selected_preset_6
    _mk(d, "04_march_preset__e", _preset_frame(selected=6), rows)
    names = {n: f"preset_{n}" for n in range(1, 7)}
    names.update({n + 52: f"selected_preset_{n}" for n in range(1, 7)})
    inv = {v: k for k, v in names.items()}

    plan, edits = plan_preset(d / "images", d / "labels", names, inv)

    out = plan["04_march_preset__e"]
    cids = [int(ln.split()[0]) for ln in out]
    assert len(out) == 6, "同一个槽被写了两次"
    assert cids.count(inv["selected_preset_6"]) == 1
    assert cids.count(inv["preset_6"]) == 0
    assert edits[0].action == "replace"


def test_preset_pass_leaves_a_frame_with_no_highlight_alone(tmp_path):
    """没有白底槽的帧（模板把 6 个槽全标成 preset_N）不能瞎猜一个选中态。"""
    d = tmp_path / "dataset"
    d.mkdir()
    rows = [_row(n, CX, TOP + (n - 1) * STEP) for n in range(1, 7)]
    _mk(d, "04_march_preset__c", _preset_frame(selected=None), rows)
    names = {n: f"preset_{n}" for n in range(1, 7)}
    names.update({n + 52: f"selected_preset_{n}" for n in range(1, 7)})
    inv = {v: k for k, v in names.items()}

    plan, edits = plan_preset(d / "images", d / "labels", names, inv)

    assert plan == {}
    assert edits[0].action == "skip"
    assert PRESET_MIN_FRAC == 0.4


def test_preset_pass_skips_frames_with_too_few_known_slots(tmp_path):
    """已知槽 <3 就没法交叉校验列基准，宁可不动。"""
    d = tmp_path / "dataset"
    d.mkdir()
    _mk(d, "04_march_preset__d", _preset_frame(selected=1),
        [_row(1, CX, TOP), _row(2, CX, TOP + STEP)])
    names = {n: f"preset_{n}" for n in range(1, 7)}
    names.update({n + 52: f"selected_preset_{n}" for n in range(1, 7)})
    inv = {v: k for k, v in names.items()}

    plan, edits = plan_preset(d / "images", d / "labels", names, inv)

    assert plan == {}
    assert "无法交叉校验" in edits[0].detail


# --- 交叉校验：列基准不是当前布局的帧，一个框都不动 -------------------------

@pytest.mark.parametrize("offset,why", [
    (-82.0, "整一个槽距：标注落在顶部菱形那一格"),
    (-26.0, "实测 failure_*/smoke__* 的列就在 448"),
])
def test_preset_pass_skips_frames_whose_column_is_not_at_the_measured_geometry(
        tmp_path, offset, why):
    """**回归测试**：标注拟合出的列基准偏离实测几何 >15px → 整帧跳过。

    旧版从标注反推基准，于是「标注错一格 → 基准错一格 → 采样错一格 → 自洽地
    判出错的选中槽」，谁都不报错。现在拟合值只用来否决，不用来采样。
    """
    d = tmp_path / "dataset"
    d.mkdir()
    shifted = TOP + offset
    rows = [_row(n, CX, shifted + (n - 1) * STEP) for n in range(1, 7)]
    _mk(d, "04_march_preset__shifted", _preset_frame(selected=4), rows)
    names = {n: f"preset_{n}" for n in range(1, 7)}
    names.update({n + 52: f"selected_preset_{n}" for n in range(1, 7)})
    inv = {v: k for k, v in names.items()}

    plan, edits = plan_preset(d / "images", d / "labels", names, inv)

    assert plan == {}, f"该帧不该被动（{why}）"
    assert edits[0].action == "skip"
    assert "偏离实测固定几何" in edits[0].detail


def test_preset_pass_still_fires_when_the_column_matches(tmp_path):
    """偏差在容差内（实测 04_march_preset 的标注偏 2~8px）照常判。"""
    d = tmp_path / "dataset"
    d.mkdir()
    # 标注用 84 的槽距（实测标注就是这个毛病：槽距 83.8 而真值 82，累积偏到 8px）
    rows = [_row(n, CX, TOP + (n - 1) * 83.8) for n in range(1, 7)]
    _mk(d, "04_march_preset__drift", _preset_frame(selected=5), rows)
    names = {n: f"preset_{n}" for n in range(1, 7)}
    names.update({n + 52: f"selected_preset_{n}" for n in range(1, 7)})
    inv = {v: k for k, v in names.items()}

    plan, edits = plan_preset(d / "images", d / "labels", names, inv)

    assert edits[0].action == "replace"
    assert edits[0].class_name == "selected_preset_5"


def test_selected_box_is_snapped_to_the_measured_geometry(tmp_path):
    """选中槽的框吸附到实测几何——这个类实例最少，每条位置精度都值钱。"""
    d = tmp_path / "dataset"
    d.mkdir()
    rows = [_row(n, CX, TOP + (n - 1) * 83.8) for n in range(1, 7)]
    _mk(d, "04_march_preset__drift", _preset_frame(selected=6), rows)
    names = {n: f"preset_{n}" for n in range(1, 7)}
    names.update({n + 52: f"selected_preset_{n}" for n in range(1, 7)})
    inv = {v: k for k, v in names.items()}

    plan, _e = plan_preset(d / "images", d / "labels", names, inv)

    sel = [ln for ln in plan["04_march_preset__drift"]
           if int(ln.split()[0]) == inv["selected_preset_6"]]
    assert len(sel) == 1
    cx, cy, w, h = (float(v) for v in sel[0].split()[1:])
    assert cx * NATIVE_W == pytest.approx(CX, abs=0.5)
    assert cy * NATIVE_H == pytest.approx(TOP + 5 * STEP, abs=0.5), \
        "吸附到槽 6 的实测中心，不是标注里那个偏 8px 的位置"
    assert w * NATIVE_W == pytest.approx(44.0, abs=0.5)


def test_preset_pass_never_samples_the_top_diamond(tmp_path):
    """**回归测试**：真值几何从 474 起，采不到 389 的菱形。

    合成帧只在菱形那一格（TOP-82）刷白，6 个真槽全暗——判据必须判「无选中态」。
    """
    d = tmp_path / "dataset"
    d.mkdir()
    img = np.full((NATIVE_H, NATIVE_W, 3), 30, np.uint8)
    cy = TOP - STEP                      # 菱形那一格
    img[int(cy) - 22:int(cy) + 22, int(CX) - 22:int(CX) + 22] = 255
    rows = [_row(n, CX, TOP + (n - 1) * STEP) for n in range(1, 7)]
    _mk(d, "04_march_preset__diamond", img, rows)
    names = {n: f"preset_{n}" for n in range(1, 7)}
    names.update({n + 52: f"selected_preset_{n}" for n in range(1, 7)})
    inv = {v: k for k, v in names.items()}

    plan, edits = plan_preset(d / "images", d / "labels", names, inv)

    assert plan == {}, "只有菱形亮时不许判出任何选中槽"
    assert "无选中态" in edits[0].detail


# --- pass sort ------------------------------------------------------------

def _sort_names():
    names = {59: "sort_selector", 60: "sort_opt_latest",
             61: "sort_opt_nearest", 62: "sort_opt_shortest", 14: "war_title"}
    return names, {v: k for k, v in names.items()}


def _with_selector(img: np.ndarray) -> np.ndarray:
    """在排序条的位置刷一道黄字——有条的帧实测黄字占比 0.038~0.062。"""
    x1, y1, x2, y2 = SORT_SELECTOR_PX
    img[y1 + 10:y2 - 10, x1 + 150:x2 - 150] = (60, 200, 230)   # BGR 黄
    return img


def test_yellow_frac_reads_the_selector_text_not_just_any_bright_patch():
    """判据是「黄」而不是「亮」：白/蓝的亮块不能算，黄字才算。"""
    x1, y1, x2, y2 = SORT_SELECTOR_PX
    white = np.full((NATIVE_H, NATIVE_W, 3), 255, np.uint8)
    blue = np.full((NATIVE_H, NATIVE_W, 3), (200, 120, 30), np.uint8)
    assert _yellow_frac(white, x1, y1, x2, y2) == 0.0
    assert _yellow_frac(blue, x1, y1, x2, y2) == 0.0
    assert _yellow_frac(_with_selector(white.copy()), x1, y1, x2, y2) > SORT_YELLOW_MIN


def test_sort_pass_rewrites_to_the_full_frame_convention(tmp_path):
    """收起帧：只标 sort_selector；旧约定残留（含裁剪帧那种整幅框）一律先清掉。"""
    d = tmp_path / "dataset"
    d.mkdir()
    img = _with_selector(np.full((NATIVE_H, NATIVE_W, 3), 200, np.uint8))
    # 旧的退化框：占整幅 99%x91%（裁剪帧上的那种）
    stale = "59 0.500000 0.500000 0.990000 0.910000"
    _mk(d, "02_warlist__a", img, [stale, _row(14, 900, 120)])
    names, inv = _sort_names()

    plan, _edits = plan_sort(d / "images", d / "labels", names, inv)

    out = plan["02_warlist__a"]
    cids = [int(ln.split()[0]) for ln in out]
    assert cids == [14, 59], "旧 sort_* 行要清掉，再按整屏约定补一条"
    cx, cy, w, h = (float(v) for v in out[1].split()[1:])
    assert w * NATIVE_W == pytest.approx(396.6, abs=1.0)
    assert cy * NATIVE_H == pytest.approx(160.7, abs=1.0)


def test_sort_pass_adds_the_three_rows_only_when_the_dropdown_is_open(tmp_path):
    """展开判据是「这块是近黑面板」：收起帧 meanV≈120，展开帧≈30~90。"""
    d = tmp_path / "dataset"
    d.mkdir()
    names, inv = _sort_names()

    collapsed = _with_selector(np.full((NATIVE_H, NATIVE_W, 3), 200, np.uint8))
    _mk(d, "02_warlist__collapsed", collapsed, [])
    open_ = collapsed.copy()
    x1, y1, x2, y2 = (300, 210, 640, 350)
    open_[y1:y2, x1:x2] = 25
    _mk(d, "02_warlist__open", open_, [])

    plan, _e = plan_sort(d / "images", d / "labels", names, inv)

    assert len(plan["02_warlist__collapsed"]) == 1
    assert [int(ln.split()[0]) for ln in plan["02_warlist__open"]] == [59, 60, 61, 62]
    assert SORT_DARK_MAX == 90.0
    # 三行按 ~54px 行距等间隔排开，不能叠在一起
    ys = [float(ln.split()[2]) * NATIVE_H for ln in plan["02_warlist__open"][1:]]
    assert ys == pytest.approx([223.5, 277.0, 331.5], abs=0.5)
    assert all(45 <= b - a <= 60 for a, b in zip(ys, ys[1:]))


def test_sort_pass_writes_nothing_when_there_is_no_selector_bar(tmp_path):
    """战争详情页：那个位置是列表行，没有条——补框就是拿列表像素教「排序条」。"""
    d = tmp_path / "dataset"
    d.mkdir()
    names, inv = _sort_names()
    plain = np.full((NATIVE_H, NATIVE_W, 3), 200, np.uint8)   # 没有黄字
    _mk(d, "02_warlist__detail", plain, [_row(14, 900, 120)])

    plan, edits = plan_sort(d / "images", d / "labels", names, inv)

    assert plan == {}
    assert edits[0].action == "skip"
    assert "没有排序条" in edits[0].detail


def test_sort_pass_strips_a_stale_label_from_a_detail_page(tmp_path):
    """详情页上先前留下的错标注要清掉——这才是这道闸顺手修回来的东西。"""
    d = tmp_path / "dataset"
    d.mkdir()
    names, inv = _sort_names()
    plain = np.full((NATIVE_H, NATIVE_W, 3), 200, np.uint8)
    _mk(d, "02_warlist__detail", plain,
        [_row(59, 466.5, 160.7, 396.6, 45.1), _row(14, 900, 120)])

    plan, _e = plan_sort(d / "images", d / "labels", names, inv)

    assert [int(ln.split()[0]) for ln in plan["02_warlist__detail"]] == [14]


def test_sort_pass_leaves_a_clean_detail_page_out_of_the_plan(tmp_path):
    """本来就没错标注的详情页，不该出现在待写清单里（无谓重写 = 无谓风险）。"""
    d = tmp_path / "dataset"
    d.mkdir()
    names, inv = _sort_names()
    _mk(d, "02_warlist__detail", np.full((NATIVE_H, NATIVE_W, 3), 200, np.uint8),
        [_row(14, 900, 120)])

    plan, _e = plan_sort(d / "images", d / "labels", names, inv)

    assert plan == {}


def test_sort_pass_skips_non_full_frames(tmp_path):
    """裁剪帧按整屏约定重标是错的——留给 prune_labels 撤帧。"""
    d = tmp_path / "dataset"
    d.mkdir()
    small = np.full((162, 279, 3), 200, np.uint8)
    import cv2
    (d / "images").mkdir(parents=True, exist_ok=True)
    (d / "labels").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(d / "images" / "02_warlist__crop.png"), small)
    (d / "labels" / "02_warlist__crop.txt").write_text("59 0.5 0.5 1.0 1.0\n",
                                                       encoding="utf-8")
    names, inv = _sort_names()

    plan, edits = plan_sort(d / "images", d / "labels", names, inv)

    assert plan == {}
    assert edits[0].action == "skip"
    assert "非 1920x1080" in edits[0].detail


# --- pass home ------------------------------------------------------------

def _noise(shape) -> np.ndarray:
    """有纹理的补丁——纯色补丁会让 TM_CCOEFF_NORMED 退化（方差为 0）。"""
    return (np.random.RandomState(7).rand(*shape) * 255).astype(np.uint8)


def test_home_pass_adds_both_buttons_when_the_gate_passes(tmp_path):
    """门控过 → 补 search_icon + city_btn；已标过的类不重复补。"""
    d = tmp_path / "dataset"
    d.mkdir()
    img = np.full((NATIVE_H, NATIVE_W, 3), 60, np.uint8)
    tmpl = _noise((100, 100, 3))
    img[800:900, 100:200] = tmpl                     # 门控模板就取这块
    _mk(d, "06_home_map__a", img, [_row(1, 1700, 860, 200, 120)])  # alliance_btn 已标
    names = {0: "search_icon", 1: "alliance_btn", 63: "city_btn"}
    inv = {v: k for k, v in names.items()}

    plan, edits = plan_home(d / "images", d / "labels", names, inv,
                            {"search_icon": tmpl}, {"search_icon": _Spec(roi=ROI(0, 700, 240, 940))})

    cids = [int(ln.split()[0]) for ln in plan["06_home_map__a"]]
    assert cids == [1, 0, 63]
    assert [e.class_name for e in edits] == ["search_icon", "city_btn"]


def test_home_pass_skips_when_a_panel_covers_the_corner(tmp_path):
    """左下角被面板盖住时（实测模板分 0.21~0.39）一个框都不补。"""
    d = tmp_path / "dataset"
    d.mkdir()
    img = np.full((NATIVE_H, NATIVE_W, 3), 60, np.uint8)
    tmpl = _noise((100, 100, 3))
    img[800:900, 100:200] = tmpl
    img[800:900, 100:200] = 60                       # 盖住
    _mk(d, "06_home_map__b", img, [])
    names = {0: "search_icon", 63: "city_btn"}
    inv = {v: k for k, v in names.items()}

    plan, edits = plan_home(d / "images", d / "labels", names, inv,
                            {"search_icon": tmpl}, {"search_icon": _Spec(roi=ROI(0, 700, 240, 940))})

    assert plan == {}
    assert edits[0].action == "skip"
    assert HOME_GATE_MIN == 0.85
    assert set(HOME_BOXES) == {"search_icon", "city_btn"}
    assert SORT_OPT_YS["sort_opt_nearest"] > SORT_OPT_YS["sort_opt_latest"]
