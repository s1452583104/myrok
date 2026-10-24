# tools/crop_gem_templates.py
"""按显式 ROI 批量裁宝石模式模板（非交互，annotator 用）。

为什么不用 tools/crop_template.py：那个要人拖框，批量裁 6 张要开 6 次窗口，
而且裁出来的框没法进代码评审。这里把坐标写死在表里——改坐标就是改代码。

坐标来源：2026-10-17 用 `_probe_gem_locate.py` 定位候选 + 逐张拼联络表人眼复核
（见 `recordings/gem_probe/context_sheet*.png` 与
`docs/superpowers/specs/2026-10-17-宝石模式-design.md` §3.1.1）。
**不是** Stage 0 的估计值——Stage 0 未跑，表里每一行都是实测后校正过的。

用法：
    .venv/Scripts/python.exe -X utf8 tools/crop_gem_templates.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "imgs" / "gem"
OUT = ROOT / "templates"

# (模板 id, 源帧, 框中心 x, 框中心 y, 宽, 高)
# **坐标 2026-10-17 实测校正**（见 spec §3.1.1）。括号里是相对最初估计值的改动。
CROPS = [
    # 白色六边形晶体本体，**不含**下方的等级角标（角标数字随矿等级变）。
    # 行剖面实测：晶体 bbox (992,436)-(1025,466)，角标从 y=466 起（白色圆角框 +
    # 深色数字「3」，数字从 y=470 起）。所以下边界停在 466，把角标整块切掉。
    # 估计 (1010,450) 44x44 的下边界 472 会带进 6 行角标（含数字），故改 44x34。
    ("gem_icon",          "MuMu-20261017-142653-907.png", 1010, 449,  44,  34),
    # 放大后的红色晶簇。取晶簇本体（红掩码 bbox (838,406)-(1014,580)），
    # 下边界停在等级角标（y≈566）之上。估计 120x120 全红无特征 → 改为含晶簇轮廓。
    ("gem_mine_zoom",     "MuMu-20261017-142730-244.png",  926, 480, 190, 168),
    # 环形菜单已弹出的锚点：山按钮 (213,664)-(316,763) + 黄色高亮的树/资源按钮
    # (366,769)-(482,889) + 下方塔按钮 (354,980)-(457,1078)。
    # 估计 (175,810) 380x380 会越界（x1=-15）→ 实测中心 (352,864)。
    # 注意：左边界刻意避开城堡按钮（map_btn，一直存在），否则锚点会被稀释。
    ("view_radial_menu",  "MuMu-20261017-142653-907.png",  352, 864, 296, 428),
    # 环形菜单里的「资源」按钮：黄色发光圆盘本体 (366,769)-(482,889)。
    # 估计 90x90 只盖到盘心（无盘缘）→ 放大到 128x128 盖住整个圆盘。
    ("view_btn_resource", "MuMu-20261017-142653-907.png",  424, 829, 128, 128),
    # 采集框整块面板：白区 bbox (741,275)-(1437,791)。
    # 估计 (960,560) 620x300 偏左且丢了顶部 → 改为面板整块。
    ("collect_dialog",    "MuMu-20261017-142743-132.png", 1089, 533, 700, 520),
    # 蓝色「采集」按钮整颗（蓝掩码 bbox (932,669)-(1244,783)，含白色「采集」二字）。
    # 估计 240x80 落在按钮内部纯蓝区（无任何特征，会误配任何蓝块）→ 改为整颗按钮。
    ("collect_btn",       "MuMu-20261017-142743-132.png", 1088, 726, 320, 124),
    # 第 7 张 back_from_detail **故意不裁**：brief 的估计坐标 142720(1850,530) 60x60
    # 实测指着的是一个**地图资源点标记**（蓝盘 + 白色镐头图标 + 下方「7」等级角标），
    # 不是返回箭头——同一图标在 142653 的 (224,904) 也出现（位置随相机移动，且两处都
    # 跟着等级角标），全 11 帧里 142707/142725/142653/142658 的右侧带都没有它。
    # 这 11 帧里没有任何返回/关闭箭头（采集框只有星标+分享两个盾形按钮；142730 的
    # 蓝色「<」是城内任务面板的收起键，142720 里没有；创建部队表单标题栏也没有）。
    # 「错的模板比没有模板更糟」——留给控制器裁定，不猜。
    # 下面这行是 **brief 的原始估计值**（未采用）：万一 Stage 0 之后要重新启用，
    # 请连坐标一起改，别直接放开——它指着的是地图标记，不是返回箭头。
    # ("back_from_detail", "MuMu-20261017-142720-208.png", 1850, 530,  60,  60),
]


def imread_unicode(p: Path) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"读不了 {p}")
    return img


def main() -> int:
    missing = [c[1] for c in CROPS if not (SRC / c[1]).is_file()]
    if missing:
        print(f"缺源帧：{sorted(set(missing))}", file=sys.stderr)
        return 2

    # 先全部校验、再落盘：Stage 5 的活就是照着新帧改坐标，改出一个越界框时
    # 绝不能留下半套「看起来完整」的模板。任何一行越界 → 一个文件都不写。
    frames: dict[str, np.ndarray] = {}
    plan: list[tuple[str, str, tuple[int, int, int, int], np.ndarray]] = []
    bad: list[str] = []
    for tid, src, cx, cy, w, h in CROPS:
        img = frames.get(src)
        if img is None:
            img = frames[src] = imread_unicode(SRC / src)
        x1, y1 = int(cx - w / 2), int(cy - h / 2)
        x2, y2 = x1 + w, y1 + h
        if x1 < 0 or y1 < 0 or x2 > img.shape[1] or y2 > img.shape[0]:
            print(f"[skip] {tid}: 框越界 ({x1},{y1},{x2},{y2})，"
                  f"源帧只有 {img.shape[1]}x{img.shape[0]}", file=sys.stderr)
            bad.append(tid)
            continue
        plan.append((tid, src, (x1, y1, x2, y2), img[y1:y2, x1:x2]))
    if bad:
        print(f"越界 {len(bad)} 个：{bad}；一个文件都没写", file=sys.stderr)
        return 2

    OUT.mkdir(exist_ok=True)
    for tid, src, (x1, y1, x2, y2), patch in plan:
        ok, buf = cv2.imencode(".png", patch)
        if not ok:
            raise SystemExit(f"编码失败：{tid}")
        (OUT / f"{tid}.png").write_bytes(buf.tobytes())
        print(f"[crop] {tid:18s} <- {src} ({x1},{y1},{x2},{y2}) {patch.shape}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
