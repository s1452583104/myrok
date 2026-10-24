# -*- coding: utf-8 -*-
"""真机入口探针：一步步探「地图 → 活动页 → 习题演练」到底点哪里。

用法:
  $PY -X utf8 tools/quiz_entry_probe.py [--instance <实例id>] [--tap X,Y ...] [--save out.png]

不传 `--tap` 就只截一帧、打印 OCR 块与入口候选；每个 `--tap` 会先点那个坐标
再重新截图，逐帧打印。最后打印 `find_quiz_entry()` 的结论，以及一行可以直接
粘进 `config.yaml` 的 `entry_taps`。

为什么要有它：`dati/test/` 的素材都**从活动页开始**，地图那一步没有素材
（spec §10 已知局限 4）。入口路径只能真机探——**别在计划里臆造坐标**。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import cv2                                                          # noqa: E402
import numpy as np                                                  # noqa: E402

from rok_assistant.core.handle_source import create_handle_source    # noqa: E402
from rok_assistant.core.quiz.screen import (                         # noqa: E402
    detect_quiz, find_quiz_entry, parse_question)
from rok_assistant.core.recognizers.ocr_text import RapidOcrEngine   # noqa: E402
from rok_assistant.infra.app_paths import config_path                # noqa: E402
from rok_assistant.infra.config import load_config                    # noqa: E402

MAX_BLOCKS = 60


def _parse_tap(text: str) -> tuple[int, int]:
    x, y = text.split(",", 1)
    return int(x), int(y)


def _dump(frame, engine, taps: list[tuple[int, int]]) -> list:
    """打印一帧的 OCR 块与三种判据；返回 blocks 供调用方复用（OCR 很贵）。"""
    h, w = frame.shape[:2]
    blocks = engine.detect_text(frame)
    print(f"\n=== {w}x{h}  {len(blocks)} 块"
          f"  已点：{taps or '（无）'}")
    rows = sorted((box.y1, box.x1, text, conf, box) for box, text, conf in blocks)
    for i, (_y, _x, text, conf, box) in enumerate(rows):
        if i >= MAX_BLOCKS:
            print(f"    ... 还有 {len(rows) - MAX_BLOCKS} 块")
            break
        print(f"  y={box.y1:4d} x={box.x1:4d} c={conf:.2f} | {text[:40]}")
    print(f"  detect_quiz={detect_quiz(blocks)}"
          f"  parse={'有题目' if parse_question(blocks, w) else '无'}"
          f"  entry={find_quiz_entry(blocks)}")
    return blocks


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    instance_id = None
    taps: list[tuple[int, int]] = []
    save = None
    i = 0
    while i < len(args):
        if args[i] == "--instance" and i + 1 < len(args):
            instance_id = args[i + 1]
            i += 2
        elif args[i] == "--tap" and i + 1 < len(args):
            taps.append(_parse_tap(args[i + 1]))
            i += 2
        elif args[i] == "--save" and i + 1 < len(args):
            save = Path(args[i + 1])
            i += 2
        else:
            print(f"未知参数：{args[i]}")
            return 2

    cfg_file = config_path()
    if not cfg_file.is_file():
        print(f"找不到配置文件：{cfg_file}（先运行一次程序，它会生成 config.yaml）")
        return 1
    cfg = load_config(cfg_file)
    instances = list(cfg.quiz.instances)
    if not instances:
        print("config.yaml 的 quiz.instances 是空的——先填一台模拟器再探。")
        return 1
    inst = next((x for x in instances if x.id == instance_id), None) \
        if instance_id else instances[0]
    if inst is None:
        print(f"quiz.instances 里没有 id={instance_id}")
        return 1

    engine = RapidOcrEngine()
    app = cfg.app
    handle = create_handle_source(
        mumu_index=inst.mumu_index,
        mumu_manager_path=app.mumu_manager_path,
        adb_address=inst.adb_address,
        adb_path=app.adb_path,
        window_title_pattern=inst.window_title_pattern)
    print(f"[探针] 实例「{inst.name or inst.id}」——请先手动把号停在地图视图。")

    for tap in taps:
        print(f"[探针] 点击 {tap}")
        handle.click(tap[0], tap[1])
        time.sleep(1.5)                  # 等界面动画落定，否则截到的是过渡帧
    frame = handle.capture()
    blocks = _dump(frame, engine, taps)
    if save is not None:
        # cv2.imwrite 同样读不了中文路径，按扩展名编码再写字节
        ok, buf = cv2.imencode(save.suffix or ".png", frame)
        if ok:
            save.write_bytes(buf.tobytes())
            print(f"[探针] 已保存 {save}")

    entry = find_quiz_entry(blocks)
    if entry is None:
        print("\n没有找到入口文字。把号停在活动页再跑一次，"
              "或用 --tap 逐步试出路径，再把点过的坐标填进 entry_taps。")
    else:
        print(f"\n推荐点击点：{entry[0]},{entry[1]}")
    pts = ", ".join(f"[{x}, {y}]" for x, y in taps)
    print("探完把**确实点进去过**的坐标按顺序填进 config.yaml：")
    print(f"  quiz:\n    entry_taps: [{pts}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
