# -*- coding: utf-8 -*-
"""给 `_ocr_level_text` 的预处理调参：在留白/放大两个维度上扫一遍。

背景：RapidOCR 的 DBNet 检测在文本贴住裁剪边界时会**整个失败**（返回空），
而不是降级成低置信度。实测同一张清晰裁剪图：

    无留白 -> []   白边 10px -> 等级   白边 40px -> 等级：   白边 60px -> 等级：8

而 `_ocr_level_text` 现在的 `pad_y` 只有框高的 10%（30px 的框 → 3px），垂直留白
几乎为零。它的注释说少外扩是**有意**的（防把滑块像素卷进来）——所以修法不是把
裁剪框撑大，而是在裁好的图上补一圈白边：既不引入邻居像素，又给足 DBNet 留白。

在 v8 的全部 zhaizi_level_text 检出框上比各方案「读出数字」的比例，取最优。

用法（仓库根目录）：
    .venv/Scripts/python.exe -X utf8 tools/tune_zhaizi_ocr.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

RUN = "gpu_1080_v8"
MAX_FRAMES = 40

# (标签, 白边 px, 放大倍数)
VARIANTS = [
    ("现状 pad 10%/15% 无白边 2x", 0, 2.0),
    ("白边 20px 无放大", 20, 1.0),
    ("白边 40px 无放大", 40, 1.0),
    ("白边 60px 无放大", 60, 1.0),
    ("白边 80px 无放大", 80, 1.0),
    ("白边 40px + 2x", 40, 2.0),
    ("白边 60px + 2x", 60, 2.0),
    ("白边 60px + 3x", 60, 3.0),
]


def prep(shot, x1, y1, x2, y2, border: int, scale: float):
    h, w = shot.shape[:2]
    pad_x, pad_y = int((x2 - x1) * 0.15), int((y2 - y1) * 0.1)
    crop = shot[max(0, y1 - pad_y):min(h, y2 + pad_y),
                max(0, x1 - pad_x):min(w, x2 + pad_x)]
    if crop.size == 0:
        return None
    if border:
        crop = cv2.copyMakeBorder(crop, border, border, border, border,
                                  cv2.BORDER_CONSTANT, value=(255, 255, 255))
    if scale != 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_CUBIC)
    return crop


def read_level(engine, crop) -> str:
    """与 tools/annotate_live.py:_ocr_level_text 后半段一致：取最右含数字文本块。"""
    digit_texts = [(bb.x1, t) for bb, t, _c in engine.detect_text(crop)
                   if re.search(r"\d", t)]
    if not digit_texts:
        return ""
    rightmost = max(digit_texts, key=lambda e: e[0])[1]
    m = re.search(r"\d+", rightmost)
    return m.group(0) if m else ""


def main() -> int:
    names = {int(k): str(v) for k, v in yaml.safe_load(
        (ROOT / "dataset/dataset.yaml").read_text(encoding="utf-8"))["names"].items()}
    zid = next(k for k, v in names.items() if v == "zhaizi_level_text")

    frames = []
    for lab in sorted((ROOT / "dataset/labels").glob("*.txt")):
        img = ROOT / "dataset/images" / f"{lab.stem}.png"
        if not img.exists():
            continue
        rows = [l.split() for l in lab.read_text(encoding="utf-8").splitlines() if l.strip()]
        if any(int(r[0]) == zid for r in rows):
            frames.append(img)
    frames = frames[:MAX_FRAMES]
    print(f"含 zhaizi_level_text 的帧：{len(frames)}，模型 {RUN}\n")

    from rok_assistant.core.recognizers.ocr_text import RapidOcrEngine
    from ultralytics import YOLO
    engine = RapidOcrEngine()
    model = YOLO(str(ROOT / "runs" / RUN / "weights" / "best.pt"))

    boxes = []          # (shot, x1,y1,x2,y2)
    for img in frames:
        shot = cv2.imread(str(img), cv2.IMREAD_COLOR)
        pred = model(shot, imgsz=640, verbose=False)[0]
        for b in pred.boxes:
            if int(b.cls[0]) == zid:
                boxes.append((shot, *[int(v) for v in b.xyxy[0].tolist()]))
    print(f"共 {len(boxes)} 个检出框\n")

    print(f"{'方案':<28}{'读出数字':>10}{'读数分布':>34}")
    print("-" * 74)
    for tag, border, scale in VARIANTS:
        hits = []
        for shot, x1, y1, x2, y2 in boxes:
            crop = prep(shot, x1, y1, x2, y2, border, scale)
            if crop is None:
                continue
            lv = read_level(engine, crop)
            if lv:
                hits.append(lv)
        dist = ", ".join(f"{v}x{hits.count(v)}" for v in sorted(set(hits), key=hits.count, reverse=True)[:5])
        print(f"{tag:<28}{len(hits):>4}/{len(boxes):<5}{dist:>34}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
