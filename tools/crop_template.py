"""Interactive template cropper.

Usage:
    python tools/crop_template.py --input screenshots/main_city.png
    python tools/crop_template.py --input foo.png --id search_icon --threshold 0.9 --roi "10,660,100,760"

Workflow:
  1. Window opens showing the screenshot
  2. Drag a rectangle around the UI element you want as a template
  3. Press ENTER to save (will prompt for id if --id not given)
  4. Press R to reset, ESC to cancel
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml


WINDOW = "Crop Template"
PREVIEW = "Saved"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, help="Path to source screenshot")
    p.add_argument(
        "--output-dir",
        default="templates",
        help="Where to write template PNGs (default: templates/)",
    )
    p.add_argument("--id", help="Template id (will prompt if not given)")
    p.add_argument(
        "--threshold", type=float, default=0.9, help="Match threshold (default 0.9)"
    )
    p.add_argument(
        "--roi",
        default="full",
        help='ROI: "full" or "x1,y1,x2,y2" (default: full)',
    )
    return p.parse_args()


def parse_roi(s: str):
    if s == "full" or not s:
        return "full"
    parts = [int(x) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"ROI must be 'x1,y1,x2,y2' or 'full', got {s!r}")
    return parts


def load_or_init_manifest(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data is None:
                return {"templates": []}
            # ensure shape
            data.setdefault("templates", [])
            return data
    return {"templates": []}


def save_manifest(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def prompt_id(default: str = "") -> str:
    s = input(f"  Template id [{default}]: ").strip()
    return s or default


def main() -> int:
    args = parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"ERROR: input file not found: {src}", file=sys.stderr)
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.yaml"

    img = cv2.imread(str(src))
    if img is None:
        print(f"ERROR: could not read image: {src}", file=sys.stderr)
        return 1

    base = img.copy()
    state = {
        "start": None,
        "end": None,
        "drawing": False,
        "done": False,
        "saved": False,
    }

    def draw_overlay():
        view = base.copy()
        # Banner
        cv2.rectangle(view, (0, 0), (view.shape[1], 36), (0, 0, 0), -1)
        cv2.putText(
            view,
            "Drag to select. ENTER=save, R=reset, ESC=cancel",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        if state["start"] and state["end"]:
            x1, y1 = state["start"]
            x2, y2 = state["end"]
            x1, x2 = sorted((x1, x2))
            y1, y2 = sorted((y1, y2))
            cv2.rectangle(view, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                view,
                f"({x1},{y1}) - ({x2},{y2})  {x2-x1}x{y2-y1}",
                (x1, max(y1 - 8, 16)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )
        cv2.imshow(WINDOW, view)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["start"] = (x, y)
            state["end"] = (x, y)
            state["drawing"] = True
            draw_overlay()
        elif event == cv2.EVENT_MOUSEMOVE and state["drawing"]:
            state["end"] = (x, y)
            draw_overlay()
        elif event == cv2.EVENT_LBUTTONUP:
            state["drawing"] = False
            state["end"] = (x, y)
            draw_overlay()

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WINDOW, on_mouse)
    draw_overlay()

    print("Drag a rectangle on the image. Press ENTER in the image window to save, ESC to cancel.")

    while True:
        key = cv2.waitKey(50) & 0xFF
        if key in (13, 32):  # ENTER or SPACE
            if not state["start"] or not state["end"]:
                print("  No region selected. Drag first.")
                continue
            x1, y1 = state["start"]
            x2, y2 = state["end"]
            # Normalize
            x1, x2 = sorted((x1, x2))
            y1, y2 = sorted((y1, y2))
            if x2 - x1 < 4 or y2 - y1 < 4:
                print("  Region too small. Drag a larger area.")
                continue
            # Prompt for id if not given
            tid = args.id
            if not tid:
                print(f"  Selected region: ({x1},{y1}) - ({x2},{y2}) = {x2-x1}x{y2-y1}")
                tid = prompt_id()
                if not tid:
                    print("  No id given, skipping save.")
                    continue
            # Check overwrite
            dest = out_dir / f"{tid}.png"
            if dest.exists():
                ans = input(f"  {dest.name} already exists. Overwrite? [y/N]: ").strip().lower()
                if ans != "y":
                    print("  Skipped.")
                    continue
            # Save crop
            crop = img[y1:y2, x1:x2]
            cv2.imwrite(str(dest), crop)
            # Update manifest
            manifest = load_or_init_manifest(manifest_path)
            roi = parse_roi(args.roi)
            entry = {
                "id": tid,
                "file": dest.name,
                "threshold": args.threshold,
                "roi": roi,
            }
            # Remove existing entry with same id
            manifest["templates"] = [
                t for t in manifest.get("templates", []) if t.get("id") != tid
            ]
            manifest["templates"].append(entry)
            save_manifest(manifest_path, manifest)
            # Show preview briefly
            cv2.imshow(PREVIEW, crop)
            cv2.waitKey(800)
            try:
                cv2.destroyWindow(PREVIEW)
            except cv2.error:
                pass
            print(f"  Saved {dest} and updated {manifest_path}")
            state["saved"] = True
            break
        elif key in (ord("r"), ord("R")):
            state["start"] = None
            state["end"] = None
            state["drawing"] = False
            draw_overlay()
        elif key == 27:  # ESC
            print("Cancelled.")
            break

    cv2.destroyAllWindows()
    return 0 if state["saved"] else 1


if __name__ == "__main__":
    sys.exit(main())
