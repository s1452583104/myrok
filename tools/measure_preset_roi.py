# -*- coding: utf-8 -*-
"""导出 preset_1..6 的 ROI/阈值标定数据（重标定用）。

`tests/unit/core/test_preset_roi_anchor.py` 锚着四个数，全部来自这个脚本。
游戏改版换了面板位置或美术之后，改完 `templates/manifest.yaml` 就跑这个，
把输出的四个数回填进锚点测试和 manifest 里 preset_1 上方的注释——别只改一边。

判法刻意与 `TemplateMatch.recognize` 一致：把 ROI 裁出来再 `matchTemplate` +
`minMaxLoc` 取**唯一最优**匹配。这一点是这个类的关键——`multi_match`（标注侧）
会把 6 个槽全部报出来（实测 1799 命中 / 1406 越界），但运行时只认最优那一个，
而最优那个能不能落在正确槽位，就是「会不会点错预设」的全部问题。

输出四个数：
  1. 正确下限 —— 最优匹配落在正确槽位时的最低分（阈值不能高过它，否则漏检）
  2. 串位上限 —— 最优匹配落到别的槽位时的最高分（阈值必须高过它，否则点错槽）
  3. 误报上限 —— 该槽没有标注的帧上，窗内最优匹配的最高分
  4. 阈值扫描 —— 各阈值下的 正确/串位/误报 计数

用法（仓库根目录）：
    .venv/Scripts/python.exe tools/measure_preset_roi.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rok_assistant.core.template_registry import TemplateRegistry  # noqa: E402

# 判「落在正确槽位」的容差：图标 44px，标注框与匹配框都是同一套坐标
SLOT_TOLERANCE_PX = 12
# 槽间距实测 ~84px。真正的「串到邻槽」至少偏半个槽距，否则就是同一个槽，
# 偏那点只可能是标注框画歪了——两者必须分开，混在一起会让上限恒为 1.0，
# 这个工具就永远报「分离失败」，等于没用。
SLOT_PITCH_PX = 84
PRESETS = [f"preset_{i}" for i in range(1, 7)]


def main() -> int:
    reg = TemplateRegistry.load(ROOT / "templates" / "manifest.yaml")
    names = {int(k): str(v) for k, v in yaml.safe_load(
        (ROOT / "dataset/dataset.yaml").read_text(encoding="utf-8"))["names"].items()}
    inv = {v: k for k, v in names.items()}

    tmpls, rois = {}, {}
    for tid in PRESETS:
        spec = reg.get(tid)
        tmpls[tid] = cv2.imread(str(spec.file), cv2.IMREAD_COLOR)
        rois[tid] = (spec.roi.x1, spec.roi.y1, spec.roi.x2, spec.roi.y2)

    r0 = reg.get("preset_1")
    print(f"manifest 现值：preset_1..6 阈值 {r0.threshold}"
          f"  ROI [{r0.roi.x1},{r0.roi.y1},{r0.roi.x2},{r0.roi.y2}]")
    if len({rois[t] for t in PRESETS}) != 1:
        print("  !! 六槽 ROI 不一致 —— 窄窗切法挡不住面板上下行程（见锚点测试）")
    print()

    hits: list[tuple[str, float, int]] = []       # (模板, 分数, 偏离标注多少 px)
    no_lab: list[tuple[str, float]] = []          # 该槽无标注帧上的分数
    for lab in sorted((ROOT / "dataset/labels").glob("*.txt")):
        ip = ROOT / "dataset/images" / f"{lab.stem}.png"
        if not ip.exists() or Image.open(ip).size != (1920, 1080):
            continue
        shot = cv2.imread(str(ip), cv2.IMREAD_COLOR)
        if shot is None:
            continue
        rows = [l.split() for l in lab.read_text(encoding="utf-8").splitlines() if l.strip()]
        exp = {i: float(r[2]) * 1080 for r in rows for i in range(1, 7)
               if int(r[0]) == inv[f"preset_{i}"]}
        for i, tid in enumerate(PRESETS, start=1):
            x1, y1, x2, y2 = rois[tid]
            th, tw = tmpls[tid].shape[:2]
            res = cv2.matchTemplate(shot[y1:y2, x1:x2], tmpls[tid],
                                    cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            cy = y1 + loc[1] + th / 2
            if i in exp:
                hits.append((tid, mx, int(abs(cy - exp[i]))))
            else:
                no_lab.append((tid, mx))

    good = [s for _, s, off in hits if off <= SLOT_TOLERANCE_PX]
    near = [(t, s, off) for t, s, off in hits
            if SLOT_TOLERANCE_PX < off < SLOT_PITCH_PX // 2]
    cross = [(t, s, off) for t, s, off in hits if off >= SLOT_PITCH_PX // 2]
    print(f"该槽有标注的 (帧,模板) 对：{len(hits)}")
    print(f"  1. 正确下限 = {min(good):.4f}" if good else "  1. 正确下限 = 无样本")
    print(f"  2. 串位上限 = {max((s for _, s, _ in cross), default=0):.4f}"
          f"（{len(cross)} 例真串位，偏移 >= {SLOT_PITCH_PX // 2}px）")
    print(f"  3. 误报上限 = {max((s for _, s in no_lab), default=0):.4f}"
          f"（{len(no_lab)} 个无标注样本）")
    if near:
        print(f"\n  !! {len(near)} 例「最优匹配在正确槽位附近但偏离标注 "
              f"{SLOT_TOLERANCE_PX}~{SLOT_PITCH_PX // 2}px 且分数很高」"
              f"—— 这不是串位，是标注框画歪了，请人工核对：")
        for t, s, off in sorted(near, key=lambda r: -r[1])[:8]:
            print(f"       {t} 分数 {s:.4f} 偏离 {off}px")

    # 下界要同时压过「串到邻槽」和「无标注帧上的误报」——后者往往才是真正的
    # 约束（实测：串位上限 0.51，误报上限 0.96）。只取串位上限会给出一个
    # 低到放行误报的阈值。
    lo = max(max((s for _, s, _ in cross), default=0.0),
             max((s for _, s in no_lab), default=0.0))
    hi = min(good) if good else 1.0
    if lo < hi:
        print(f"\n  => 安全窗口 ({lo:.4f}, {hi:.4f})，窗口内取值在本数据集上"
              f"行为一致（见下表）")
        if lo < r0.threshold < hi:
            print(f"     manifest 现值 {r0.threshold} 在窗口内 [OK]")
        else:
            print(f"     !! manifest 现值 {r0.threshold} 不在窗口内，必须改")
    else:
        print(f"\n  => 分离失败（下界 {lo:.4f} >= 正确下限 {hi:.4f}）："
              f"光靠阈值卡不住，得换模板/换判据")

    print("\n  4. 阈值扫描（正确 / 低于阈值 / 无标注帧误报）：")
    print("     注意「低于阈值」含两类：真的没匹配上，以及标注在 ROI 外"
          "（如编队界面的预设条 cx≈1486，运行时根本不在那儿找）。")
    for thr in (0.90, 0.93, 0.95, 0.96, 0.97, 0.98, 0.99, 0.995):
        g = sum(1 for _, s, off in hits
                if s >= thr and off <= SLOT_TOLERANCE_PX)
        m = sum(1 for _, s, _ in hits if s < thr)
        f = sum(1 for _, s in no_lab if s >= thr)
        mark = "  <- manifest 现值" if abs(thr - r0.threshold) < 1e-9 else ""
        print(f"     thr={thr:.3f}  正确 {g:4d}  低于阈值 {m:3d}  误报 {f:4d}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
