import pathlib
import sys

_TOOLS = pathlib.Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.append(str(_TOOLS))

import build_package                                       # noqa: E402


def test_verify_rejects_private_key_in_package(tmp_path, capsys):
    """私钥泄漏是**不可逆**的：一旦进包，等于把「给所有人发永久码」的能力
    交出去了。这条断言是保险丝，比任何文档提醒都可靠（spec §10）。"""
    app = tmp_path / "app"
    (app / "secrets").mkdir(parents=True)
    (app / "secrets" / "license_private.key").write_text("x", encoding="utf-8")
    assert build_package._verify(app) == 1
    assert "私钥" in capsys.readouterr().out


def test_verify_rejects_loose_private_key(tmp_path, capsys):
    app = tmp_path / "app"
    app.mkdir()
    (app / "license_private.key").write_text("x", encoding="utf-8")
    assert build_package._verify(app) == 1
    assert "私钥" in capsys.readouterr().out
