# -*- coding: utf-8 -*-
"""补标：给已入库的帧补上「标注侧从来没有过一致约定」的三类漏标。

这三处漏标都不是模型弱，而是**标注侧就没有可学的东西**：

1. `home` — `06_home_map`（地图视图）从没标过左下角的两个按钮。
   `search_icon`（放大镜，上槽）的 81 条实例全来自别的场景/状态；
   `city_btn`（城堡，下槽）是 2026-09-27 新增的类，零实例。
   两个按钮在整屏上位置零方差（`search_icon` n=81 的 y1 标准差 0.9px），
   所以用**固定框 + 门控**，不用模板匹配。

2. `preset` — `raw_imgs/04_march_preset` 的帧只有 `preset_N`（蓝底未选中），
   一条 `selected_preset_N`（白底高亮）都没有：预标注用的模板是蓝底抠的，
   选中态匹配不上。判据用亮度——选中槽近白像素占比 0.72~0.75，未选中 0.07~0.09。
   采样位置走**实测固定几何**（`pixel_stat.PRESET_*`，槽 N 中心 474+82*(N-1)），
   不再用 `fit_slots` 从被校验的标注反推——那个闭环会把顶部菱形（在槽 1 上方整
   一个槽距、且比任何选中槽都亮）当成槽 1，整列错一格。`fit_slots` 保留作**交叉
   校验**：偏离固定几何 >15px 的帧一个框都不动（实测 `failure_*`/`smoke__*` 的列
   在 448、`manual3_*` 的一批在 390，确实不是当前布局）。

3. `sort` — `sort_selector` / `sort_opt_*` 的既有标注里，`sort_opt_*` 的 18 条
   **全部**来自 279x162 等**裁剪帧**，normalized 坐标是相对裁剪的；整屏帧上同一个
   下拉在 cx 0.19、宽 0.10。两套坐标系 → 与寨子宽框同病。这里按整屏约定重标，
   那 6 张裁剪帧随后由 `prune_labels.py` 撤掉（撤完 `sort_opt_*` 才不会归零）。

三个 pass 都只碰自己那几帧，互不干扰。默认 dry-run，`--apply` 前把 `labels/`
整份备份到 `dataset/_relabel_backup_<时间戳>/`。

用法（仓库根目录）：
    .venv/Scripts/python.exe tools/relabel_extra_classes.py              # 只看报告
    .venv/Scripts/python.exe tools/relabel_extra_classes.py --render     # 报告 + 叠框图
    .venv/Scripts/python.exe tools/relabel_extra_classes.py --apply      # 真写
    .venv/Scripts/python.exe tools/relabel_extra_classes.py --only preset
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

from auto_label_yolo import multi_match  # noqa: E402
from class_names_zh import zh  # noqa: E402
from rok_assistant.core.recognizers.pixel_stat import (  # noqa: E402
    PRESET_CLICKABLE_N,
    PRESET_CX,
    PRESET_HALF,
    PRESET_MIN_FRAC,
    PRESET_MIN_RATIO,
    PRESET_PITCH,
    PRESET_TOP,
    SORT_DARK_MAX,
    SORT_DARK_ROI,
    SORT_OPT_H,
    SORT_OPT_X,
    SORT_OPT_YS,
    SORT_SELECTOR,
    SORT_SELECTOR_PX,
    SORT_YELLOW_MIN,
    bright_frac,
    mean_v,
    slot_center,
    yellow_frac,
)
from rok_assistant.core.template_registry import TemplateRegistry  # noqa: E402

# 判据与几何常量的**真相在 `recognizers/pixel_stat.py`**（运行时识别器与预览共用
# 同一份）。这里只做私有别名，让本工具与单测继续按原名引用——绝不反向 import。
_bright_frac = bright_frac
_mean_v = mean_v
_yellow_frac = yellow_frac

NATIVE_W, NATIVE_H = 1920, 1080
FULL = (NATIVE_W, NATIVE_H)

# --- pass home ------------------------------------------------------------
HOME_SCENE = "06_home_map"
# 两个按钮的固定框 (x1, y1, w, h) 绝对像素。取自现有标注实测，不是目测：
#   search_icon n=81  x1 38.3±2.3  y1 762.9±0.9  w 96.1±0.9  h 96.1±1.2
#   city_btn    与 map_btn 同槽：城市视图那格是 map_btn (45,950,95,90)（19 条
#               标注零方差），地图视图那格是城堡，实测城堡补丁在该框上
#               0.986~1.000 命中、城市视图帧上 0.31~0.48 不命中。
HOME_BOXES: dict[str, tuple[int, int, int, int]] = {
    "search_icon": (38, 763, 96, 96),
    "city_btn": (45, 950, 95, 90),
}
# 门控：放大镜模板在它自己的 ROI 里 ≥0.85 ⟺ 在地图视图 ⟺ 这两个按钮都露着。
# 实测 45 张 06_home_map 帧是干净双峰：露着 0.88~1.00（27 张），
# 被面板盖住 0.21~0.39（18 张）。0.85 落在峰谷中间。
HOME_GATE_TMPL = "search_icon"
HOME_GATE_MIN = 0.85

# --- pass preset ----------------------------------------------------------
PRESET_SCENE = "04_march_preset"
# 几何/阈值全部来自 `pixel_stat`（见顶部 import）。这里只留本工具特有的东西。
#
# **列基准是实测钉死的，不再从标注反推。** 旧版 `fit_slots` 拿「被校验的标注
# 本身」反推列基准，标注错→几何错→自洽地错，是个闭环；实测 `top` 在 391~475
# 间漂移，而 391 恰好是**顶部那个恒定亮菱形**（在槽 1 上方整一个槽距）——它
# 一旦被当成槽 1，整列错一格。
#
# 保留 `fit_slots`，但改作**交叉校验**：拟合值与固定几何偏差超过 `PRESET_FIT_TOL`
# 就说明这帧的界面/标注不是当前布局（实测确实存在：`failure_*`/`smoke__*` 的列在
# 448、`manual3_*` 的有一批在 390），此时**一个框都不动**并报告出来。
PRESET_FIT_TOL = 15.0     # 拟合基准与固定几何的最大容许偏差（px）

# --- pass sort ------------------------------------------------------------
SORT_SCENE = "02_warlist"
SORT_CLASSES = ("sort_selector", "sort_opt_latest", "sort_opt_nearest",
                "sort_opt_shortest")


@dataclass(frozen=True)
class Edit:
    frame: str
    action: str        # add / replace / skip
    class_name: str
    detail: str


# --- 公共 -----------------------------------------------------------------

def _row(cid: int, cx: float, cy: float, w: float, h: float) -> str:
    return f"{cid} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def _box_row(cid: int, x1: float, y1: float, x2: float, y2: float) -> str:
    return _row(cid, (x1 + x2) / 2 / NATIVE_W, (y1 + y2) / 2 / NATIVE_H,
                (x2 - x1) / NATIVE_W, (y2 - y1) / NATIVE_H)


def _read_rows(labels_dir: Path, stem: str) -> list[str]:
    p = labels_dir / f"{stem}.txt"
    if not p.exists():
        return []
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _class_ids(rows: list[str]) -> list[int]:
    return [int(ln.split()[0]) for ln in rows if len(ln.split()) == 5]


# --- pass home ------------------------------------------------------------

def plan_home(images_dir: Path, labels_dir: Path, names: dict[int, str],
              names_inv: dict[str, int], templates: dict[str, np.ndarray],
              specs: dict) -> tuple[dict[str, list[str]], list[Edit]]:
    plan: dict[str, list[str]] = {}
    edits: list[Edit] = []
    gate = templates.get(HOME_GATE_TMPL)
    if gate is None:
        raise RuntimeError(f"manifest 里没有 {HOME_GATE_TMPL}，门控无法成立")
    spec = specs[HOME_GATE_TMPL]
    roi = (spec.roi.x1, spec.roi.y1, spec.roi.x2, spec.roi.y2)

    for img_path in sorted(images_dir.glob(f"{HOME_SCENE}__*.png")):
        img = cv2.imread(str(img_path))
        if img is None or img.shape[:2] != (NATIVE_H, NATIVE_W):
            continue
        _, score = multi_match(img, gate, 1.0, roi)
        if score < HOME_GATE_MIN:
            edits.append(Edit(img_path.stem, "skip", "-",
                              f"门控未过：放大镜模板 {score:.3f} < {HOME_GATE_MIN}"
                              f"（左下角被面板盖住）"))
            continue
        rows = _read_rows(labels_dir, img_path.stem)
        have = {names[c] for c in _class_ids(rows)}
        new = list(rows)
        for cls, (x1, y1, w, h) in HOME_BOXES.items():
            if cls in have:
                continue
            cid = names_inv.get(cls)
            if cid is None:
                continue
            new.append(_box_row(cid, x1, y1, x1 + w, y1 + h))
            edits.append(Edit(img_path.stem, "add", cls,
                              f"({x1},{y1})-({x1 + w},{y1 + h})"))
        if new != rows:
            plan[img_path.stem] = new
    return plan, edits


# --- pass preset ----------------------------------------------------------

def fit_slots(slots: dict[int, tuple[float, float]]) -> tuple[float, float, float]:
    """由**已知编号**的槽反推列基准，返回 (cx, 首槽 cy, 槽距)。

    不能拿 `min(cy)` 当首槽：选中槽若是 1 号，`preset_*` 里就没有它，min 会落到
    2 号上、整列错一格（第一版就是这么错的，10 个已知帧只对 4 个）。用最小二乘
    拟合 `cy = top + step*(n-1)` 还能顺带吸收槽距在各帧间的漂移（实测 ±4px）。
    """
    ns = np.array(sorted(slots), dtype=float)
    cys = np.array([slots[int(n)][1] for n in ns], dtype=float)
    if len(ns) >= 2:
        step, top = np.polyfit(ns - 1, cys, 1)
    else:
        top, step = cys[0], PRESET_SLOT
    cx = float(np.median([slots[int(n)][0] for n in ns]))
    return cx, float(top), float(step)


def plan_preset(images_dir: Path, labels_dir: Path, names: dict[int, str],
                names_inv: dict[str, int]) -> tuple[dict[str, list[str]], list[Edit]]:
    plan: dict[str, list[str]] = {}
    edits: list[Edit] = []
    for img_path in sorted(images_dir.glob(f"{PRESET_SCENE}__*.png")):
        img = cv2.imread(str(img_path))
        if img is None or img.shape[:2] != (NATIVE_H, NATIVE_W):
            continue
        rows = _read_rows(labels_dir, img_path.stem)
        slots: dict[int, tuple[float, float]] = {}
        for ln in rows:
            t = ln.split()
            if len(t) != 5:
                continue
            cname = names.get(int(t[0]), "")
            if not cname.startswith("preset_"):
                continue
            cx, cy = float(t[1]) * NATIVE_W, float(t[2]) * NATIVE_H
            slots[int(cname.rsplit("_", 1)[1])] = (cx, cy)

        # 交叉校验（不参与判据）：标注拟合出的列基准若偏离实测固定几何，说明这帧
        # 的界面/标注不是当前布局——此时**一个框都不动**。实测确有这样的帧：
        # `failure_*`/`smoke__*` 的列在 448、`manual3_*` 的一批在 390。
        if len(slots) < 3:
            edits.append(Edit(img_path.stem, "skip", "-",
                              f"只有 {len(slots)} 个已知槽，无法交叉校验列基准"))
            continue
        _cx_f, top_f, _step_f = fit_slots(slots)
        dev = top_f - PRESET_TOP
        if abs(dev) > PRESET_FIT_TOL:
            edits.append(Edit(img_path.stem, "skip", "-",
                              f"拟合列基准 {top_f:.0f} 偏离实测固定几何 "
                              f"{PRESET_TOP:.0f} 达 {dev:+.0f}px "
                              f"(> {PRESET_FIT_TOL:.0f})，这帧不是当前布局"))
            continue

        # 判据采样一律走**实测固定几何**，绝不走拟合值（旧版就是从标注反推的闭环）
        fracs = [_bright_frac(img, *slot_center(n))
                 for n in range(1, PRESET_CLICKABLE_N + 1)]
        order = sorted(range(PRESET_CLICKABLE_N), key=lambda i: -fracs[i])
        best, second = order[0], fracs[order[1]]
        n_sel = best + 1
        if fracs[best] < PRESET_MIN_FRAC or fracs[best] < PRESET_MIN_RATIO * second:
            edits.append(Edit(img_path.stem, "skip", "-",
                              f"无选中态（最高槽 {n_sel} 占比 {fracs[best]:.2f}，"
                              f"次高 {second:.2f}）"))
            continue

        cid_sel = names_inv.get(f"selected_preset_{n_sel}")
        cid_pre = names_inv.get(f"preset_{n_sel}")
        if cid_sel is None:
            continue
        # 选中槽的框**吸附到实测几何**：这个类实例最少（3~17 条），每一条的位置
        # 精度都值钱；其余 preset_N 框不动（它们的偏差 ≤8px，且不该为此重写全场景）。
        scx, scy = slot_center(n_sel)
        sel_row = _box_row(cid_sel, scx - PRESET_HALF, scy - PRESET_HALF,
                           scx + PRESET_HALF, scy + PRESET_HALF)
        new: list[str] = []
        hit_pre = hit_sel = False
        for ln in rows:
            t = ln.split()
            cid = int(t[0]) if len(t) == 5 else None
            if cid == cid_pre:
                # 互斥：选中槽**不保留** preset_N（manual2/manual3 的 10 帧逐帧核对过）
                new.append(sel_row)
                hit_pre = True
            elif cid == cid_sel:
                # 已经有 selected_preset_N 了（预标注漏掉的是**别的**槽）：
                # 吸附位置，**不能**再追加一条——追加就成了同一个槽两条标注。
                new.append(sel_row)
                hit_sel = True
            else:
                new.append(ln)
        if not (hit_pre or hit_sel):
            new.append(sel_row)
        edits.append(Edit(img_path.stem,
                          "replace" if (hit_pre or hit_sel) else "add",
                          f"selected_preset_{n_sel}",
                          f"槽位 {n_sel}，占比 {fracs[best]:.2f} "
                          f"（次高 {second:.2f}）"))
        plan[img_path.stem] = new
    return plan, edits


# --- pass sort ------------------------------------------------------------

def plan_sort(images_dir: Path, labels_dir: Path, names: dict[int, str],
              names_inv: dict[str, int]) -> tuple[dict[str, list[str]], list[Edit]]:
    plan: dict[str, list[str]] = {}
    edits: list[Edit] = []
    sort_cids = {names_inv[c] for c in SORT_CLASSES if c in names_inv}
    for img_path in sorted(images_dir.glob(f"{SORT_SCENE}__*.png")):
        img = cv2.imread(str(img_path))
        if img is None or img.shape[:2] != (NATIVE_H, NATIVE_W):
            edits.append(Edit(img_path.stem, "skip", "-",
                              f"非 {NATIVE_W}x{NATIVE_H}，整屏约定不适用"))
            continue
        rows = _read_rows(labels_dir, img_path.stem)
        new = [ln for ln in rows
               if not (len(ln.split()) == 5 and int(ln.split()[0]) in sort_cids)]

        # 先问「这条上有没有排序条」，再谈展开没展开。没有条时**一条都不补**，
        # 但仍要把旧的 sort_* 行清掉——先前那版没有这道闸，已经在 2 帧战争详情页
        # 上留了错标注，清掉就是顺手修回来。
        yf = _yellow_frac(img, *SORT_SELECTOR_PX)
        if yf < SORT_YELLOW_MIN:
            edits.append(Edit(img_path.stem, "skip", "-",
                              f"这条上没有排序条（黄字占比 {yf:.3f}）"
                              f"——战争详情页，不是战争列表"))
            if new != rows:
                plan[img_path.stem] = new
            continue

        new.append(_row(names_inv["sort_selector"], *SORT_SELECTOR))
        dark = _mean_v(img, *SORT_DARK_ROI)
        if dark < SORT_DARK_MAX:
            x1, x2 = SORT_OPT_X
            for cls, cy in SORT_OPT_YS.items():
                new.append(_box_row(names_inv[cls], x1, cy - SORT_OPT_H / 2,
                                    x2, cy + SORT_OPT_H / 2))
        edits.append(Edit(img_path.stem, "replace", "sort_selector"
                          + ("+下拉三行" if dark < SORT_DARK_MAX else "（收起）"),
                          f"面板暗度 {dark:.0f}"))
        plan[img_path.stem] = new
    return plan, edits


# --- 渲染复核 -------------------------------------------------------------

def render(images_dir: Path, plan: dict[str, list[str]], names: dict[int, str],
           out_path: Path, scene: str) -> None:
    tiles = []
    for stem, rows in sorted(plan.items()):
        img = cv2.imread(str(images_dir / f"{stem}.png"))
        if img is None:
            continue
        for ln in rows:
            t = ln.split()
            if len(t) != 5:
                continue
            cid, cx, cy, w, h = int(t[0]), *(float(v) for v in t[1:])
            x1, y1 = int((cx - w / 2) * NATIVE_W), int((cy - h / 2) * NATIVE_H)
            x2, y2 = int((cx + w / 2) * NATIVE_W), int((cy + h / 2) * NATIVE_H)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 3)
            cv2.putText(img, names[cid], (x1, max(22, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
        img = cv2.resize(img, None, fx=0.42, fy=0.42, interpolation=cv2.INTER_AREA)
        h_, w_ = img.shape[:2]
        t_ = np.full((h_ + 30, w_, 3), 255, np.uint8)
        t_[30:] = img
        cv2.putText(t_, stem[-24:], (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 0), 2, cv2.LINE_AA)
        tiles.append(t_)
    if not tiles:
        return
    width = max(t.shape[1] for t in tiles)
    out = np.vstack([np.hstack([t, np.full((t.shape[0], width - t.shape[1], 3),
                                           255, np.uint8)]) for t in tiles])
    cv2.imencode(".png", out)[1].tofile(str(out_path))
    print(f"   -> 叠框图 {out_path}（{len(tiles)} 帧）")


# --- main -----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    ap.add_argument("--manifest", type=Path,
                    default=ROOT / "templates" / "manifest.yaml")
    ap.add_argument("--only", default="home,preset,sort",
                    help="只跑其中几个 pass（逗号分隔）")
    ap.add_argument("--render", action="store_true",
                    help="把每帧的最终标注渲成叠框图到 logs/review/")
    ap.add_argument("--apply", action="store_true", help="真写（默认只报告）")
    args = ap.parse_args()

    images_dir, labels_dir = args.dataset / "images", args.dataset / "labels"
    names = {int(k): str(v) for k, v in yaml.safe_load(
        (args.dataset / "dataset.yaml").read_text(encoding="utf-8"))["names"].items()}
    names_inv = {v: k for k, v in names.items()}
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    registry = TemplateRegistry.load(args.manifest)
    specs = registry._t
    templates = {tid: cv2.imread(str(s.file)) for tid, s in specs.items()}
    templates = {k: v for k, v in templates.items() if v is not None}

    passes = []
    if "home" in only:
        passes.append(("home", HOME_SCENE, plan_home(images_dir, labels_dir, names,
                                                     names_inv, templates, specs)))
    if "preset" in only:
        passes.append(("preset", PRESET_SCENE,
                       plan_preset(images_dir, labels_dir, names, names_inv)))
    if "sort" in only:
        passes.append(("sort", SORT_SCENE,
                       plan_sort(images_dir, labels_dir, names, names_inv)))

    total = 0
    for name, scene, (plan, edits) in passes:
        added = sum(1 for e in edits if e.action == "add")
        replaced = sum(1 for e in edits if e.action == "replace")
        skipped = sum(1 for e in edits if e.action == "skip")
        print(f"\n=== pass {name}（{scene}）：改 {len(plan)} 帧"
              f"（补 {added} / 换 {replaced} / 跳过 {skipped}）")
        for e in edits:
            if e.action == "skip":
                print(f"   跳过 {e.frame[-26:]:26s} {e.detail}")
        for e in edits:
            if e.action != "skip":
                print(f"   {e.action:7s} {e.frame[-26:]:26s} "
                      f"{zh(e.class_name):16s} {e.detail}")
        total += len(plan)
        if args.render and plan:
            (ROOT / "logs" / "review").mkdir(parents=True, exist_ok=True)
            render(images_dir, plan, names,
                   ROOT / "logs" / "review" / f"_relabel_{name}.png", scene)

    print(f"\n合计待写 {total} 帧。")
    if not args.apply:
        print("dry-run：没有写任何文件（加 --apply 才写）。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = args.dataset / f"_relabel_backup_{stamp}"
    shutil.copytree(labels_dir, backup / "labels")
    print(f"\n已备份 labels/ → {backup.name}/labels/（{len(list(backup.glob('labels/*.txt')))} 个）")

    for _name, _scene, (plan, _edits) in passes:
        for stem, rows in plan.items():
            (labels_dir / f"{stem}.txt").write_text("\n".join(rows) + "\n",
                                                    encoding="utf-8")
    cache = args.dataset / "labels.cache"
    if cache.exists():
        cache.unlink()
        print("已删 labels.cache（增量改标注后不删会让新标注漏读）")
    print(f"已写 {total} 帧。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
