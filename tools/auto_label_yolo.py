"""Auto-label YOLO dataset from recorded frames using existing template manifest.

Runs every template in templates/manifest.yaml over recordings/**/*.png with
multi-match (not just the single best hit), writes YOLO-format labels plus a
stats report showing per-class coverage and "gray zone" frames that would need
LLM/manual review.

Usage:
    .venv/Scripts/python.exe tools/auto_label_yolo.py            # full run
    .venv/Scripts/python.exe tools/auto_label_yolo.py --limit 50 # quick trial
    .venv/Scripts/python.exe tools/auto_label_yolo.py --visualize 8

Outputs (default dataset/):
    images/<flat>.png            hardlinks to recording frames (flat names:
                                 relative path with separators -> "__")
    labels/<flat>.txt            YOLO labels (class_id cx cy w h, normalized)
    train.txt / val.txt          image path lists for ultralytics
    dataset.yaml                 ultralytics dataset config
    stats.json                   per-class box counts + gray-zone candidates

Note: ultralytics maps image->label by replacing "\\images\\" with
"\\labels\\", so images and labels must live in parallel flat folders.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
from pathlib import Path

import cv2
import numpy as np

from rok_assistant.core.template_registry import TemplateRegistry

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDINGS = ROOT / "recordings"
DEFAULT_MANIFEST = ROOT / "templates" / "manifest.yaml"
DEFAULT_OUT = ROOT / "dataset"

# a match is only counted as a "gray zone review candidate" when the best
# score landed this close below the threshold (closer = more likely a real
# instance the threshold missed)
GRAY_ZONE_MARGIN = 0.15
MAX_MATCHES_PER_TEMPLATE = 10


def multi_match(frame: np.ndarray, tmpl: np.ndarray, threshold: float,
                roi: tuple[int, int, int, int] | None) -> tuple[list[dict], float]:
    """All template matches >= threshold in frame, greedy with zero-out NMS.

    Returns (matches, best_score) where best_score is the max correlation in
    the ROI regardless of threshold (used for gray-zone stats).
    Each match: {"bbox": (x1, y1, x2, y2), "conf": float}.
    """
    ox, oy = 0, 0
    img = frame
    if roi is not None:
        x1, y1, x2, y2 = roi
        ox, oy = x1, y1
        img = frame[y1:y2, x1:x2]
    if img.shape[0] < tmpl.shape[0] or img.shape[1] < tmpl.shape[1]:
        return [], 0.0

    result = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
    best_score = float(result.max())
    th, tw = tmpl.shape[:2]
    matches: list[dict] = []
    # zero-out margin suppresses near-duplicate peaks around the same object
    margin_y = max(2, th // 4)
    margin_x = max(2, tw // 4)
    for _ in range(MAX_MATCHES_PER_TEMPLATE):
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < threshold:
            break
        lx, ly = max_loc
        matches.append({
            "bbox": (ox + lx, oy + ly, ox + lx + tw, oy + ly + th),
            "conf": float(max_val),
        })
        y1 = max(0, ly - margin_y)
        y2 = min(result.shape[0], ly + th + margin_y)
        x1 = max(0, lx - margin_x)
        x2 = min(result.shape[1], lx + tw + margin_x)
        result[y1:y2, x1:x2] = -1.0
    return matches, best_score


def _preflight_guard(out: Path, class_names: list[str],
                     expected: set[str]) -> list[str]:
    """跑之前的破坏性检查：这次运行会不会把现有数据集里的东西弄丢。

    本工具是**全量重建**（截断写 train/val + 重建 dataset.yaml），而 dataset/ 现在是
    手工维护的（63 类方案 B + 手工追加的帧），所以它已经不能再跑了。这个检查把
    「静默毁数据」变成「明确报错」——不检查的话跑一次就是类表缩回 50 + 手工帧全丢。

    返回会丢失的东西（空列表 = 安全）。
    """
    import yaml

    problems: list[str] = []

    ds_yaml = out / "dataset.yaml"
    if ds_yaml.exists():
        old = {str(v) for v in
               yaml.safe_load(ds_yaml.read_text(encoding="utf-8"))["names"].values()}
        lost = sorted(old - set(class_names))
        if lost:
            problems.append(
                f"dataset.yaml 有 {len(lost)} 个类不在本次类表里，会被删掉："
                f"{', '.join(lost[:8])}{' ...' if len(lost) > 8 else ''}")

    for name in ("train.txt", "val.txt"):
        p = out / name
        if not p.exists():
            continue
        rows = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        # Windows 路径大小写不敏感，按小写比对（两边都是 .resolve() 的结果）
        have = {e.lower() for e in expected}
        gone = [r for r in rows if r.lower() not in have]
        if gone:
            problems.append(
                f"{name} 有 {len(gone)}/{len(rows)} 行不在本次输出范围内，会被截断丢掉"
                f"（例：{Path(gone[0]).name}）")

    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recordings", type=Path, default=DEFAULT_RECORDINGS)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--val-ratio", type=float, default=0.1)
    ap.add_argument("--limit", type=int, default=0, help="only first N frames (trial)")
    ap.add_argument("--exclude", default="",
                    help="comma-separated glob patterns of template ids to drop "
                         "from the YOLO class list (e.g. 'fill_*' for "
                         "account-bound name classes; avoids non-ASCII args)")
    ap.add_argument("--visualize", type=int, default=0, help="draw boxes on N random frames")
    ap.add_argument("--allow-dataset-rewrite", action="store_true",
                    help="确认要全量重建 dataset/（会截断 train/val 并重建 dataset.yaml）。"
                         "补图请用 tools/ingest_raw_imgs.py 增量入库，不要用这个")
    args = ap.parse_args()

    import fnmatch
    patterns = [s.strip() for s in args.exclude.split(",") if s.strip()]
    registry = TemplateRegistry.load(args.manifest)
    specs = [(tid, spec) for tid, spec in registry._t.items()
             if not any(fnmatch.fnmatchcase(tid, pat) for pat in patterns)]
    if patterns:
        excluded = sorted(set(registry._t) - {tid for tid, _ in specs})
        print(f"excluded {len(excluded)} classes: {excluded}")
    class_names = [tid for tid, _ in specs]
    print(f"loaded {len(specs)} templates, class ids 0..{len(specs) - 1}")

    templates: dict[str, np.ndarray] = {}
    for tid, spec in specs:
        img = cv2.imread(str(spec.file))
        if img is None:
            raise FileNotFoundError(f"cannot load template image: {spec.file}")
        templates[tid] = img

    frames = sorted(args.recordings.rglob("*.png"))
    if args.limit:
        frames = frames[:args.limit]
    print(f"found {len(frames)} frames under {args.recordings}")

    labels_dir = args.out / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    images_dir = args.out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    def flat_name(frame_path: Path) -> str:
        rel = frame_path.relative_to(args.recordings)
        return "__".join(rel.parts)

    expected = {str((images_dir / flat_name(p)).resolve()) for p in frames}
    problems = _preflight_guard(args.out, class_names, expected)
    if problems:
        print("\n!! 这次运行会破坏现有数据集：")
        for prob in problems:
            print(f"   - {prob}")
        if not args.allow_dataset_rewrite:
            print("\n已中止。dataset/ 现在是手工维护的（63 类方案 B + 手工追加帧），"
                  "补图请用 tools/ingest_raw_imgs.py 增量入库。\n"
                  "想试跑（--limit）请把 --out 指到临时目录，别指 dataset/。\n"
                  "确实要全量重建（现有内容会被覆盖）再加 --allow-dataset-rewrite。")
            raise SystemExit(2)
        print("\n--allow-dataset-rewrite 已指定，继续（现有内容会被覆盖）。\n")

    per_class_boxes = {name: 0 for name in class_names}
    per_class_pos_frames = {name: 0 for name in class_names}
    gray_zone = {name: 0 for name in class_names}   # best score in [thr-margin, thr)
    below_zone = {name: 0 for name in class_names}  # best score even lower
    empty_frames = 0
    box_total = 0

    for idx, frame_path in enumerate(frames):
        frame = cv2.imread(str(frame_path))
        if frame is None:
            print(f"  [skip unreadable] {frame_path}")
            continue
        fh, fw = frame.shape[:2]

        lines: list[str] = []
        for cid, (tid, spec) in enumerate(specs):
            tmpl = templates[tid]
            roi = None if spec.roi.is_full else (spec.roi.x1, spec.roi.y1, spec.roi.x2, spec.roi.y2)
            matches, best = multi_match(frame, tmpl, spec.threshold, roi)
            for m in matches:
                x1, y1, x2, y2 = m["bbox"]
                # clip to frame in case template touches ROI edge
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(fw, x2), min(fh, y2)
                cx, cy = (x1 + x2) / 2 / fw, (y1 + y2) / 2 / fh
                w, h = (x2 - x1) / fw, (y2 - y1) / fh
                lines.append(f"{cid} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
                per_class_boxes[tid] += 1
            if matches:
                per_class_pos_frames[tid] += 1
            elif best >= spec.threshold - GRAY_ZONE_MARGIN:
                gray_zone[tid] += 1
            else:
                below_zone[tid] += 1
        box_total += len(lines)
        if not lines:
            empty_frames += 1

        rel = flat_name(frame_path)
        out_path = labels_dir / Path(rel).with_suffix(".txt")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")

        # hardlink the frame into images/ (zero extra disk); fall back to copy
        link_path = images_dir / rel
        if not link_path.exists():
            try:
                os.link(frame_path, link_path)
            except OSError:
                shutil.copy2(frame_path, link_path)

        if (idx + 1) % 50 == 0 or idx + 1 == len(frames):
            print(f"  [{idx + 1}/{len(frames)}] frames done, {box_total} boxes so far")

    # image path lists (absolute: ultralytics resolves txt lines against
    # dataset.yaml's `path`, absolute avoids the ambiguity)
    image_paths = [str((images_dir / flat_name(p)).resolve()) for p in frames]
    rng = random.Random(42)
    rng.shuffle(image_paths)
    n_val = int(len(image_paths) * args.val_ratio)
    (args.out / "val.txt").write_text("\n".join(image_paths[:n_val]), encoding="utf-8")
    (args.out / "train.txt").write_text("\n".join(image_paths[n_val:]), encoding="utf-8")

    names = {i: n for i, n in enumerate(class_names)}
    import yaml
    (args.out / "dataset.yaml").write_text(yaml.safe_dump({
        "path": str(args.out.resolve()),
        "train": "train.txt",
        "val": "val.txt",
        "names": names,
    }, allow_unicode=True), encoding="utf-8")

    stats = {
        "frames": len(frames),
        "boxes": box_total,
        "empty_frames": empty_frames,
        "per_class": {
            name: {
                "boxes": per_class_boxes[name],
                "positive_frames": per_class_pos_frames[name],
                "gray_zone_frames": gray_zone[name],
                "no_signal_frames": below_zone[name],
            } for name in class_names
        },
    }
    (args.out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    print(f"\n=== summary ===")
    print(f"frames: {len(frames)}, boxes: {box_total}, empty frames: {empty_frames}")
    print(f"{'class':<24}{'boxes':>7}{'pos fr':>8}{'gray':>7}{'none':>7}")
    for name in class_names:
        print(f"{name:<24}{per_class_boxes[name]:>7}{per_class_pos_frames[name]:>8}"
              f"{gray_zone[name]:>7}{below_zone[name]:>7}")
    print(f"\nlabels + train.txt/val.txt + dataset.yaml + stats.json -> {args.out}")

    if args.visualize:
        vis_dir = ROOT
        for i, frame_path in enumerate(rng.sample(frames, min(args.visualize, len(frames)))):
            frame = cv2.imread(str(frame_path))
            fh, fw = frame.shape[:2]
            label_path = labels_dir / Path(flat_name(frame_path)).with_suffix(".txt")
            if label_path.exists():
                for line in label_path.read_text(encoding="utf-8").splitlines():
                    cid, cx, cy, w, h = line.split()
                    cid = int(cid)
                    cx, cy, w, h = float(cx) * fw, float(cy) * fh, float(w) * fw, float(h) * fh
                    x1, y1 = int(cx - w / 2), int(cy - h / 2)
                    cv2.rectangle(frame, (x1, y1), (x1 + int(w), y1 + int(h)), (0, 255, 0), 2)
                    cv2.putText(frame, class_names[cid], (x1, max(12, y1 - 4)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
            out_png = vis_dir / f"_yolo_check_{i}.png"
            cv2.imwrite(str(out_png), frame)
            print(f"  visualization -> {out_png}")


if __name__ == "__main__":
    main()
