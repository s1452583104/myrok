# -*- coding: utf-8 -*-
"""同一 val 集上逐类对比两个 run 的 AP50。

**为什么必须现算，而不是读各自的 results.csv**：v7 训练时用的 val 集和现在的
不是同一套——09-24 做过 `prune_labels.py`（摘 24 条越界标注、撤 8 帧）和
`preset_*` ROI 重定，val 的构成变了。读各自 results.csv 里记的 mAP50，等于拿
两把不同的尺子量两个模型，涨跌里混着尺子的变化。

这个脚本把两个权重都放到**当前** `dataset/val.txt` 上重跑一遍 val，才可比。

用法（仓库根目录）：
    .venv/Scripts/python.exe -X utf8 tools/compare_runs.py gpu_1080_v7 gpu_1080_v8
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 这几个类是这轮补图/改标注的目标，单独拉出来看
FOCUS = [
    "zhaizi_level_text", "queue_fight_icon", "queue_battle_icon",
    "sort_selector", "warning_panel", "preset_1", "preset_2", "preset_3",
    "preset_4", "preset_5", "preset_6", "join_btn", "search_icon",
]


def eval_run(run: str, data: Path, imgsz: int = 640) -> tuple[dict[str, float], float, int]:
    from ultralytics import YOLO

    w = ROOT / "runs" / run / "weights" / "best.pt"
    if not w.exists():
        raise SystemExit(f"找不到权重：{w}")

    out = ROOT / "runs" / "_cmp"
    m = YOLO(str(w))
    r = m.val(data=str(data), imgsz=imgsz, plots=False, verbose=False,
              project=str(out), name=run, exist_ok=True)
    ap = {int(c): float(v) for c, v in zip(r.box.ap_class_index, r.box.ap50)}
    return ap, float(r.box.map50), float(r.box.map)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    runs = sys.argv[1:]

    data = ROOT / "dataset" / "dataset.yaml"
    names = {int(k): str(v) for k, v in
             yaml.safe_load(data.read_text(encoding="utf-8"))["names"].items()}
    n_val = len([l for l in (ROOT / "dataset/val.txt").read_text(
        encoding="utf-8").splitlines() if l.strip()])
    print(f"val 集：{n_val} 帧（dataset/val.txt）\n")

    got = {}
    for run in runs:
        ap, map50, map5095 = eval_run(run, data)
        got[run] = ap
        print(f"{run}: mAP50 {map50:.4f}  mAP50-95 {map5095:.4f}"
              f"  （覆盖 {len(ap)}/{len(names)} 类）")

    print("\n=== 重点类 ===")
    hdr = f"{'类':<22}" + "".join(f"{r[-7:]:>11}" for r in runs) + f"{'Δ':>10}"
    print(hdr)
    print("-" * len(hdr))
    for nm in FOCUS:
        cid = next((k for k, v in names.items() if v == nm), None)
        if cid is None:
            continue
        cells = "".join(f"{got[r].get(cid, float('nan')):>11.3f}" for r in runs)
        a, b = (got[runs[0]].get(cid, 0.0), got[runs[-1]].get(cid, 0.0))
        flag = "  ↑" if b > a + 0.02 else ("  ↓" if b < a - 0.02 else "   ~")
        print(f"{nm:<22}{cells}{b - a:>+10.3f}{flag}")

    print("\n=== 全类变化最大的（按 Δ 排序）===")
    deltas = []
    for cid, nm in names.items():
        if cid not in got[runs[0]] and cid not in got[runs[-1]]:
            continue
        a, b = got[runs[0]].get(cid, 0.0), got[runs[-1]].get(cid, 0.0)
        deltas.append((b - a, nm, a, b, cid))
    deltas.sort(reverse=True)
    for d, nm, a, b, _ in deltas[:8]:
        print(f"  {nm:<24}{a:>7.3f} -> {b:>7.3f}  {d:>+7.3f}  ↑")
    print("  ...")
    for d, nm, a, b, _ in deltas[-8:]:
        print(f"  {nm:<24}{a:>7.3f} -> {b:>7.3f}  {d:>+7.3f}  ↓")

    print("\n=== 退到 0 的类（v7 有、v8 没了）===")
    lost = [nm for d, nm, a, b, _ in deltas if a > 0.05 and b < 0.02]
    print("  " + (", ".join(lost) if lost else "无"))

    print("\n=== 仍是 0 的类（两个 run 都测不出）===")
    zero = [nm for d, nm, a, b, _ in deltas if a < 0.02 and b < 0.02]
    print(f"  {len(zero)} 个：" + ", ".join(zero))

    shutil.rmtree(ROOT / "runs" / "_cmp", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
