"""所有 HandleSource 实现都必须收下 `rapid` 关键字（spec §9）。"""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "rok_assistant"


def _click_impls():
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "click":
                    yield f"{path.name}:{node.name}", fn


def test_every_click_implementation_accepts_rapid():
    found = dict(_click_impls())
    assert len(found) >= 6, f"只扫到 {sorted(found)}，路径算错了"
    missing = sorted(where for where, fn in found.items()
                     if "rapid" not in {a.arg for a in fn.args.args})
    assert missing == []
