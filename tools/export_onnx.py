"""把训练好的 .pt 检测权重导出成 onnxruntime 能跑的 .onnx。

为什么需要：运行时（src/）已经不再依赖 ultralytics/torch，只认 .onnx
（见 core/recognizers/onnx_detect.py）。发行包因此不用带 3~4GB 的 torch。

导出用 ultralytics 自己（它会把类别名写进 ONNX 的 metadata_props），
导出完立刻用 onnxruntime 重新打开做一遍自检：输入/输出形状、类别数、
文件大小。形状或类别数不对就直接失败，不要等到实机才发现。

用法（仓库根目录）：
    .venv/Scripts/python.exe -X utf8 tools/export_onnx.py
    .venv/Scripts/python.exe -X utf8 tools/export_onnx.py --weights runs/gpu_1080_v8/weights/best.pt
    .venv/Scripts/python.exe -X utf8 tools/export_onnx.py --parity

导出后**必须**重跑 tools/calibrate_yolo_threshold.py 复核阈值——换权重
（哪怕是同一份权重的 ONNX 版本）都要重新标定，见 template_registry.py 的
DEFAULT_YOLO_THRESHOLD 注释。
"""
from __future__ import annotations

import argparse
import ast
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_OUT = ROOT / "models" / "detect.onnx"


def _resolve_weights(explicit: str | None) -> Path:
    """没给 --weights 时：读 config.yaml 的 app.yolo_model（若是 .pt），否则用 v10。"""
    if explicit:
        return Path(explicit)
    cfg_path = ROOT / "config.yaml"
    if cfg_path.is_file():
        try:
            from rok_assistant.infra.config import load_config
            model = load_config(cfg_path).app.yolo_model
            if model and Path(model).suffix.lower() == ".pt":
                p = Path(model)
                return p if p.is_absolute() else ROOT / p
        except Exception as e:                            # noqa: BLE001 - 只是取默认值
            print(f"[warn] 读 config.yaml 取 yolo_model 失败（{e}），改用默认权重")
    return ROOT / "runs" / "gpu_1080_v10" / "weights" / "best.pt"


def _export(weights: Path, imgsz: int, opset: int, simplify: bool) -> Path:
    from ultralytics import YOLO
    print(f"[1/3] 导出 ONNX：{weights}（imgsz={imgsz} opset={opset} simplify={simplify}）")
    model = YOLO(str(weights))
    produced = Path(model.export(format="onnx", imgsz=imgsz, opset=opset,
                                 simplify=simplify, dynamic=False,
                                 half=False, device="cpu", nms=False))
    return produced


def _verify(onnx_path: Path, imgsz: int) -> dict:
    """用 onnxruntime 打开导出的模型自检；返回 {nc, names, in_shape, out_shape}。"""
    import onnxruntime as ort
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    out = sess.get_outputs()[0]
    meta = sess.get_modelmeta().custom_metadata_map or {}

    names = {}
    raw = meta.get("names")
    if raw:
        try:
            names = {int(k): str(v) for k, v in ast.literal_eval(raw).items()}
        except Exception as e:                            # noqa: BLE001
            print(f"[warn] 元数据 names 解析失败（{e}），将回落到 .names.json sidecar")

    in_shape = list(inp.shape)
    out_shape = list(out.shape)
    print(f"[2/3] 自检：输入 {in_shape}  输出 {out_shape}")
    if names:
        print(f"      类别数 {len(names)}：{list(names.values())[:5]} ...")

    expect_in = [1, 3, imgsz, imgsz]
    if in_shape != expect_in:
        raise SystemExit(f"输入形状不对：期望 {expect_in}，实际 {in_shape}")
    if len(out_shape) != 3:
        raise SystemExit(f"输出不是 3 维，导出的可能不是 detect 头：{out_shape}")
    if not names:
        sidecar = onnx_path.with_suffix(".names.json")
        print(f"[warn] ONNX 元数据里没有 names，写 sidecar：{sidecar}")
        import json
        sidecar.write_text(json.dumps({str(k): v for k, v in names.items()}),
                           encoding="utf-8")
    return {"nc": len(names), "names": names,
            "in_shape": in_shape, "out_shape": out_shape}


def _parity(onnx_path: Path, weights: Path, limit: int) -> int:
    """同一批实机帧分别走 .pt 与 .onnx，比对框的数量/坐标/置信度。

    .pt 的 predict 用 auto=True 的矩形推理（1920x1080 -> 640x384），静态
    ONNX 用 640x640 方形补边，两者内容缩放比例相同但上下位置差一个常数，
    所以**不会逐位相同**，这里只报偏差量级供判断。
    """
    import cv2
    from ultralytics import YOLO
    from rok_assistant.core.recognizers.onnx_detect import OnnxYoloModel

    frames = _sample_frames(limit)
    if not frames:
        print("[3/3] 没找到可比对的帧（logs/_v10_val.txt 或 recordings/ 都为空），跳过 parity")
        return 0

    pt = YOLO(str(weights))
    onnx_model = OnnxYoloModel(onnx_path)
    print(f"[3/3] parity：{len(frames)} 帧，比对 .pt(auto=True 矩形) vs .onnx(640 方形)")

    # 按 IoU 配对，不能按置信度排序后 zip——分数稍有出入就会拿 A 的框比 B 的框。
    n_pt = n_on = n_matched = n_missed = 0
    max_conf_delta = 0.0
    max_center_delta = 0.0
    min_iou = 1.0
    for fp in frames:
        img = cv2.imdecode(np.fromfile(str(fp), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        r = pt(img, device="cpu", verbose=False)[0]
        pt_boxes = []
        for b in r.boxes:
            xyxy = b.xyxy[0].cpu().numpy() if hasattr(b.xyxy[0], "cpu") \
                else np.asarray(b.xyxy[0])
            pt_boxes.append((int(b.cls[0]), float(b.conf[0]), np.asarray(xyxy, float)))
        on_boxes = [(b.cls[0], b.conf[0], np.asarray(b.xyxy[0], float))
                    for b in onnx_model(img)[0].boxes]

        n_pt += len(pt_boxes)
        n_on += len(on_boxes)
        for pc, pconf, pxy in pt_boxes:
            best_iou, best = 0.0, None
            for oc, oconf, oxy in on_boxes:
                if oc != pc:
                    continue
                iou = _iou(pxy, oxy)
                if iou > best_iou:
                    best_iou, best = iou, oconf
            if best is None or best_iou < 0.5:
                n_missed += 1
                continue
            n_matched += 1
            min_iou = min(min_iou, best_iou)
            max_conf_delta = max(max_conf_delta, abs(pconf - best))
            pcx = ((pxy[0] + pxy[2]) / 2, (pxy[1] + pxy[3]) / 2)
            for oc, oconf, oxy in on_boxes:
                if oc == pc and _iou(pxy, oxy) == best_iou:
                    ocx = ((oxy[0] + oxy[2]) / 2, (oxy[1] + oxy[3]) / 2)
                    max_center_delta = max(max_center_delta,
                                           max(abs(a - b) for a, b in zip(pcx, ocx)))
                    break

    print(f"      .pt 框数 {n_pt}，.onnx 框数 {n_on}")
    print(f"      配对成功 {n_matched}，.pt 里没配上（IoU<0.5）的 {n_missed}")
    if n_matched:
        print(f"      配对框最小 IoU：{min_iou:.3f}")
        print(f"      最大置信度偏差：{max_conf_delta:.4f}")
        print(f"      最大中心点偏差：{max_center_delta:.1f} px")
    print("      判据：配对数应≈.pt 框数、IoU 应普遍 >0.9、置信度偏差应远小于"
          " 标定脚本打印的阈值间隙。")
    return 0


def _iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _sample_frames(limit: int) -> list[Path]:
    """取一批实机帧：优先 logs/_v10_val.txt 里的路径，其次 recordings/ 下的截图。"""
    frames: list[Path] = []
    listing = ROOT / "logs" / "_v10_val.txt"
    if listing.is_file():
        for line in listing.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            p = Path(line)
            if not p.is_absolute():
                p = ROOT / p
            if p.is_file():
                frames.append(p)
            if len(frames) >= limit:
                return frames
    rec = ROOT / "recordings"
    if rec.is_dir():
        frames.extend(sorted(rec.glob("*.png"))[:max(0, limit - len(frames))])
    return frames


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weights", help=".pt 权重（默认取 config.yaml 的 app.yolo_model）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出 .onnx 路径")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--opset", type=int, default=17)
    ap.add_argument("--no-simplify", action="store_true", help="跳过 onnxslim 简化")
    ap.add_argument("--parity", action="store_true",
                    help="导出后与 .pt 在同一批实机帧上比对")
    ap.add_argument("--parity-limit", type=int, default=20)
    args = ap.parse_args()

    weights = _resolve_weights(args.weights)
    if not weights.is_file():
        print(f"[error] 找不到权重：{weights}", file=sys.stderr)
        return 2
    if weights.suffix.lower() != ".pt":
        print(f"[error] --weights 要是 .pt（拿到的 {weights.suffix}）", file=sys.stderr)
        return 2

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out

    produced = _export(weights, args.imgsz, args.opset, not args.no_simplify)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(produced, out)

    info = _verify(out, args.imgsz)
    size_mb = out.stat().st_size / 1024 / 1024
    print(f"      产物 {out}（{size_mb:.1f} MB）")

    if args.parity:
        _parity(out, weights, args.parity_limit)

    print()
    print(f"完成。把 config.yaml / config.example.yaml 的 app.yolo_model 指向 {out.name}")
    print("然后**必须**复核阈值："
          ".venv/Scripts/python.exe -X utf8 tools/calibrate_yolo_threshold.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
