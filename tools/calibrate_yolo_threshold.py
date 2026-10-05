# -*- coding: utf-8 -*-
"""YOLO 腿阈值定标：测每个 YOLO 类在**生产 ROI 过滤**下的 conf 分布。

什么时候跑：换 `app.yolo_model` 之后。`DEFAULT_YOLO_THRESHOLD`
（src/rok_assistant/core/template_registry.py）是**跟着模型走**的常量，
换权重必须重标一次，否则 YOLO 腿要么抢掉模板的正确结果、要么整条失效。

判据：对每个 id，把 val 帧分成两类——
  * present：该帧 GT 里有这个类 -> 取该帧内 YOLO 的最大 conf（真阳性侧）
  * absent ：该帧 GT 无此类 **且模板也没命中** -> 取最大 conf（假阳性地板）
阈值要落在 max(absent) 和 min(present) 之间。

**标签噪声修正**：不能把「GT 无此类」一律当 absent。实测 queue_panel 场景帧上
search_icon / alliance_btn 明明在画面里（模板给 1.000），只是标注漏标了常驻
HUD——首版没修正时把这种帧算成假阳性，把地板从 0.000 抬到 0.72/0.48，会得出
「YOLO 不可用」的错误结论。故用现役模板判据做仲裁，漏标帧单独计数。

用法: .venv/Scripts/python.exe -X utf8 tools/calibrate_yolo_threshold.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rok_assistant.core.recognizers.yolo_detect import SharedYoloDetector  # noqa: E402
from rok_assistant.core.template_registry import TemplateRegistry  # noqa: E402
from rok_assistant.infra.config import load_config  # noqa: E402

W, H = 1920, 1080


def load_gt(label: Path, w: int, h: int):
    out = []
    if not label.exists():
        return out
    for line in label.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) < 5:
            continue
        c = int(p[0])
        cx, cy, bw, bh = (float(v) for v in p[1:5])
        out.append((c, (cx - bw / 2) * w, (cy - bh / 2) * h,
                    (cx + bw / 2) * w, (cy + bh / 2) * h))
    return out


def main() -> int:
    cfg = load_config(ROOT / "config.yaml")
    model = Path(cfg.app.yolo_model)
    if not model.is_absolute():
        model = ROOT / model
    reg = TemplateRegistry.load(ROOT / "templates" / "manifest.yaml")
    shared = SharedYoloDetector(model)
    name_to_id = {v: k for k, v in shared.names.items()}
    tmpl = reg.build_recognizers()            # 纯模板（不挂 YOLO）作标签仲裁

    ids = []
    for tid in reg._t:                        # noqa: SLF001
        spec = reg.get(tid)
        if spec.type != "template_match" or tid.startswith("fill_"):
            continue
        if tid in name_to_id:
            ids.append(tid)

    val_list = ROOT / "logs" / "_v10_val.txt"
    imgs = [Path(x.strip()) for x in
            val_list.read_text(encoding="utf-8").splitlines() if x.strip()]

    present: dict[str, list[float]] = {t: [] for t in ids}
    absent: dict[str, list[float]] = {t: [] for t in ids}
    noise: dict[str, int] = {t: 0 for t in ids}
    skipped = frames = 0

    for img_path in imgs:
        img = cv2.imread(str(img_path))
        if img is None:
            skipped += 1
            continue
        h, w = img.shape[:2]
        if (w, h) != (W, H):                  # 非 1080p 的裁剪帧：ROI 不适用
            skipped += 1
            continue
        frames += 1
        gt = load_gt(img_path.parent.parent / "labels" / (img_path.stem + ".txt"), w, h)
        gt_classes = {g[0] for g in gt}

        result = shared.detect(img)[0]
        boxes = getattr(result, "boxes", None)
        rows = []
        if boxes is not None:
            for box in boxes:
                xyxy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy[0], "cpu") \
                    else np.array(box.xyxy[0])
                x1, y1, x2, y2 = (float(v) for v in xyxy[:4])
                rows.append((int(box.cls[0]), float(box.conf[0]),
                             (x1 + x2) / 2, (y1 + y2) / 2))

        for tid in ids:
            cid = name_to_id[tid]
            roi = reg.get(tid).roi
            best = 0.0
            for cls, conf, cx, cy in rows:
                if cls != cid:
                    continue
                if not roi.is_full and not (roi.x1 <= cx < roi.x2
                                            and roi.y1 <= cy < roi.y2):
                    continue
                best = max(best, conf)
            if cid in gt_classes:
                present[tid].append(best)
            else:
                if tmpl[tid].recognize(img).matched:   # 模板说在 -> 标注漏标
                    noise[tid] += 1
                else:
                    absent[tid].append(best)

    print(f"val 帧: 用 {frames} / 跳过 {skipped}（非 1080p 或无文件）")
    print(f"测的 id: {len(ids)}   （absent 已剔除模板命中帧）\n")
    hdr = (f"{'id':<20}{'阈值':>6}{'n正':>5}{'最小正':>8}{'中位正':>8}"
           f"{'假阳地板':>10}{'漏标':>6}{'建议':>7}")
    print(hdr)
    print("-" * len(hdr))

    miss: list[str] = []      # YOLO 有漏检（最小正=0）—— 无害，模板兜
    overlap: list[str] = []   # 真有重叠 —— 阈值救不了
    for tid in sorted(ids, key=lambda t: -len(present[t])):
        p = sorted(present[tid])
        a = sorted(absent[tid])
        cur = reg.get(tid).threshold
        if not p:
            print(f"{tid:<20}{cur:>6.2f}{0:>5}{'—':>8}{'—':>8}"
                  f"{(max(a) if a else 0.0):>10.3f}{noise[tid]:>6}{'?':>7}  val 无正样本")
            continue
        lo, hi = p[0], (max(a) if a else 0.0)
        if lo <= 0.0:
            sug, tag = "漏检", miss
        elif hi < lo:
            sug, tag = f"{(lo + hi) / 2:.3f}", None
        else:
            sug, tag = "无间隙", overlap
        if tag is not None:
            tag.append(tid)
        print(f"{tid:<20}{cur:>6.2f}{len(p):>5}{lo:>8.3f}{p[len(p) // 2]:>8.3f}"
              f"{hi:>10.3f}{noise[tid]:>6}{sug:>7}")
    if overlap:
        print(f"\n真有重叠（阈值救不了，{len(overlap)}）：{', '.join(overlap)}")
    if miss:
        print(f"YOLO 漏检（无害，模板腿会兜，{len(miss)}）：{', '.join(miss)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
