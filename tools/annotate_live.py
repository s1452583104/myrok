# -*- coding: utf-8 -*-
"""Live annotation test — capture the emulator screen and overlay YOLO detections.

用途：实机验证训练产物（如 runs/gpu_1080_v7/weights/best.pt）。每拍一帧画面，
跑一遍 YOLO，把所有检出框（中文类名+置信度）画在画面上弹窗显示，同时打印到
控制台（中文名对照见 tools/class_names_zh.py）。寨子搜索页面检出
zhaizi_level_text 时自动 OCR 框内数字，画面标 `→ L10`，控制台单独打印识别结果。

用法（仓库根目录）：
    python tools/annotate_live.py                      # 默认 mumu0 + config 权重
    python tools/annotate_live.py --instance 1         # 指定模拟器实例
    python tools/annotate_live.py --conf 0.35 --save   # 降阈值 + 存标注帧到 logs/annotate/
    python tools/annotate_live.py --once               # 只跑一帧（无窗口，存文件）

窗口内按键：s = 保存当前标注帧，q/Esc = 退出。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from class_names_zh import zh  # noqa: E402
from rok_assistant.core.handle_source import create_handle_source  # noqa: E402
from rok_assistant.infra.config import load_config  # noqa: E402


def _color(cid: int) -> tuple:
    """每个类 id 一个稳定颜色（HSV 均匀取样）。"""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((cid * 0.618) % 1.0, 0.9, 1.0)
    return int(b * 255), int(g * 255), int(r * 255)  # BGR


_ocr_engine = None  # 懒加载：zhaizi_level_text 框内数字识别
_zh_font = None     # 懒加载：中文标注字体（cv2 Hershey 字体不支持中文）


def _font(size: int = 18):
    global _zh_font
    if _zh_font is None:
        from PIL import ImageFont
        for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
            path = Path("C:/Windows/Fonts") / name
            if path.exists():
                _zh_font = ImageFont.truetype(str(path), size)
                break
        if _zh_font is None:
            print("  (未找到中文字体，标注退回英文名)")
            _zh_font = False
    return _zh_font or None


def _ocr_level_text(img: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> str:
    """裁剪等级文本框（垂直少外扩，防把滑块像素卷进来），2x 放大后 OCR。

    取最靠右的含数字文本块（等级数字在「等级:」右侧的布局保证）；直接拼接
    全部文本会被低置信度的杂讯数字（如滑块边缘幻读）污染。
    """
    global _ocr_engine
    import re
    h, w = img.shape[:2]
    pad_x, pad_y = int((x2 - x1) * 0.15), int((y2 - y1) * 0.1)
    crop = img[max(0, y1 - pad_y):min(h, y2 + pad_y),
               max(0, x1 - pad_x):min(w, x2 + pad_x)]
    if crop.size == 0:
        return ""
    # 白边 60px：RapidOCR 的 DBNet 在文本贴住裁剪边界时会**整个失败**（返回空），
    # 不是降级成低置信度。实测同一张肉眼无歧义的清晰裁剪图（"等级: 8"）：
    #   无留白 -> []    白边 10px -> 等级    白边 40px -> 等级：    白边 60px -> 等级：8
    # 而下面的 pad_y 只有框高的 10%（30px 的框 -> 3px），垂直留白几乎为零——
    # 少外扩是有意的（防滑块像素卷入），所以不撑大裁剪框，改成裁完再补一圈白边：
    # 既不引入邻居像素，又给足 DBNet 留白。
    # 全库 42 个检出框实测：现状 17/42 -> 补白边 40/42，其中 39 个的数字来自含
    # 「等级」的文本块（另 3 个同属一帧误检，GT 本身就是画在提示文字上的宽框）。
    # 放大倍数在白边存在后不再影响结果（60px 与 60px+2x 同为 40/42）。
    crop = cv2.copyMakeBorder(crop, 60, 60, 60, 60, cv2.BORDER_CONSTANT,
                              value=(255, 255, 255))
    crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    if _ocr_engine is None:
        from rok_assistant.core.recognizers.ocr_text import RapidOcrEngine
        _ocr_engine = RapidOcrEngine()
    digit_texts = [(bb.x1, t) for bb, t, _c in _ocr_engine.detect_text(crop)
                   if re.search(r"\d", t)]
    if not digit_texts:
        return ""
    rightmost = max(digit_texts, key=lambda e: e[0])[1]
    m = re.search(r"\d+", rightmost)
    return m.group(0) if m else ""


# YOLO 学不动的「状态」类：**同一图标、同一位置，只有填充亮度不同**。数据集里
# `preset_N` 有 57~73 个实例、`selected_preset_N` 只有 3~17 个，同一像素位置差
# 13~20 倍，模型永远选多数类（v9 实测在标注为 selected_preset_3 的槽上给出
# preset_4@0.06，连类别都错）；`sort_selector` 全库仅 21 个实例。运行时与预览
# 一律改由像素判据接管（`recognizers/pixel_stat.py`），这里把 YOLO 的这几类输出
# **滤掉**——不滤的话真框和假框会同时画在屏幕上。
_PIXEL_TAKEOVER = ("selected_preset_", "sort_selector", "sort_opt_")


def _is_pixel_takeover(name: str) -> bool:
    return name.startswith(_PIXEL_TAKEOVER)


def _pixel_dets(img: np.ndarray, inv: dict,
                yolo_names: frozenset | set = frozenset()) -> list[dict]:
    """像素判据的检出（非 YOLO）。`inv` 是 name -> cid，cid 复用 YOLO 的类表，
    这样 `zh()` 的中文名与配色都自动生效。

    `conf` 字段放的是**实测统计量**（不是模型置信度）：选中槽放 `frac`、排序条放
    黄字占比、下拉三行放面板暗度比。日志里据此能看出判据离闸门有多远。

    **排序 UI 只在战争列表上找**（`yolo_names` 里有 `war_title` 才算）：黄字闸门
    `SORT_YELLOW_MIN` 是在 `02_warlist` 内部标定的（有条 0.0375~0.0623 / 无条
    0.0000），换到别的界面就不成立——实测创建部队弹窗上那块（罩着兵种行）黄字
    占比 0.03，照样过闸，会在兵种列表上画一个假的「排序条」。宁可漏画。

    **不声称哪一行排序项是激活的**：三行的填充/亮度一致、只有文字不同，没有判据
    （见 `pixel_stat` 模块尾注）。三行的名字只是**布局事实**（下拉第一行就是「最新
    发起」），不是对激活态的推断。
    """
    from rok_assistant.core.recognizers.pixel_stat import (
        PRESET_CLICKABLE_N,
        PRESET_HALF,
        SORT_DARK_MAX,
        SORT_DARK_ROI,
        SORT_OPT_H,
        SORT_OPT_X,
        SORT_OPT_YS,
        SORT_SELECTOR,
        SORT_SELECTOR_PX,
        mean_v,
        panel_verdict,
        slot_center,
        sort_bar_present,
        sort_dropdown_open,
        yellow_frac,
    )

    out: list[dict] = []
    verdict = panel_verdict(img)
    if verdict.slot is not None and verdict.slot <= PRESET_CLICKABLE_N:
        name = f"selected_preset_{verdict.slot}"
        cid = inv.get(name)
        if cid is not None:
            cx, cy = slot_center(verdict.slot)
            out.append({"cid": cid, "name": name, "conf": verdict.top_frac,
                        "xyxy": (int(cx) - PRESET_HALF, int(cy) - PRESET_HALF,
                                 int(cx) + PRESET_HALF, int(cy) + PRESET_HALF),
                        "level": "", "src": "pixel"})
    if "war_title" not in yolo_names or not sort_bar_present(img):
        return out
    cid = inv.get("sort_selector")
    if cid is not None:
        cx, cy, w, h = SORT_SELECTOR
        out.append({"cid": cid, "name": "sort_selector",
                    "conf": yellow_frac(img, *SORT_SELECTOR_PX),
                    "xyxy": (int((cx - w / 2) * 1920), int((cy - h / 2) * 1080),
                             int((cx + w / 2) * 1920), int((cy + h / 2) * 1080)),
                    "level": "", "src": "pixel"})
    if sort_dropdown_open(img):
        conf = 1.0 - mean_v(img, *SORT_DARK_ROI) / SORT_DARK_MAX
        x1, x2 = SORT_OPT_X
        for name, cy in SORT_OPT_YS.items():
            cid = inv.get(name)
            if cid is None:
                continue
            out.append({"cid": cid, "name": name, "conf": conf,
                        "xyxy": (x1, int(cy - SORT_OPT_H / 2),
                                 x2, int(cy + SORT_OPT_H / 2)),
                        "level": "", "src": "pixel"})
    return out


def _detections(img: np.ndarray, results, names: dict,
                threshold: float, inv: dict | None = None) -> list[dict]:
    """过滤后的检出列表；zhaizi_level_text 附带 OCR 等级（供绘制与日志共用）。

    末尾追加像素判据的检出（`_pixel_dets`），并滤掉 YOLO 在 `_PIXEL_TAKEOVER`
    那几类上的输出——同一个槽会被模型认错类别，不滤就是真框假框一起画。
    """
    dets: list[dict] = []
    r = results[0]
    if getattr(r, "boxes", None) is None:
        return dets
    for box in r.boxes:
        conf = float(box.conf[0])
        if conf < threshold:
            continue
        cid = int(box.cls[0])
        name = names.get(cid, str(cid))
        if _is_pixel_takeover(name):
            continue
        x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
        det = {"cid": cid, "name": name, "conf": conf,
               "xyxy": (x1, y1, x2, y2), "level": "", "src": "yolo"}
        if name == "zhaizi_level_text":
            det["level"] = _ocr_level_text(img, x1, y1, x2, y2)
        dets.append(det)
    if inv:
        dets.extend(_pixel_dets(img, inv, {d["name"] for d in dets}))
    return dets


def annotate(img: np.ndarray, dets: list[dict]) -> np.ndarray:
    """检出框画到画面上；有中文字体时用 PIL 写中文标签，否则退回英文名。"""
    if not dets:
        return img.copy()
    out = img.copy()
    font = _font()
    if font is None:  # 无中文字体：走旧 cv2 路径（ASCII 标签）
        for d in dets:
            _cv2_label(out, d, f"{d['name']} {d['conf']:.2f}"
                              + (" [px]" if d.get("src") == "pixel" else ""))
        return out
    from PIL import Image, ImageDraw
    pil = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    for d in dets:
        text = f"{zh(d['name'])} {d['conf']:.2f}"
        if d.get("src") == "pixel":
            text += " ◇像素"
        if d["level"]:
            text += f" -> L{d['level']}"
        x1, y1, x2, y2 = d["xyxy"]
        color = _color(d["cid"])[::-1]  # BGR -> RGB
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ty = y1 - th - 8 if y1 - th - 8 > 0 else y2 + 4
        draw.rectangle([x1, ty - 4, x1 + tw + 6, ty + th + 4], fill=color)
        draw.text((x1 + 3, ty), text, font=font, fill=(0, 0, 0))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def _cv2_label(out: np.ndarray, d: dict, label: str) -> None:
    """无中文字体时的兜底标签绘制（英文名）。"""
    x1, y1, x2, y2 = d["xyxy"]
    color = _color(d["cid"])
    cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    ty = y1 - 6 if y1 - 6 > th else y2 + th + 6
    cv2.rectangle(out, (x1, ty - th - 4), (x1 + tw + 4, ty + 4), color, -1)
    cv2.putText(out, label, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (0, 0, 0), 1, cv2.LINE_AA)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--instance", default="mumu0",
                    help="config.yaml 里的实例 id（mumu0 / mumu1）")
    ap.add_argument("--model", default=None,
                    help="默认取 config.yaml 的 app.yolo_model")
    ap.add_argument("--conf", type=float, default=0.5, help="绘制/打印的置信度阈值")
    ap.add_argument("--interval", type=float, default=1.0, help="抓帧间隔秒")
    ap.add_argument("--once", action="store_true", help="只跑一帧并保存，不弹窗")
    ap.add_argument("--save", action="store_true", help="除弹窗外额外保存标注帧")
    ap.add_argument("--out", default=str(ROOT / "logs" / "annotate"))
    ap.add_argument("--disp-w", type=int, default=1280,
                    help="显示窗口宽度（源 1920 缩到该宽，避免超出屏幕截切）")
    args = ap.parse_args()

    from ultralytics import YOLO

    config = load_config(Path(args.config))
    inst = next((i for i in config.instances if i.id == args.instance), None)
    if inst is None:
        print(f"实例 {args.instance!r} 不在 config.yaml（可选："
              f"{[i.id for i in config.instances]}）")
        return 1
    handle = create_handle_source(
        mumu_index=inst.mumu_index, mumu_manager_path=config.app.mumu_manager_path,
        adb_address=inst.adb_address, adb_path=config.app.adb_path,
        window_title_pattern=inst.window_title_pattern)

    model_path = args.model or getattr(config.app, "yolo_model", None) \
        or str(ROOT / "runs/gpu_1080_v8/weights/best.pt")
    if not os.path.isabs(model_path):
        model_path = str((ROOT / model_path).resolve())
    yolo = YOLO(model_path)
    names = yolo.names
    inv = {v: k for k, v in names.items()}   # name -> cid：像素判据复用 YOLO 的类表
    print(f"model={model_path}  classes={len(names)}  conf>={args.conf}")
    print(f"instance={args.instance}  capture via adb "
          f"({getattr(handle, '_address', 'win32')})")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    n_saved = 0

    def _emit(img, results):
        nonlocal n_saved
        dets = _detections(img, results, names, args.conf, inv)
        vis = annotate(img, dets)
        det_str = ", ".join(
            f"{zh(d['name'])}({d['conf']:.2f})"
            + (f"->L{d['level']}" if d["level"] else "")
            for d in dets) or "(none)"
        print(f"[{time.strftime('%H:%M:%S')}] {len(dets)} dets: {det_str}")
        for d in dets:
            if d["name"] == "zhaizi_level_text":
                result = f"等级 {d['level']}" if d["level"] else "未识别出数字"
                print(f"  [OCR] 寨子等级文本识别结果: {result}")
        if args.once or args.save:
            path = out_dir / f"annot_{stamp}_{n_saved:04d}.png"
            cv2.imencode(".png", vis)[1].tofile(str(path))
            n_saved += 1
            print(f"  saved -> {path}")
        return vis

    try:
        win = f"yolo live: {args.instance}"
        disp_h = int(args.disp_w * 1080 / 1920)
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)  # 可拉伸，避免 1:1 超出屏幕截切
        cv2.resizeWindow(win, args.disp_w, disp_h)
        while True:
            try:
                img = handle.capture()
            except Exception:
                # MuMu adb 偶发断连（exit 4294967295）：重连一次再试
                addr = getattr(handle, "_address", None)
                if addr is None:
                    raise
                print(f"  capture 失败，重连 adb {addr} ...")
                subprocess.run([config.app.adb_path, "connect", addr],
                               capture_output=True, timeout=10)
                img = handle.capture()
            results = yolo(img, verbose=False)
            vis = _emit(img, results)
            if args.once:
                return 0
            cv2.imshow(win, vis)
            key = cv2.waitKey(int(args.interval * 1000)) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("s"):
                # 无条件落盘。早先这里是 `n_saved -= 1` + 打印「手动保存」，真正写
                # 文件的那步在 _emit 的 `if args.once or args.save` 后面——没传
                # --save 时按 s 什么都不写，却照样打印「手动保存」，比没反应更坏：
                # 会让人以为自己存下了（2026-09-24 用户按 s 没反应才发现）。
                # 键的语义就是「存这一帧」，不该依赖别的开关。
                path = out_dir / f"annot_{stamp}_{n_saved:04d}.png"
                cv2.imencode(".png", vis)[1].tofile(str(path))
                n_saved += 1
                print(f"  saved -> {path}")
    except KeyboardInterrupt:
        print("\n中断退出")
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
