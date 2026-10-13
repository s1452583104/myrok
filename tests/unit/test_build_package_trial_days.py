"""`tools/build_package.py --trial-days`：构建期注入试用期天数（spec §5.5）。

生成物 `_trial_override.py` 落在**源码树**里，所以每条用例都把
`build_package._TRIAL_OVERRIDE` 指到 tmp_path——绝不能污染真实仓库。
"""
import pathlib
import sys

_TOOLS = pathlib.Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.append(str(_TOOLS))

import build_package                                       # noqa: E402


def _point_at_tmp(monkeypatch, tmp_path):
    target = tmp_path / "_trial_override.py"
    monkeypatch.setattr(build_package, "_TRIAL_OVERRIDE", target)
    return target


def test_write_then_clear_roundtrip(monkeypatch, tmp_path):
    target = _point_at_tmp(monkeypatch, tmp_path)
    build_package._write_trial_override(2)
    assert "TRIAL_DAYS = 2" in target.read_text(encoding="utf-8")
    build_package._clear_trial_override()
    assert not target.exists()


def test_clear_is_idempotent(monkeypatch, tmp_path):
    _point_at_tmp(monkeypatch, tmp_path)
    build_package._clear_trial_override()      # 文件不存在也不该抛
    build_package._clear_trial_override()


def test_write_refuses_stale_override(monkeypatch, tmp_path):
    """残留文件说明上一次构建没清干净——宁可失败，也不要用错值构建。"""
    target = _point_at_tmp(monkeypatch, tmp_path)
    target.write_text("TRIAL_DAYS = 9999\n", encoding="utf-8")
    try:
        build_package._write_trial_override(2)
    except RuntimeError as e:
        assert "残留" in str(e)
    else:
        raise AssertionError("文件已存在时 _write_trial_override 应报错")


def test_default_trial_days_is_30_and_skip_build_writes_nothing(monkeypatch,
                                                               tmp_path):
    """不传 --trial-days 时默认 30；--skip-build 下不写生成物。"""
    assert build_package.DEFAULT_TRIAL_DAYS == 30
    target = _point_at_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(build_package, "_verify", lambda _app: 0)
    assert build_package.main(["--skip-build", "--no-zip"]) == 0
    assert not target.exists()


def test_trial_days_out_of_range_rejected(capsys):
    assert build_package.main(["--trial-days", "0"]) == 2
    assert build_package.main(["--trial-days", "99999"]) == 2
    assert "1.." in capsys.readouterr().err
