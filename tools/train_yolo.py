"""Train YOLO on the auto-labeled dataset (see tools/auto_label_yolo.py).

CPU fallback config is deliberately small (yolov8n + imgsz 640): it validates
the data pipeline and convergence, but small UI icons need native resolution,
which requires a GPU. On a CUDA machine use:
    .venv/Scripts/python.exe tools/train_yolo.py --epochs 100 --imgsz 1920 --batch 8

注意必须用 venv 的解释器：系统 `python`（C:\\coding\\python）装的是 torch+cpu，
在里面跑只会得到「Invalid CUDA 'device=0' requested」这种指向驱动、实际无关的
报错（2026-09-24 踩了两次）。_preflight_device 会把这种情况直接点明。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _preflight_device(device: str) -> None:
    """设备是 CUDA 但当前解释器的 torch 没有 CUDA 时，直接点明是解释器的问题。

    2026-09-24 被这个坑了两次：拿系统 python（torch+cpu）跑，ultralytics 只报
    「Invalid CUDA 'device=0' requested」，看着像驱动/CUDA 装坏了，实际是敲错了
    解释器——项目 venv 里才是 torch+cu128。报错信息指错方向比不报错更费时间。
    """
    if device.strip().lower() in ("cpu", ""):
        return
    import torch

    if torch.cuda.is_available():
        return
    print(f"!! --device {device} 要 CUDA，但当前解释器的 torch 没有 CUDA：\n"
          f"     解释器：{sys.executable}\n"
          f"     torch ：{torch.__version__}\n"
          f"   项目 venv 里装的是 CUDA 版 torch，用它的解释器跑：\n"
          f"     {ROOT / '.venv' / 'Scripts' / 'python.exe'}\n"
          f"   确实想跑 CPU 就显式传 --device cpu。", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=ROOT / "dataset" / "dataset.yaml")
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--workers", type=int, default=2,
                    help="dataloader workers; 8 workers each buffer a batch of "
                         "1080p images and can OOM alongside running emulators")
    ap.add_argument("--name", default="smoke_cpu")
    # 显式给设备，别依赖自动选择：2026-09-24 的 v8 不传 device，ultralytics 把
    # device 解析成了 'cpu'（args.yaml 记的就是 cpu），GPU 全程 0%/0MiB，
    # 131s/epoch 白跑 24 分钟。历史上 9 个 run 里 8 个记的是 device: ''（=自动→GPU），
    # 只有 v8 是 cpu，触发条件没查明——所以直接钉死，不让它有机会静默降级。
    # 真起不来 CUDA 时会报错，比默默用 CPU 好。
    ap.add_argument("--device", default="0",
                    help="训练设备，默认 '0'（第一块 GPU）。CPU 冒烟测试传 --device cpu")
    ap.add_argument("--resume", action="store_true",
                    help="resume from <project>/<name>/weights/last.pt")
    args = ap.parse_args()
    _preflight_device(args.device)

    from ultralytics import YOLO

    if args.resume:
        last = ROOT / "runs" / args.name / "weights" / "last.pt"
        # resume=True inherits all args from the checkpoint; patch workers in
        # place so the resumed run doesn't OOM host RAM with 8 dataloader
        # workers alongside the emulators
        import torch
        ckpt = torch.load(last, map_location="cpu", weights_only=False)
        ckpt["train_args"]["workers"] = args.workers
        # device 同理从 ckpt 继承：续跑一个在 CPU 上跑出来的 ckpt 会继续用 CPU，
        # 哪怕你现在是在 venv 里跑的。显式覆盖成 --device。
        ckpt["train_args"]["device"] = args.device
        torch.save(ckpt, last)
        model = YOLO(str(last))
        model.train(resume=True)
        return

    model = YOLO(args.model)
    model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        name=args.name,
        device=args.device,
        project=str(ROOT / "runs"),
        # small icons + limited data: heavier augmentation hurts more than helps
        mosaic=0.5,
        mixup=0.0,
        degrees=0.0,
        shear=0.0,
        perspective=0.0,
        flipud=0.0,
        fliplr=0.0,  # UI is direction-sensitive (back arrows etc.)
        exist_ok=True,
    )
    metrics = model.val()
    print("\n=== validation summary ===")
    print(f"mAP50: {metrics.box.map50:.4f}  mAP50-95: {metrics.box.map:.4f}")


if __name__ == "__main__":
    main()
