# -*- coding: utf-8 -*-
"""逐张翻看数据集标注：把 YOLO 标注框画在图上，键盘一张张切换。

**为什么需要它。** 报告里「某帧 0 框」只是一个名字，看不出这张图里到底有没有目标
——那正是要判的东西（0 框帧是假负样本还是合法背景）。必须看到画面才知道。

画框复用 `tools/annotate_live.py` 的配色（`_color`，每类一个稳定颜色）与中文字体
（`_font`），类名走 `tools/class_names_zh.py` 的中文对照；字体缺失时退回英文名。

**按键**（图像窗口获得焦点时）：
    SPACE / n / f     下一张
    b                 上一张
    k / j             后 / 前 10 张
    g                 跳到第 N 张（在**控制台**输入序号）
    s                 把当前带框图存到 --out 目录（原图分辨率）
    q / ESC           退出

小图（裁剪帧，如 270x210）会自动放大到 `--width` 宽，否则框和字看不清。

用法（仓库根目录）：
    .venv/Scripts/python.exe -X utf8 tools/view_dataset.py                  # 全部 777 帧
    .venv/Scripts/python.exe -X utf8 tools/view_dataset.py --split val      # 只看 val
    .venv/Scripts/python.exe -X utf8 tools/view_dataset.py --empty          # 只看 0 框帧
    .venv/Scripts/python.exe -X utf8 tools/view_dataset.py --filter scenes___z_
    .venv/Scripts/python.exe -X utf8 tools/view_dataset.py --out logs/view  # s 键存这里
    .venv/Scripts/python.exe -X utf8 tools/view_dataset.py --no-window \\
        --out logs/view --empty            # 不弹窗，直接把 0 框帧全导成 PNG
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from annotate_live import _color, _font  # noqa: E402
from class_names_zh import zh  # noqa: E402
from ingest_raw_imgs import _read_list  # noqa: E402

WINDOW = "dataset viewer"
BAR_H = 30


def _read_rows(label_path: Path) -> list[tuple]:
    """读 YOLO 标签（归一化 cx cy w h）。标签文件缺失 = 0 框帧，返回空表。"""
    if not label_path.exists():
        return []
    out = []
    for ln in label_path.read_text(encoding="utf-8").splitlines():
        p = ln.split()
        if len(p) == 5:
            out.append((int(p[0]), *(float(v) for v in p[1:])))
    return out


def _dets(rows, names, w, h) -> list[dict]:
    """归一化 → 像素框，做成 annotate_live 那套 det 字典。"""
    dets = []
    for cid, cx, cy, bw, bh in rows:
        x1 = int(round((cx - bw / 2) * w))
        y1 = int(round((cy - bh / 2) * h))
        x2 = int(round((cx + bw / 2) * w))
        y2 = int(round((cy + bh / 2) * h))
        dets.append({"cid": cid, "name": names.get(cid, str(cid)),
                     "xyxy": (x1, y1, x2, y2)})
    return dets


def _draw(img: np.ndarray, dets: list[dict], scale: float) -> np.ndarray:
    """按 scale 缩放后画框。标签用中文名，无中文字体时退回英文名。"""
    if scale != 1.0:
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=interp)
        dets = [{**d, "xyxy": tuple(int(round(v * scale)) for v in d["xyxy"])}
                for d in dets]
    out = img.copy()
    font = _font(max(14, int(18 * min(scale, 2.0))))
    if font is None:
        for d in dets:
            x1, y1, x2, y2 = d["xyxy"]
            cv2.rectangle(out, (x1, y1), (x2, y2), _color(d["cid"]), 2)
            cv2.putText(out, d["name"], (x1 + 2, max(16, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, _color(d["cid"]), 1,
                        cv2.LINE_AA)
        return out
    from PIL import Image, ImageDraw
    pil = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    for d in dets:
        x1, y1, x2, y2 = d["xyxy"]
        color = _color(d["cid"])[::-1]          # BGR -> RGB
        text = zh(d["name"])
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ty = y1 - th - 8 if y1 - th - 8 > 0 else y2 + 4
        draw.rectangle([x1, ty - 4, x1 + tw + 6, ty + th + 4], fill=color)
        draw.text((x1 + 3, ty), text, font=font, fill=(0, 0, 0))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def _banner(img: np.ndarray, text: str) -> np.ndarray:
    """顶部黑条写状态。刻意只用 ASCII——中文字体在这条路径上不做保证。"""
    cv2.rectangle(img, (0, 0), (img.shape[1], BAR_H), (0, 0, 0), -1)
    cv2.putText(img, text, (10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 1, cv2.LINE_AA)
    return img


def _collect(dataset: Path, split: str, substr: str, only_empty: bool):
    """返回 [(stem, split, size, rows, image_path)]，按帧名排序。"""
    from PIL import Image

    images_dir = dataset / "images"
    train = {Path(p).stem.lower() for p in _read_list(dataset / "train.txt")}
    val = {Path(p).stem.lower() for p in _read_list(dataset / "val.txt")}
    names = {int(k): str(v) for k, v in yaml.safe_load(
        (dataset / "dataset.yaml").read_text(encoding="utf-8"))["names"].items()}

    frames = []
    for img in sorted(images_dir.glob("*.png")):
        stem = img.stem
        where = ("train" if stem.lower() in train
                 else "val" if stem.lower() in val else "none")
        if split != "all" and where != split:
            continue
        if substr and substr not in stem:
            continue
        rows = _read_rows(dataset / "labels" / f"{stem}.txt")
        if only_empty and rows:
            continue
        with Image.open(img) as im:
            size = im.size
        frames.append((stem, where, size, rows, img))
    return frames, names


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    ap.add_argument("--split", choices=("all", "train", "val"), default="all")
    ap.add_argument("--filter", default="", help="帧名子串过滤")
    ap.add_argument("--empty", action="store_true", help="只看 0 框帧")
    ap.add_argument("--width", type=int, default=1280, help="显示宽度（默认 1280）")
    ap.add_argument("--max-scale", type=float, default=4.0,
                    help="小图最大放大倍数（默认 4）")
    ap.add_argument("--out", type=Path, default=None,
                    help="s 键 / --no-window 的导出目录")
    ap.add_argument("--no-window", action="store_true",
                    help="不弹窗，直接把全部帧导出到 --out")
    args = ap.parse_args()

    if args.no_window and args.out is None:
        print("--no-window 需要同时给 --out <目录>")
        return 2

    frames, names = _collect(args.dataset, args.split, args.filter, args.empty)
    if not frames:
        print("没有匹配的帧（检查 --split / --filter / --empty）。")
        return 0

    n_empty = sum(1 for f in frames if not f[3])
    print(f"共 {len(frames)} 帧" + (f"，其中 0 框帧 {n_empty} 帧" if n_empty else ""))

    def render(i: int) -> np.ndarray:
        stem, where, (w, h), rows, img_path = frames[i]
        img = cv2.imread(str(img_path))
        if img is None:
            img = np.zeros((h, w, 3), dtype=np.uint8)
        scale = min(args.width / w, args.max_scale)
        out = _draw(img, _dets(rows, names, w, h), scale)
        classes = ", ".join(sorted({names.get(r[0], str(r[0])) for r in rows}))
        flag = "  <<< 0 BOX" if not rows else f"  [{classes}]"
        return _banner(out, f"[{i + 1}/{len(frames)}] {stem}  {where} "
                            f"{w}x{h}  boxes={len(rows)}{flag}")

    if args.no_window:
        args.out.mkdir(parents=True, exist_ok=True)
        for i in range(len(frames)):
            cv2.imwrite(str(args.out / f"{frames[i][0]}.png"), render(i))
        print(f"已导出 {len(frames)} 张到 {args.out}/")
        return 0

    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
    print("按键：SPACE/n 下一张 · b 上一张 · j/k ±10 · g 跳转 · "
          "s 存图 · q/ESC 退出")

    i = 0
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    while 0 <= i < len(frames):
        disp = render(i)
        cv2.imshow(WINDOW, disp)
        cv2.resizeWindow(WINDOW, disp.shape[1], disp.shape[0])
        stem, where, (w, h), rows, _ = frames[i]
        print(f"  [{i + 1}/{len(frames)}] {stem}  {where}  {w}x{h}  "
              f"boxes={len(rows)}"
              + ("" if rows else "   <<< 0 框帧"))
        key = cv2.waitKey(0) & 0xFF
        if key in (ord("q"), 27):                       # q / ESC
            break
        if key in (32, ord("n"), ord("f")):             # SPACE / n
            i += 1
        elif key == ord("b"):
            i -= 1
        elif key == ord("j"):
            i += 10
        elif key == ord("k"):
            i -= 10
        elif key == ord("s"):
            if args.out is None:
                print("    未指定 --out，本次不存。")
            else:
                dest = args.out / f"{stem}.png"
                cv2.imwrite(str(dest), render(i))
                print(f"    已存 {dest}")
        elif key == ord("g"):
            try:
                n = int(input(f"    跳到第几张 (1-{len(frames)})：").strip())
                i = max(0, min(len(frames) - 1, n - 1))
            except ValueError:
                print("    序号无效，忽略。")
        i = max(0, min(len(frames) - 1, i))
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
