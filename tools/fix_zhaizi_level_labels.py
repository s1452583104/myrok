# -*- coding: utf-8 -*-
"""修正 `zhaizi_level_text` 的污染标注：宽框改回紧框，锚错的整条删掉。

**污染怎么来的。** 三层预标注里有一层是「OCR 文本锚定 `zhaizi_level_text`」：
在等级行的 ROI 内找含「等级」的文本块，拿它的 bbox 当标注框。RapidOCR 把
「等级：3 您的城市附近暂未找到符合条件的野蛮人城寨。」**识别成两个块**，锚定
那步却按「块里含『等级』」取，于是同一屏的标注在不同帧上分裂成两套尺寸：

- 紧框 ~95x30，只圈「等级：N」（33 条，含 manual3 的 lvl1..lvl10）；
- 宽框 286~802px，把后面那句提示文字一起圈进来（15 条，等级 1~8）。

同一位置、同一类、两种差 8 倍的框，YOLO 只能回归到两者的折中：实测 v8 在
用户存的等级 1~10 实机帧上，`zhaizi_level_text` 只在 7/8/9/10 出框且置信度
仅 0.12~0.28（默认阈值 0.5 下等于不出框），等级 1~6 **一个框都没有**。
这就是用户报的「1-6 级不识别」。

还有 2 条是**锚错了对象**：`215522-415` 之外的两帧其实是世界地图上的城寨信息
弹窗，画面里根本没有搜索面板的等级文本，预标注却锚到了「推荐兵力：1,400,000
等级4的战斗单位集结进攻」这行提示里的「等级4」。这类直接删——改成紧框也是错的。

**判据（可测、非魔数）。** 搜索面板的等级文本是**独立的一个文本块**，文字形如
「等级：N」。所以：OCR 块文字能整块匹配 `^等级[：:]\\d+$` 才算锚点，锚点存在
就把框改成锚点 bbox（按 `PAD` 外扩，见下），锚点不存在就删这条标注。

`PAD=4` 不是随手取的：OCR 的 bbox 紧贴字形（实测 92x26），而本类**现有**的紧框
统一留了边距（manual3 的 100x34）。外扩 4px 正好让两者对齐（92+8=100，26+8=34），
同类内就不会再出现两套框尺寸——那正是这次污染的成因。

`MAX_W_PX=200` 只用来**筛出可疑项**，不是判据本身：现有 33 条紧框最宽 123px，
最小的宽框 286px，200 落在这个空档里。窄于它的标注一律不碰（避免把 33 条好
标注也拿去重算）。

默认 dry-run，`--apply` 才写；写之前整份 labels + train/val 备份到
`dataset/_levelfix_backup_<时间戳>/`。

用法（仓库根目录）：
    .venv/Scripts/python.exe -X utf8 tools/fix_zhaizi_level_labels.py
    .venv/Scripts/python.exe -X utf8 tools/fix_zhaizi_level_labels.py --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

CLASS_NAME = "zhaizi_level_text"

# 宽于此值才拿去做 OCR 重算（现有紧框最宽 123，最小宽框 286）
MAX_W_PX = 200

# 等级行 ROI（1920x1080 绝对像素，从实测紧框推：cy≈529，框高≈30）
ROI = (100, 470, 1040, 620)

# 锚点 bbox 的外扩量：让 OCR 紧框对齐本类现有标注的留边（见模块 docstring）
PAD = 4

# 搜索面板的等级文本块就是「等级：N」一整块
LEVEL_RE = re.compile(r"^等级\s*[：:]\s*\d+$")


@dataclass(frozen=True)
class Fix:
    frame: str
    row_index: int     # 该行在 labels/<frame>.txt 里的行号（0 起）
    action: str        # "retighten" / "drop"
    old_px: tuple[int, int, int, int]
    new_px: tuple[int, int, int, int] | None
    note: str


def anchor_from_blocks(blocks) -> tuple[int, int, int, int] | None:
    """从 OCR 文本块里找等级锚点，返回外扩后的 bbox（像素），找不到返回 None。

    `blocks` 是 (x1, y1, x2, y2, text) 序列。**整块**匹配才算——「推荐兵力：
    1,400,000等级4的战斗单位集结进攻」这种含「等级」的长句必须被拒掉，否则
    就是这次污染的复现。取最靠左的合格块（等级数字在「等级：」右侧的布局保证
    不会有两块）。
    """
    hits = [b for b in blocks if LEVEL_RE.match(b[4].strip())]
    if not hits:
        return None
    x1, y1, x2, y2, _t = min(hits, key=lambda b: b[0])
    return (x1 - PAD, y1 - PAD, x2 + PAD, y2 + PAD)


def _ocr_blocks(img, roi: tuple[int, int, int, int], engine) -> list[tuple]:
    x1, y1, x2, y2 = roi
    crop = img[y1:y2, x1:x2]
    out = []
    for bb, text, _conf in engine.detect_text(crop):
        out.append((x1 + bb.x1, y1 + bb.y1, x1 + bb.x2, y1 + bb.y2, text))
    return out


def scan(dataset: Path, engine=None) -> tuple[list[Fix], list[str]]:
    """扫一遍数据集，返回 (待改清单, 改完会变 0 框的帧)。

    只读。`engine` 传 None 时懒加载真 OCR（测试传假的，免得跑模型）。
    """
    import cv2

    names = {int(k): str(v) for k, v in yaml.safe_load(
        (dataset / "dataset.yaml").read_text(encoding="utf-8"))["names"].items()}
    cid = next(k for k, v in names.items() if v == CLASS_NAME)
    images_dir, labels_dir = dataset / "images", dataset / "labels"

    fixes: list[Fix] = []
    emptied: list[str] = []
    for lab in sorted(labels_dir.glob("*.txt")):
        rows = [ln for ln in lab.read_text(encoding="utf-8").splitlines() if ln.strip()]
        wide = []
        for i, ln in enumerate(rows):
            p = ln.split()
            if len(p) == 5 and int(p[0]) == cid:
                cx, cy, w, h = (float(v) for v in p[1:])
                if w * 1920 > MAX_W_PX:
                    wide.append((i, (int((cx - w / 2) * 1920), int((cy - h / 2) * 1080),
                                     int((cx + w / 2) * 1920), int((cy + h / 2) * 1080))))
        if not wide:
            continue
        img = cv2.imread(str(images_dir / f"{lab.stem}.png"))
        if img is None:
            print(f"!! 读不了图，跳过：{lab.stem}")
            continue
        if engine is None:
            from rok_assistant.core.recognizers.ocr_text import RapidOcrEngine
            engine = RapidOcrEngine()
        blocks = _ocr_blocks(img, ROI, engine)
        anchor = anchor_from_blocks(blocks)
        for i, old in wide:
            if anchor is None:
                fixes.append(Fix(lab.stem, i, "drop", old, None,
                                 "等级行里没有「等级：N」独立文本块——锚错了对象"))
            else:
                fixes.append(Fix(lab.stem, i, "retighten", old, anchor, ""))
        if anchor is None and len(rows) == len(wide):
            emptied.append(lab.stem)
    return fixes, emptied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    ap.add_argument("--apply", action="store_true", help="真改（默认只报告）")
    args = ap.parse_args()

    dataset = args.dataset
    images_dir, labels_dir = dataset / "images", dataset / "labels"
    train_txt, val_txt = dataset / "train.txt", dataset / "val.txt"

    fixes, emptied = scan(dataset)
    if not fixes:
        print(f"{CLASS_NAME} 没有需要修正的宽框标注。")
        return 0

    val_stems = {Path(p).stem.lower() for p in
                 val_txt.read_text(encoding="utf-8").splitlines() if p.strip()}
    ret = [f for f in fixes if f.action == "retighten"]
    drop = [f for f in fixes if f.action == "drop"]

    print(f"待改 {len(fixes)} 条 {CLASS_NAME} 标注，"
          f"涉及 {len({f.frame for f in fixes})} 帧：")
    print(f"  改紧框 {len(ret)} 条（宽 "
          f"{min(f.old_px[2]-f.old_px[0] for f in ret)}~"
          f"{max(f.old_px[2]-f.old_px[0] for f in ret)}px -> "
          f"{min(f.new_px[2]-f.new_px[0] for f in ret)}~"
          f"{max(f.new_px[2]-f.new_px[0] for f in ret)}px）")
    print(f"  整条删 {len(drop)} 条：")
    for f in drop:
        print(f"      {f.frame[:52]:52s} 原框 {f.old_px[2]-f.old_px[0]}x"
              f"{f.old_px[3]-f.old_px[1]}  {f.note}")
    print()
    for f in ret:
        print(f"      {f.frame[:52]:52s} {f.old_px[2]-f.old_px[0]:4d}x"
              f"{f.old_px[3]-f.old_px[1]:<3d} -> {f.new_px[2]-f.new_px[0]:3d}x"
              f"{f.new_px[3]-f.new_px[1]:<3d} @x{f.new_px[0]}")
    n_val = sum(1 for f in fixes if f.frame.lower() in val_stems)
    print(f"\n其中 {n_val} 帧在 val 里 —— val 组成会变，指标不能与上一版直接比。")
    if emptied:
        print(f"\n改完变 0 框的 {len(emptied)} 帧（{', '.join(emptied)}）："
              f"这些帧里没有任何真目标，留作负样本是对的，不撤帧。")

    if not args.apply:
        print("\n[未改动] 加 --apply 真改（会先整份备份）。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = dataset / f"_levelfix_backup_{stamp}"
    shutil.copytree(labels_dir, backup / "labels")
    for p in (train_txt, val_txt):
        shutil.copy2(p, backup / p.name)
    print(f"\n已备份到 {backup.name}/（labels 全量 + train.txt + val.txt）")

    names = {int(k): str(v) for k, v in yaml.safe_load(
        (dataset / "dataset.yaml").read_text(encoding="utf-8"))["names"].items()}
    cid = next(k for k, v in names.items() if v == CLASS_NAME)
    by_frame: dict[str, list[Fix]] = {}
    for f in fixes:
        by_frame.setdefault(f.frame, []).append(f)

    for stem, fs in sorted(by_frame.items()):
        lab = labels_dir / f"{stem}.txt"
        rows = [ln for ln in lab.read_text(encoding="utf-8").splitlines() if ln.strip()]
        # 按**行号**定位要改的那一行，不按重算出来的像素坐标比对：归一化写回时
        # 六位小数的取整会让重算值差 1px（801px 的框写 0.417188 就足以偏一格），
        # 拿坐标当键等于把改动系在小数点后第六位上。
        plan = {f.row_index: f for f in fs}
        out = []
        for i, ln in enumerate(rows):
            fix = plan.get(i)
            if fix is None:
                out.append(ln)
                continue
            if int(ln.split()[0]) != cid:
                raise RuntimeError(f"{stem}:{i + 1} 不是 {CLASS_NAME}，未写入")
            if fix.action == "drop":
                continue
            x1, y1, x2, y2 = fix.new_px
            cx, cy = (x1 + x2) / 2 / 1920, (y1 + y2) / 2 / 1080
            bw, bh = (x2 - x1) / 1920, (y2 - y1) / 1080
            out.append(f"{cid} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
        # 行号重复、或落在文件外，都会让某条 Fix 静默失效——报告说改了、其实没改，
        # 正是这次要清掉的那种「看着没问题」的污染。宁可炸掉。
        if len(plan) != len(fs) or max(plan) >= len(rows):
            raise RuntimeError(f"{stem}: 行号对不上（{len(fs)} 条待改 / "
                               f"{len(rows)} 行），未写入")
        lab.write_text("\n".join(out) + "\n", encoding="utf-8")

    (dataset / "labels.cache").unlink(missing_ok=True)
    print(f"已改 {len(fixes)} 条；已删 labels.cache")
    print(f"要回滚：把 {backup.name}/labels/*.txt 拷回 dataset/labels/ 即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
