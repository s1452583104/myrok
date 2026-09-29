# -*- coding: utf-8 -*-
"""端到端验证「寨子等级能不能读出来」：检测框 -> 裁剪 -> OCR -> 数字。

这是用户最初报的症状（"OCR 识别寨子等级识别不出"）。检测框只是 OCR 的输入，
AP 涨了不等于数字读得出来——所以直接跑完整链路，对比两个 run 各帧的结果。

OCR 裁剪逻辑**直接 import** `tools/annotate_live.py:_ocr_level_text`，不复制。
早先这里抄了一份，理由是「口径必须和实机预览完全一致」——但那恰恰是复制的坏处：
改了实机那份，这份就悄悄测的是旧逻辑，验证变成假的。annotate_live 只有 import、
没有模块级副作用，可以安全导入。

用法（仓库根目录）：
    .venv/Scripts/python.exe -X utf8 tools/check_zhaizi_level.py gpu_1080_v7 gpu_1080_v8
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from annotate_live import _ocr_level_text  # noqa: E402

MAX_FRAMES = 24


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    runs = sys.argv[1:]

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
    print(f"含 zhaizi_level_text 标注的帧：{len(frames)}（取前 {MAX_FRAMES}）\n")

    # OCR 引擎由 annotate_live 模块内的 _ocr_engine 懒加载，这里不再自己建一个
    from ultralytics import YOLO
    results = {}
    for run in runs:
        model = YOLO(str(ROOT / "runs" / run / "weights" / "best.pt"))
        rows = []
        for img in frames:
            shot = cv2.imread(str(img), cv2.IMREAD_COLOR)
            pred = model(shot, imgsz=640, verbose=False)[0]
            levels, nbox = [], 0
            for box in pred.boxes:
                if int(box.cls[0]) != zid:
                    continue
                nbox += 1
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                lv = _ocr_level_text(shot, x1, y1, x2, y2)
                levels.append(lv or "-")
            rows.append((img.stem, nbox, levels))
        results[run] = rows

    for i, img in enumerate(frames):
        print(f"{img.stem}")
        for run in runs:
            stem, nbox, levels = results[run][i]
            got = sum(1 for l in levels if l != "-")
            mark = "OK " if got else "   "
            print(f"  {mark}{run[-7:]:>9}  框 {nbox}  读出数字 {got}/{nbox}  "
                  f"{levels if levels else '(无框)'}")
        print()

    print("=== 汇总 ===")
    for run in runs:
        rows = results[run]
        frames_hit = sum(1 for _s, _n, lv in rows if any(x != "-" for x in lv))
        boxes = sum(n for _s, n, _lv in rows)
        read = sum(1 for _s, _n, lv in rows for x in lv if x != "-")
        print(f"  {run}: 读出数字的帧 {frames_hit}/{len(rows)}"
              f"   框 {boxes} 个，其中读出数字 {read} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
