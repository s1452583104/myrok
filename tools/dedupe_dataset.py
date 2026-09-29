# -*- coding: utf-8 -*-
"""去掉 dataset/ 里像素完全相同的重复帧，并修掉它们造成的 train/val 泄漏。

为什么必须处理：同一张图出现两次、两次标注又不一致时，模型对**同一份输入**同时收到
「这里有个 X」和「这里没有 X」两种监督——比单纯多算一张图有害得多。更糟的是当孪生帧
一个落在 train 一个落在 val，val 指标直接虚高（实测 3 组）。

幸存者挑选：标注更全的那一份（同一张图的两遍标注往往互补，留少的那份等于丢标注）。
组内每份的标注互相矛盾时这里不做合并——合并需要判断哪一遍是对的，那是人工的活，
本工具只保证「同一张图只有一份」。

用法（仓库根目录）：
    .venv/Scripts/python.exe tools/dedupe_dataset.py            # 只看报告（默认不动文件）
    .venv/Scripts/python.exe tools/dedupe_dataset.py --apply    # 真删
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from ingest_raw_imgs import _read_list, _write_list  # noqa: E402


def _label_count(labels_dir: Path, stem: str) -> int:
    p = labels_dir / f"{stem}.txt"
    if not p.exists():
        return 0
    return len([ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()])


def find_duplicate_groups(images_dir: Path) -> list[list[str]]:
    """按文件内容分组，返回像素完全相同的组（组内 >1 个成员）。"""
    by_hash: dict[str, list[str]] = collections.defaultdict(list)
    for p in sorted(images_dir.glob("*.png")):
        by_hash[hashlib.md5(p.read_bytes()).hexdigest()].append(p.stem)
    return [sorted(v) for v in by_hash.values() if len(v) > 1]


def pick_survivor(group: list[str], labels_dir: Path) -> str:
    """留标注最多的那份；并列时取名字最小的，保证结果可复现。"""
    return max(sorted(group), key=lambda s: (_label_count(labels_dir, s),))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    ap.add_argument("--apply", action="store_true", help="真删（默认只报告）")
    args = ap.parse_args()

    images_dir = args.dataset / "images"
    labels_dir = args.dataset / "labels"
    train_txt = args.dataset / "train.txt"
    val_txt = args.dataset / "val.txt"

    groups = find_duplicate_groups(images_dir)
    if not groups:
        print("没有像素完全相同的重复帧。")
        return 0

    train, val = _read_list(train_txt), _read_list(val_txt)
    split = {Path(p).stem: "train" for p in train}
    for p in val:
        split[Path(p).stem] = "val"

    drop: list[tuple[str, str]] = []      # (幸存者, 被删)
    promote: list[tuple[str, str]] = []   # (幸存者, 该进哪个 split)
    for g in groups:
        survivor = pick_survivor(g, labels_dir)
        for stem in g:
            if stem == survivor:
                continue
            drop.append((survivor, stem))
        if survivor not in split:
            # 幸存者没进任何 split，但它的孪生帧进了 → 把幸存者补进去，别丢这一帧
            others = {split[s] for s in g if s in split}
            promote.append((survivor, "val" if others == {"val"} else "train"))

    print(f"重复组 {len(groups)} 组，待删 {len(drop)} 帧\n")
    for survivor, stem in drop:
        a, b = _label_count(labels_dir, survivor), _label_count(labels_dir, stem)
        leak = "  <<< 跨 train/val 泄漏" if split.get(survivor) != split.get(stem) else ""
        print(f"  删 {stem:<48} ({split.get(stem, '未入split')}, {b} 标注)"
              f"\n    留 {survivor} ({split.get(survivor, '未入split')}, {a} 标注){leak}")
    for survivor, target in promote:
        print(f"  补进 {target}.txt：{survivor}（原本没在任何 split 里）")

    if not args.apply:
        print(f"\n[未改动] 加 --apply 真删。")
        return 0

    dropped_stems = {stem for _, stem in drop}
    for _, stem in drop:
        (images_dir / f"{stem}.png").unlink(missing_ok=True)
        (labels_dir / f"{stem}.txt").unlink(missing_ok=True)

    train = [p for p in train if Path(p).stem not in dropped_stems]
    val = [p for p in val if Path(p).stem not in dropped_stems]
    for survivor, target in promote:
        (train if target == "train" else val).append(
            str((images_dir / f"{survivor}.png").resolve()))

    # 收尾对账：删完之后不能有帧同时留在两边，也不能有指向缺失文件的行
    train_lower = {p.lower() for p in train}
    val = [p for p in val if p.lower() not in train_lower]
    for name, lines in (("train", train), ("val", val)):
        gone = [p for p in lines if not Path(p).exists()]
        if gone:
            print(f"  警告：{name}.txt 有 {len(gone)} 行指向缺失文件，已摘掉")
        lines[:] = [p for p in lines if Path(p).exists()]

    _write_list(train_txt, train)
    _write_list(val_txt, val)
    (args.dataset / "labels.cache").unlink(missing_ok=True)
    print(f"\n已删 {len(drop)} 帧；train {len(train)} 行 / val {len(val)} 行；"
          f"已删 labels.cache（下次训练自动重建）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
