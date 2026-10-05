"""Manual verification script — walks through spec section 10 acceptance checklist.

Run each scenario in the game, mark off as you go.
For automated regression, see tests/integration/.
"""
import argparse
import sys
from pathlib import Path

# Make src/ importable when run from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# 2026-10-04：锁定城寨重搜 / 集结超时重开 / 关模拟器暂停三项按用户裁定不再要求
# 单独验收，与 docs/ACCEPTANCE.md §3 同步删除（编号 3.3–3.5 保留跳跃）。
CHECKS = [
    ("Start 1 emulator + 1 character, run 1 rally", "leader_full_session"),
    ("Add 1 member, verify auto-switch + join", "member_with_switch"),
    ("Invalid config (level=11) -> refused at startup", "config_invalid"),
    ("Wrong char name -> OCR verify fails + retry", "switch_verify_fail"),
    ("Log records all steps + screenshot on failure", "logging"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml",
                        help="Config file (currently unused — checklist is manual)")
    parser.add_argument("--check", choices=[c[1] for c in CHECKS] + ["all"],
                        default="all",
                        help="Highlight a specific check; default 'all'")
    args = parser.parse_args()

    print("Manual verification checklist (spec section 10):")
    print()
    for label, key in CHECKS:
        marker = "x" if args.check == "all" or args.check == key else " "
        print(f"  [{marker}] {label}  ({key})")
    print()
    print("Run each scenario in the game. Mark off as you go.")
    print("For automated regression, see tests/integration/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
