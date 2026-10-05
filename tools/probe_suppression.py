# -*- coding: utf-8 -*-
"""污染回放探针 —— 把「撤掉的 0 框帧」重新喂给模型，量出污染被学进去了多深。

**为什么需要它。** 清理 0 框帧的效果**测不出来在 val mAP 上**：

1. val 会跟着少帧（清理撤掉 2 张 val 帧 → 69 变 67），前后不同源；
   实测同一模型 v9 在 69 帧上 mAP50 0.7247、在 67 帧上 0.7248 —— 尺子自己会动。
2. val 只覆盖 44/64 类，20 类零实例；受这批裁剪帧影响的类里
   `profile_title` / `red_rally` / `settings_btn` 等**在 val 里根本没有实例**。
3. 有实例的也极小：`join_create_btn` / `sort_selector` 在 val 里各只有 1 个实例，
   翻转一个实例就是该类 AP 0↔1，摊到 44 类上 ≈ ±0.023 —— 比预期提升本身还大。

所以 mAP 在这里**分辨率不够**。能一眼看出来的是**回放**：同一批图，两个模型出框差异。

**判据。** 污染的定义就是「画着目标、标签却是 0 行」，YOLO 当纯背景学 →
反向梯度教模型在这些图上闭嘴。所以：

- 污染模型（如 v9）：峰值分极低、且峰值类常常**不是**画面里的类（不是拿不准，是被压低）
- 清理后重训（如 v10）：应当显著抬升

实测 v9 在 24 张裁剪帧上：峰值分中位 **0.004**，只有 2/24 出框；而两张窗口截图
（更像真实截图）能到 0.306 / 0.862。效应量极大，远不是 mAP 那种千分位噪声。

**注意帧要留着。** `audit_empty_frames.py --apply` 会把这些帧备份到
`dataset/_emptyfix_backup_<时间戳>/images/`；清理后把 `--frames` 指过去即可。

用法（仓库根目录）：
    # 单模型：看抑制剖面
    .venv/Scripts/python.exe -X utf8 tools/probe_suppression.py --model gpu_1080_v9

    # A/B：清理前 vs 清理后，逐帧给 Δ（这才是「清理有没有效果」的答案）
    .venv/Scripts/python.exe -X utf8 tools/probe_suppression.py \\
        --model gpu_1080_v9 --model gpu_1080_v10

    # 清理后帧已挪走，指到备份目录
    .venv/Scripts/python.exe -X utf8 tools/probe_suppression.py \\
        --model gpu_1080_v9 --model gpu_1080_v10 \\
        --frames dataset/_emptyfix_backup_20261003-120000/images

    # 也能拿别的一组帧来探（目录或 .txt 列表都行）
    .venv/Scripts/python.exe -X utf8 tools/probe_suppression.py \\
        --model gpu_1080_v9 --frames logs/my_frames.txt
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

NATIVE = (1920, 1080)
COUNT_CONF = 0.25      # 算「出框了没有」用的阈值，和实机一致
PEAK_CONF = 0.001      # 看「被压低」而不是「完全瞎」——拉到最低


def _rows(label_path: Path) -> list[str]:
    if not label_path.exists():
        return []
    return [l for l in label_path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _default_frames(dataset: Path) -> list[Path]:
    """数据集里还在的 0 框裁剪帧；都被清了就退到最近的备份目录。"""
    from PIL import Image

    live = []
    if (dataset / "images").is_dir():
        for p in sorted((dataset / "images").glob("*.png")):
            if _rows(dataset / "labels" / f"{p.stem}.txt"):
                continue
            if Image.open(p).size != NATIVE:
                live.append(p)
    if live:
        return live
    backups = sorted(dataset.glob("_emptyfix_backup_*/images"), reverse=True)
    if backups:
        print(f"（数据集里已无 0 框裁剪帧，改用备份目录 {backups[0].name}/）")
        return sorted(backups[0].glob("*.png"))
    return []


def _resolve_frames(spec: Path | None, dataset: Path) -> list[Path]:
    if spec is None:
        return _default_frames(dataset)
    if spec.is_dir():
        return sorted(spec.glob("*.png"))
    if spec.is_file():
        return [Path(l.strip()) for l in
                spec.read_text(encoding="utf-8").splitlines() if l.strip()]
    raise SystemExit(f"--frames 既不是目录也不是文件：{spec}")


def _weights(model: str) -> Path:
    """接受 run 名（gpu_1080_v9）或 .pt 路径。"""
    p = Path(model)
    if p.suffix == ".pt":
        return p if p.is_absolute() else ROOT / p
    return ROOT / "runs" / model / "weights" / "best.pt"


def probe(model: str, frames: list[Path], names: dict[int, str]) -> list[dict]:
    from ultralytics import YOLO
    from PIL import Image

    w = _weights(model)
    if not w.exists():
        raise SystemExit(f"找不到权重：{w}")
    m = YOLO(str(w))
    res = m.predict([str(p) for p in frames], conf=PEAK_CONF, verbose=False)

    out = []
    for p, r in zip(frames, res):
        cf = r.boxes.conf.tolist()
        cl = [names.get(int(c), str(int(c))) for c in r.boxes.cls.tolist()]
        top = sorted(zip(cf, cl), reverse=True)[:1]
        wpx, hpx = Image.open(p).size
        out.append({
            "frame": p.name,
            "size": f"{wpx}x{hpx}",
            "peak": top[0][0] if top else 0.0,
            "peak_cls": top[0][1] if top else "-",
            "n": sum(1 for c in cf if c >= COUNT_CONF),
        })
    return out


def _summary(rows: list[dict], n: int) -> dict:
    peaks = [r["peak"] for r in rows]
    return {
        "fire": sum(1 for r in rows if r["n"] > 0),
        "peak_med": statistics.median(peaks) if peaks else 0.0,
        "peak_max": max(peaks) if peaks else 0.0,
        "total": n,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", action="append", required=True,
                    help="run 名或 .pt 路径；给两次即 A/B 对比")
    ap.add_argument("--frames", type=Path, default=None,
                    help="帧目录或 .txt 列表（默认：数据集里的 0 框裁剪帧）")
    ap.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    ap.add_argument("--out", type=Path, default=None, help="把报告也写一份到文件")
    args = ap.parse_args()

    frames = _resolve_frames(args.frames, args.dataset)
    if not frames:
        print("没有可探的帧（数据集里已无 0 框裁剪帧，也没有 _emptyfix_backup_*/）。")
        return 0

    names = {int(k): str(v) for k, v in yaml.safe_load(
        (args.dataset / "dataset.yaml").read_text(encoding="utf-8"))["names"].items()}

    lines: list[str] = []

    def say(s: str = "") -> None:
        print(s)
        lines.append(s)

    say(f"帧源：{frames[0].parent}   共 {len(frames)} 帧")
    say(f"出框判据：conf >= {COUNT_CONF}；峰值分：conf >= {PEAK_CONF} 的最高分")
    say()
    say("回放中…（加载模型 + 推理）")

    got = {}
    for mname in args.model:
        got[mname] = probe(mname, frames, names)

    ms = list(args.model)
    if len(ms) == 1:
        a = got[ms[0]]
        hdr = f"{'帧':<40}{'尺寸':>11}{'峰值':>8}{'出框':>6}  峰值类"
        say(hdr)
        say("-" * len(hdr))
        for r in a:
            say(f"{r['frame']:<40}{r['size']:>11}{r['peak']:>8.3f}{r['n']:>6}  {r['peak_cls']}")
        s = _summary(a, len(frames))
        say("-" * len(hdr))
        say(f"出框 {s['fire']}/{s['total']}   峰值分 中位 {s['peak_med']:.3f} / 最大 {s['peak_max']:.3f}")
    else:
        A, B = got[ms[0]], got[ms[-1]]
        hdr = (f"{'帧':<38}{'A峰值':>8}{'A框':>5}{'B峰值':>8}{'B框':>5}"
               f"{'Δ峰值':>9}  B 的峰值类")
        say(f"A = {ms[0]}    B = {ms[-1]}")
        say(hdr)
        say("-" * len(hdr))
        for ra, rb in zip(A, B):
            d = rb["peak"] - ra["peak"]
            flag = "  ↑" if d > 0.10 else ("  ↓" if d < -0.10 else "")
            say(f"{ra['frame']:<38}{ra['peak']:>8.3f}{ra['n']:>5}"
                f"{rb['peak']:>8.3f}{rb['n']:>5}{d:>+9.3f}{flag}  {rb['peak_cls']}")
        sa, sb = _summary(A, len(frames)), _summary(B, len(frames))
        say("-" * len(hdr))
        say(f"出框率     A {sa['fire']}/{sa['total']} ({sa['fire']/sa['total']*100:.0f}%)"
            f"   B {sb['fire']}/{sb['total']} ({sb['fire']/sb['total']*100:.0f}%)"
            f"   Δ {(sb['fire']-sa['fire'])/sa['total']*100:+.0f}pp")
        say(f"峰值中位   A {sa['peak_med']:.3f}   B {sb['peak_med']:.3f}"
            f"   Δ {sb['peak_med']-sa['peak_med']:+.3f}")
        say(f"峰值最大   A {sa['peak_max']:.3f}   B {sb['peak_max']:.3f}"
            f"   Δ {sb['peak_max']-sa['peak_max']:+.3f}")
        say()
        say("读法：污染模型的峰值中位贴着 0（模型被教成闭嘴）是**预期**；")
        say("      B 相对 A 抬升 = 清理真的把这段抑制拆掉了。")
        say("      注意这批图是模板裁图，属域外输入 —— 这里是**相对**判据（A vs B），")
        say("      不是绝对能力值；运行时的效果另看 compare_runs.py 的逐类 AP。")

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n已写 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
