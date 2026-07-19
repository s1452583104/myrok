"""Record emulator screenshots to a session directory for replay testing."""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project src is importable when run from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rok_assistant.core.handle_source import Win32HandleSource
from rok_assistant.infra.paths import ProjectPaths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, help="Account id from config")
    parser.add_argument("--pattern", required=True, help="Window title pattern")
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--max-frames", type=int, default=600)
    parser.add_argument("--out", default="./recordings")
    args = parser.parse_args()

    out_root = Path(args.out)
    paths = ProjectPaths(root=out_root.parent)
    paths.ensure_dirs()
    session_dir = out_root / f"session_{datetime.now():%Y%m%d_%H%M%S}"
    session_dir.mkdir(parents=True, exist_ok=True)
    print(f"Recording to {session_dir}")

    handle = Win32HandleSource(window_title_pattern=args.pattern)
    if not handle.is_alive():
        print(f"ERROR: Window matching {args.pattern!r} not found")
        return 1

    import cv2
    manifest = []
    for i in range(args.max_frames):
        try:
            img = handle.capture()
        except Exception as e:
            print(f"\nFrame {i} failed: {e}")
            break
        fname = f"frame_{i:05d}.png"
        cv2.imwrite(str(session_dir / fname), img)
        manifest.append({"index": i, "file": fname, "ts": time.time()})
        print(f"\r{i+1}/{args.max_frames}", end="", flush=True)
        time.sleep(args.interval)

    (session_dir / "manifest.json").write_text(
        json.dumps({"account": args.account, "frames": manifest}, indent=2)
    )
    print(f"\nDone. {len(manifest)} frames saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
