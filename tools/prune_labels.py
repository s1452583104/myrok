# -*- coding: utf-8 -*-
"""摘掉数据集里「训了也用不上」的标注行。

运行时 YOLO 只是模板匹配的兜底腿，而且被 manifest 的 ROI 硬门控
（`YoloClassAdapter.recognize` 拿**框中心**判 ROI，越界直接丢）。所以一条标注
只要满足下面任一条，运行时永远不可能被采纳——它不产生收益，只占着模型容量，
并把同一类的学习信号拉向一个用不到的模式（实测 `queue_battle_icon` 混了队列栏
33x33 与战争列表行 63x52 两种元素）：

1. **退化框**：框占到整幅 90% 以上。等于教模型「整张图就是它」，全屏推理时
   这个框永远不成立。`sort_selector` 的 6 条 261x35 裁剪帧就是这种：框 258x31，
   占整幅 99%x91%。
2. **非全屏帧上的标注**：ROI 是 1920x1080 的绝对像素，裁剪帧的归一化坐标根本
   不对应屏幕位置，ROI 门控无从谈起。没有 manifest ROI 的类没有门控可越，但
   只要它在整屏帧上**另有**标注（`sort_selector` / `sort_opt_*` 补标之后就是
   这样），裁剪帧上那批就是第二套坐标系——同一片像素两种尺度，YOLO 只能回归到
   折中，实机一个都检不出。一个类**只有**裁剪帧时不动它：删了就归零，那是更糟
   的处境。
3. **全屏帧上框中心越出该类 ROI**：运行时直接被 `YoloClassAdapter` 丢弃。

删完变成 0 框的帧必须**连帧一起撤**（图 + 标签 + train/val 行）：0 框帧是负样本，
而这帧恰恰是「这里有个 X」的正样本——留着等于教模型漏检。撤帧会改变 val 组成，
报告里会点出来。

默认只处理 `--classes` 列出的类（其余类里也有同类问题，但改动面更大，见报告）。
默认 dry-run，`--apply` 才写，写之前整份 labels + train/val 备份到
`dataset/_prune_backup_<时间戳>/`。

用法（仓库根目录）：
    .venv/Scripts/python.exe tools/prune_labels.py            # 只看报告
    .venv/Scripts/python.exe tools/prune_labels.py --apply    # 真删（先备份）
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

# 框占到整幅这个比例以上就算退化（「整张图都是它」）
DEGENERATE_FRACTION = 0.9

# 默认处理的类：本轮用户点名的三个约定问题
DEFAULT_CLASSES = ("sort_selector", "queue_battle_icon", "warning_panel")

# 规则 2/3 用：这些类是「有 ROI 的类」，裁剪帧标注与越界标注都不可用
NATIVE_W, NATIVE_H = 1920, 1080


@dataclass(frozen=True)
class Violation:
    frame: str
    class_name: str
    reason: str          # "退化框" / "越出ROI" / "非全屏帧"
    detail: str


def load_class_rois(dataset_yaml: Path, manifest: Path) -> dict[str, list[int] | None]:
    """类名 -> manifest ROI（不在 manifest 里、或无 roi 字段的返回 None）。"""
    names = {str(v) for v in yaml.safe_load(
        dataset_yaml.read_text(encoding="utf-8"))["names"].values()}
    rois: dict[str, list[int] | None] = {n: None for n in names}
    for t in yaml.safe_load(manifest.read_text(encoding="utf-8"))["templates"]:
        if t["id"] in rois:
            rois[t["id"]] = t.get("roi")
    return rois


def judge(class_name: str, cx: float, cy: float, w: float, h: float,
          size: tuple[int, int], roi: list[int] | None,
          has_fullscreen: bool = False) -> Violation | None:
    """单条标注的裁决：返回违规原因，或 None 表示可用。

    `cx/cy/w/h` 是归一化值，`size` 是该帧的 (宽, 高)。判 ROI 用**框中心**，
    与 `YoloClassAdapter.recognize` 的判法逐字对齐——判法不一致就会出现
    「标注留着、运行时却永远不采纳」的静默浪费。

    `has_fullscreen` 由 `_fullscreen_classes` 整库算出，只对**无 ROI** 的类起
    作用（有 ROI 的类在裁剪帧上一律违规，不必再问）。默认 False = 保守：判不了
    就不删。
    """
    iw, ih = size
    if w >= DEGENERATE_FRACTION and h >= DEGENERATE_FRACTION:
        return Violation("", class_name, "退化框",
                         f"框占整幅 {w:.0%}x{h:.0%}")
    if (iw, ih) != (NATIVE_W, NATIVE_H):
        if roi is not None:
            return Violation("", class_name, "非全屏帧",
                             f"帧 {iw}x{ih}，ROI {roi} 是 1920x1080 绝对像素")
        if has_fullscreen:
            return Violation("", class_name, "非全屏帧",
                             f"帧 {iw}x{ih}，同类在整屏帧上另有标注"
                             f"（同一类两套坐标系）")
        return None       # 该类只有裁剪帧：删了就归零，宁可留着
    if roi is None:
        return None       # 无 ROI 的类：整屏帧上没有门控可越
    px, py = cx * iw, cy * ih
    if not (roi[0] <= px < roi[2] and roi[1] <= py < roi[3]):
        return Violation("", class_name, "越出ROI",
                         f"中心 ({int(px)},{int(py)}) 不在 {roi}")
    return None


def _read_frames(dataset: Path) -> list[tuple[str, tuple[int, int], list[list[str]]]]:
    """整库读一遍 (帧名, 尺寸, 逐行拆好的标注)。没有配对图的标签文件跳过。

    尺寸和标注只在这里读一次：`scan`（裁决）和 `main`（落盘）共用同一份，
    否则「报告里说要删、写盘时又留下」这种漂移迟早发生。
    """
    from PIL import Image

    images_dir, labels_dir = dataset / "images", dataset / "labels"
    out = []
    for lab in sorted(labels_dir.glob("*.txt")):
        img = images_dir / f"{lab.stem}.png"
        if not img.exists():
            continue
        rows = [ln.split() for ln in
                lab.read_text(encoding="utf-8").splitlines() if ln.strip()]
        out.append((lab.stem, Image.open(img).size, rows))
    return out


def _fullscreen_classes(frames, names: dict[int, str],
                        classes: set[str]) -> set[str]:
    """在整屏帧上有**可用**（非退化）实例的类。

    无 ROI 的类要靠它才能判裁剪帧标注该不该撤：`sort_selector` / `sort_opt_*`
    在 manifest 里没有 ROI，规则 2 的 `roi is None` 早退把它们全保下来了——但
    2026-09-25 实测这 4 个类的 18 条标注**全在 279x162 这类裁剪帧上**，框是相对
    裁剪图归一化的。一旦在整屏帧上补出同类标注，两批就是两套坐标系，留着等于
    拿同一片像素教两个尺度（寨子宽框那种病）。

    退化框不算数：它自己就要被摘掉，不能拿它证明「这个类在整屏帧上站得住」。
    """
    out: set[str] = set()
    for _stem, size, rows in frames:
        if size != (NATIVE_W, NATIVE_H):
            continue
        for cid, _cx, _cy, w, h in rows:
            cname = names.get(int(cid))
            if (cname in classes
                    and not (float(w) >= DEGENERATE_FRACTION
                             and float(h) >= DEGENERATE_FRACTION)):
                out.add(cname)
    return out


def scan(dataset: Path, classes: set[str],
         rois: dict[str, list[int] | None] | None = None
         ) -> tuple[list[Violation], list[str]]:
    """扫一遍数据集，返回 (违规清单, 会变成 0 框的帧名)。

    只读，不动文件——dry-run 和 --apply 共用这一遍。`rois` 传 None 时读真实
    manifest；测试传显式字典，免得单测跟着 manifest 的改动漂。
    """
    if rois is None:
        rois = load_class_rois(dataset / "dataset.yaml",
                               ROOT / "templates" / "manifest.yaml")
    names = {int(k): str(v) for k, v in yaml.safe_load(
        (dataset / "dataset.yaml").read_text(encoding="utf-8"))["names"].items()}

    frames = _read_frames(dataset)
    fullscreen = _fullscreen_classes(frames, names, classes)

    violations: list[Violation] = []
    emptied: list[str] = []
    for stem, size, rows in frames:
        kept = 0
        for cid, cx, cy, w, h in rows:
            cname = names.get(int(cid))
            if cname is None or cname not in classes:
                kept += 1
                continue
            v = judge(cname, float(cx), float(cy), float(w), float(h), size,
                      rois.get(cname), has_fullscreen=cname in fullscreen)
            if v is None:
                kept += 1
            else:
                violations.append(Violation(stem, v.class_name, v.reason, v.detail))
        if rows and kept == 0:
            emptied.append(stem)
    return violations, emptied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    ap.add_argument("--manifest", type=Path,
                    default=ROOT / "templates" / "manifest.yaml",
                    help="ROI 来源（默认 templates/manifest.yaml）")
    ap.add_argument("--classes", default=",".join(DEFAULT_CLASSES),
                    help=f"要处理的类，逗号分隔（默认 {','.join(DEFAULT_CLASSES)}）")
    ap.add_argument("--apply", action="store_true", help="真删（默认只报告）")
    args = ap.parse_args()

    classes = {c.strip() for c in args.classes.split(",") if c.strip()}
    dataset = args.dataset
    images_dir, labels_dir = dataset / "images", dataset / "labels"
    train_txt, val_txt = dataset / "train.txt", dataset / "val.txt"
    rois = load_class_rois(dataset / "dataset.yaml", args.manifest)

    violations, emptied = scan(dataset, classes, rois=rois)
    if not violations and not emptied:
        print("没有需要摘掉的标注行。")
        return 0

    by_reason: dict[str, list[Violation]] = {}
    for v in violations:
        by_reason.setdefault(v.reason, []).append(v)

    print(f"待摘 {len(violations)} 条标注，涉及 "
          f"{len({v.frame for v in violations})} 帧：\n")
    for reason, vs in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        by_cls: dict[str, int] = {}
        for v in vs:
            by_cls[v.class_name] = by_cls.get(v.class_name, 0) + 1
        print(f"  [{reason}] {len(vs)} 条  " +
              "  ".join(f"{k}×{n}" for k, n in sorted(by_cls.items())))
        for v in vs[:4]:
            print(f"      {v.frame[:46]:46s} {v.detail}")
        if len(vs) > 4:
            print(f"      …… 另 {len(vs) - 4} 条")

    if emptied:
        print(f"\n摘完变 0 框、必须连帧一起撤的 {len(emptied)} 帧"
              f"（0 框帧是负样本，而这些帧恰恰是正样本）：")
        for stem in emptied:
            print(f"      {stem}")
        val_stems = {Path(p).stem for p in _read_list(val_txt)}
        n_val = sum(1 for s in emptied if s in val_stems)
        print(f"      其中在 val 里的 {n_val} 帧 —— val 组成会变，"
              f"指标不能与上一版直接比")

    if not args.apply:
        print(f"\n[未改动] 加 --apply 真删（会先整份备份）。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = dataset / f"_prune_backup_{stamp}"
    shutil.copytree(labels_dir, backup / "labels")
    for p in (train_txt, val_txt):
        shutil.copy2(p, backup / p.name)
    # 撤帧会连图一起删，图不在 labels/ 里 —— 不单独备份就再也拿不回来了
    # （实测踩过：8 帧的图删掉后 recordings/ 里也没有原件，只剩标注无从复原）。
    if emptied:
        (backup / "images").mkdir()
        for stem in emptied:
            src = images_dir / f"{stem}.png"
            if src.exists():
                shutil.copy2(src, backup / "images" / src.name)
    print(f"\n已备份到 {backup.name}/（labels 全量 + train.txt + val.txt"
          f"{f' + {len(emptied)} 帧原图' if emptied else ''}）")

    # 1) 逐帧重写标签，摘掉违规行（判法与 scan 同一个 judge，不另写一遍；
    #    连 has_fullscreen 也沿用 scan 那份，否则两边会得出不同的行集）
    names = {int(k): str(v) for k, v in yaml.safe_load(
        (dataset / "dataset.yaml").read_text(encoding="utf-8"))["names"].items()}
    frames = {stem: (size, rows) for stem, size, rows in _read_frames(dataset)}
    fullscreen = _fullscreen_classes(
        [(s, sz, r) for s, (sz, r) in frames.items()], names, classes)
    for stem in sorted({v.frame for v in violations}):
        size, rows = frames[stem]
        lab = labels_dir / f"{stem}.txt"
        kept = []
        for cid, cx, cy, w, h in rows:
            cname = names.get(int(cid))
            if (cname in classes
                    and judge(cname, float(cx), float(cy), float(w), float(h),
                              size, rois.get(cname),
                              has_fullscreen=cname in fullscreen) is not None):
                continue
            kept.append(" ".join((cid, cx, cy, w, h)))
        _write_list(lab, kept)

    # 2) 撤掉变 0 框的帧：图 + 标签 + train/val 行
    for stem in emptied:
        (images_dir / f"{stem}.png").unlink(missing_ok=True)
        (labels_dir / f"{stem}.txt").unlink(missing_ok=True)
    dropped = {s.lower() for s in emptied}
    train = [p for p in _read_list(train_txt) if Path(p).stem.lower() not in dropped]
    val = [p for p in _read_list(val_txt) if Path(p).stem.lower() not in dropped]
    _write_list(train_txt, train)
    _write_list(val_txt, val)

    (dataset / "labels.cache").unlink(missing_ok=True)
    print(f"已摘 {len(violations)} 条标注、撤 {len(emptied)} 帧；"
          f"train {len(train)} 行 / val {len(val)} 行；已删 labels.cache")
    print(f"要回滚：把 {backup.name}/labels/*.txt 拷回 dataset/labels/，"
          f"train.txt/val.txt 同理；撤掉的图在 {backup.name}/images/ 里。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
