# -*- coding: utf-8 -*-
"""找出并撤掉数据集里的「0 框帧」——它们是假负样本。

**为什么 0 框帧有害。** YOLO 把「有图无框」当纯背景样本，反向梯度教模型「这张图
里没有目标」。如果图里其实有目标（只是入库时没检出），留着它每天都在削弱那个类。
`tools/prune_labels.py` 已经把这条道理写在 docstring 里了，但它只管**被自己摘空**
的帧，管不到**生下来就是 0 框**的帧——这批正是从这个缝里漏进来的。

**这批 0 框帧是怎么来的（2026-10-03 实测）。**

1. **模板素材的裁剪图**被当成检测样本灌进了 `dataset/images/`：`scenes___z_join.png`
   画的就是绿色「+」按钮（`join_create_btn`），标签却是 0 行。文件名与类名一一对应
   （`z_redrally`→`red_rally`、`z_wartitle`→`war_title`、`z_magnifier`→`search_icon`、
   `z_sort`→`sort_selector`……），另有 4 张 `window_check__win_*.png` 窗口截图。
   判据是**尺寸**：manifest 的 ROI 是 1920x1080 绝对像素，裁剪帧的归一化坐标对不上
   屏幕位置，运行时永远不可能被采纳（同 `prune_labels.py` 规则 2）。撤掉它们在数学
   上不可能让任何类归零——它们的标签本来就是 0 行。
2. **动画过渡帧落在阈值下**：`failure_mumu1_char_jy_20260915_001019.png` 与四张已标
   `warning_panel` 的帧近乎同图（mad=0.0071），而它自己的 `warning_panel` 模板读数
   只有 0.664 < 阈值 0.85——就是 `queue_flag_icon` 0.758 那个病的同款：入库时读不到
   → 写成 0 框。判据是**近重复**：与「有标注的孪生帧」的下采样灰度平均绝对差（mad）。

**两组分开处置，因为证据强度不同。** 裁剪帧组按**尺寸**判——这是硬判据，`--apply`
直接撤。整屏组靠**近重复**判——这是概率证据，脚本只出报告，要撤得显式
`--drop <帧名>`，不替人拍板。

默认 dry-run，`--apply` 才写；写之前整份 labels + train/val + **每一张被撤帧的原图**
备份到 `dataset/_emptyfix_backup_<时间戳>/`（`prune_labels.py` 的教训：只备份 labels，
图删了就再也拿不回来）。

用法（仓库根目录）：
    .venv/Scripts/python.exe -X utf8 tools/audit_empty_frames.py              # 只看报告
    .venv/Scripts/python.exe -X utf8 tools/audit_empty_frames.py --apply      # 撤裁剪帧组
    .venv/Scripts/python.exe -X utf8 tools/audit_empty_frames.py --apply \\
        --drop failure_mumu1_char_jy_20260915_001019.png
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from ingest_raw_imgs import _read_list, _write_list  # noqa: E402

# 运行时 ROI 是这套绝对像素，只有这个尺寸的帧能用
NATIVE_W, NATIVE_H = 1920, 1080
NATIVE = (NATIVE_W, NATIVE_H)

# 近重复签名：缩到 64x36 灰度。实测同一画面 mad≈0.001~0.007，不同画面 ≥0.08，
# 中间是空档——所以阈值不卡刀尖（报告里同时打印次近邻，能看出落差）。
SIG_W, SIG_H = 64, 36
DEFAULT_MAX_MAD = 0.03


@dataclass(frozen=True)
class EmptyFrame:
    """一张 0 框帧，连同它的判决依据。"""

    stem: str
    size: tuple[int, int]
    split: str                       # "train" / "val" / "none"
    is_crop: bool
    verdict: str                     # "crop" / "false_negative" / "background"
    nearest: str = ""                # 最近的邻居（不论有没有标注）
    nearest_mad: float = 1.0
    twin: str = ""                   # 最近的**有标注**邻居
    twin_mad: float = 1.0
    twin_classes: tuple[str, ...] = ()
    runner_mad: float = 1.0          # 次近的有标注邻居，用来看落差


def _label_rows(dataset: Path, stem: str) -> list[list[str]]:
    p = dataset / "labels" / f"{stem}.txt"
    if not p.exists():
        return []
    return [ln.split() for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _signature(path: Path):
    """64x36 灰度签名。读不了就返回 None（调用方跳过，不猜）。"""
    import cv2
    img = cv2.imread(str(path), cv2.IMREAD_REDUCED_GRAYSCALE_8)
    if img is None:
        return None
    return cv2.resize(img, (SIG_W, SIG_H)).astype("float32") / 255.0


def scan(dataset: Path, max_mad: float = DEFAULT_MAX_MAD
         ) -> tuple[list[EmptyFrame], list[EmptyFrame]]:
    """扫一遍数据集，返回 (裁剪帧组, 整屏帧组)。只读。

    遍历的是 `images/` 而不是 `labels/`——**标签文件缺失也是 0 框帧**，
    按 labels 遍历会把它整个漏掉。
    """
    import numpy as np
    from PIL import Image

    images_dir = dataset / "images"
    train = {Path(p).stem.lower() for p in _read_list(dataset / "train.txt")}
    val = {Path(p).stem.lower() for p in _read_list(dataset / "val.txt")}
    names = {int(k): str(v) for k, v in yaml.safe_load(
        (dataset / "dataset.yaml").read_text(encoding="utf-8"))["names"].items()}

    empties: list[tuple[str, tuple[int, int], str]] = []
    labeled_full: set[str] = set()
    for img in sorted(images_dir.glob("*.png")):
        rows = _label_rows(dataset, img.stem)
        with Image.open(img) as im:
            size = im.size
        if rows:
            if size == NATIVE:
                labeled_full.add(img.stem)
            continue
        split = ("train" if img.stem.lower() in train
                 else "val" if img.stem.lower() in val else "none")
        empties.append((img.stem, size, split))

    # 近重复只在**整屏帧之间**比：归一化坐标只在同尺寸帧之间可迁移，拿裁剪帧
    # 当孪生毫无意义（它的 mad 高低都不说明任何事）。
    sigs: dict[str, object] = {}
    for stem in sorted(labeled_full | {e[0] for e in empties if e[1] == NATIVE}):
        s = _signature(images_dir / f"{stem}.png")
        if s is not None:
            sigs[stem] = s

    crop_group: list[EmptyFrame] = []
    full_group: list[EmptyFrame] = []
    for stem, size, split in empties:
        if size != NATIVE:
            crop_group.append(EmptyFrame(stem, size, split, True, "crop"))
            continue
        me = sigs.get(stem)
        scored: list[tuple[float, str]] = []
        if me is not None:
            for other, s in sigs.items():
                if other != stem:
                    scored.append((float(np.abs(me - s).mean()), other))
            scored.sort()
        labeled_hits = [(m, o) for m, o in scored if o in labeled_full]
        twin, twin_mad = (labeled_hits[0][1], labeled_hits[0][0]) if labeled_hits \
            else ("", 1.0)
        runner = labeled_hits[1][0] if len(labeled_hits) > 1 else 1.0
        classes: tuple[str, ...] = ()
        if twin:
            classes = tuple(sorted({names.get(int(r[0]), str(r[0]))
                                    for r in _label_rows(dataset, twin)}))
        full_group.append(EmptyFrame(
            stem, size, split, False,
            "false_negative" if twin_mad <= max_mad else "background",
            nearest=scored[0][1] if scored else "",
            nearest_mad=scored[0][0] if scored else 1.0,
            twin=twin, twin_mad=twin_mad, twin_classes=classes,
            runner_mad=runner))
    return crop_group, full_group


def _print_group(title: str, frames: list[EmptyFrame], dataset: Path,
                 show_twins: bool) -> None:
    n_val = sum(1 for f in frames if f.split == "val")
    print(f"\n[{title}] {len(frames)} 张"
          f"{f'（其中 val {n_val} 张）' if n_val else ''}")
    for f in frames:
        w, h = f.size
        print(f"    {f.stem:<44s} {w}x{h:<6d} {f.split}")
        if not show_twins:
            continue
        if f.nearest:
            print(f"        最近邻 {f.nearest}  mad={f.nearest_mad:.4f}"
                  f"（{len(_label_rows(dataset, f.nearest))} 标注）")
        if f.verdict == "false_negative":
            print(f"        >>> 疑似漏标：{f.twin} mad={f.twin_mad:.4f}"
                  f"（标注 {', '.join(f.twin_classes)}）"
                  f"，次近邻 mad={f.runner_mad:.4f}")
        else:
            print(f"        无近重复的有标注孪生"
                  f"（最近的有标注邻 {f.twin or '无'} mad={f.twin_mad:.4f}）"
                  f" → 背景，保留")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    ap.add_argument("--apply", action="store_true", help="真撤（默认只报告）")
    ap.add_argument("--drop", action="append", default=[],
                    help="额外撤掉的整屏帧名（可重复；近重复是概率证据，"
                         "由人点名）")
    ap.add_argument("--keep", action="append", default=[],
                    help="从裁剪帧组里豁免的帧名（可重复）")
    ap.add_argument("--max-mad", type=float, default=DEFAULT_MAX_MAD,
                    help=f"判「近重复」的 mad 上限（默认 {DEFAULT_MAX_MAD}）")
    args = ap.parse_args()

    dataset = args.dataset
    images_dir, labels_dir = dataset / "images", dataset / "labels"
    train_txt, val_txt = dataset / "train.txt", dataset / "val.txt"

    crop_group, full_group = scan(dataset, args.max_mad)
    total = len(crop_group) + len(full_group)
    n_val = sum(1 for f in crop_group + full_group if f.split == "val")
    print(f"0 框帧 {total} 张" + (f"（其中 {n_val} 张在 val）" if n_val else ""))

    _print_group("裁剪帧 · ROI 门控下不可用，--apply 撤", crop_group, dataset,
                 show_twins=False)
    _print_group("整屏帧 · 逐个判，默认不动", full_group, dataset,
                 show_twins=True)

    keep = set(args.keep)
    known = {f.stem for f in crop_group + full_group}
    unknown = [s for s in args.drop if s not in known]
    if unknown:
        print(f"\n--drop 里有不是 0 框帧的名字：{', '.join(unknown)}")
        return 2
    unknown = [s for s in keep if s not in {f.stem for f in crop_group}]
    if unknown:
        print(f"\n--keep 里有不在裁剪帧组里的名字：{', '.join(unknown)}")
        return 2

    removed = ([f.stem for f in crop_group if f.stem not in keep]
               + [s for s in args.drop if s not in keep])

    if not args.apply:
        print(f"\n[未改动] --apply 会撤 {len(removed)} 帧"
              f"（裁剪帧 {len(crop_group)} − keep {len(keep)}"
              f" + --drop {len(args.drop)}）。")
        print("整屏帧里要撤的，用 --drop <帧名> 点名。")
        return 0

    if not removed:
        print("\n没有要撤的帧。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = dataset / f"_emptyfix_backup_{stamp}"
    shutil.copytree(labels_dir, backup / "labels")
    for p in (train_txt, val_txt):
        shutil.copy2(p, backup / p.name)
    # 撤帧会连图一起删，图不在 labels/ 里 —— 不单独备份就再也拿不回来了
    (backup / "images").mkdir()
    for stem in removed:
        src = images_dir / f"{stem}.png"
        if src.exists():
            shutil.copy2(src, backup / "images" / src.name)
    print(f"\n已备份到 {backup.name}/（labels 全量 + train.txt + val.txt"
          f" + {len(removed)} 帧原图）")

    for stem in removed:
        (images_dir / f"{stem}.png").unlink(missing_ok=True)
        (labels_dir / f"{stem}.txt").unlink(missing_ok=True)

    gone = {s.lower() for s in removed}
    train = [p for p in _read_list(train_txt) if Path(p).stem.lower() not in gone]
    val = [p for p in _read_list(val_txt) if Path(p).stem.lower() not in gone]

    # 收尾对账：删完不能有帧同时留在两边，也不能留指向缺失文件的行
    train_lower = {p.lower() for p in train}
    val = [p for p in val if p.lower() not in train_lower]
    for name, lines in (("train", train), ("val", val)):
        dangling = [p for p in lines if not Path(p).exists()]
        if dangling:
            print(f"  警告：{name}.txt 有 {len(dangling)} 行指向缺失文件，已摘掉")
        lines[:] = [p for p in lines if Path(p).exists()]

    _write_list(train_txt, train)
    _write_list(val_txt, val)
    (dataset / "labels.cache").unlink(missing_ok=True)
    print(f"已撤 {len(removed)} 帧；train {len(train)} 行 / val {len(val)} 行；"
          f"已删 labels.cache")
    print(f"要回滚：把 {backup.name}/labels/*.txt 拷回 dataset/labels/，"
          f"train.txt/val.txt 同理；撤掉的图在 {backup.name}/images/ 里。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
