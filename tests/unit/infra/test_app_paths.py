"""app_paths：冻结/源码两种运行方式下的根目录解析 + 首启生成 config.yaml。"""
import sys
from pathlib import Path

import pytest

from rok_assistant.infra import app_paths, mumu


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    """伪装成 PyInstaller 冻结运行：exe 在 tmp/exe，资源在 tmp/exe/_internal。"""
    exe_dir = tmp_path / "exe"
    internal = exe_dir / "_internal"
    internal.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "rok-assistant.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    return exe_dir, internal


def test_dev_dirs_are_repo_root():
    root = Path(app_paths.__file__).resolve().parents[3]
    assert app_paths.app_base_dir() == root
    assert app_paths.resource_dir() == root
    assert app_paths.user_dir() == root
    assert app_paths.config_path() == root / "config.yaml"


def test_frozen_dirs_split_resource_and_user(frozen):
    exe_dir, internal = frozen
    assert app_paths.is_frozen()
    # 可写数据在 exe 同级；只读资源在 _internal（PyInstaller 的 datas 落点）
    assert app_paths.user_dir() == exe_dir
    assert app_paths.resource_dir() == internal
    assert app_paths.config_path() == exe_dir / "config.yaml"


def test_resolve_asset_relative_and_absolute(frozen):
    _, internal = frozen
    assert app_paths.resolve_asset("templates") == internal / "templates"
    assert app_paths.resolve_asset("models/detect.onnx") == internal / "models" / "detect.onnx"
    abs_path = Path("C:/somewhere/best.onnx")
    assert app_paths.resolve_asset(abs_path) == abs_path


def _seed_example(internal: Path) -> None:
    (internal / "config.example.yaml").write_text(
        "app:\n"
        "  # 留空 = 首启自动探测\n"
        "  mumu_manager_path: \"\"\n"
        "  adb_path: \"\"\n"
        "instances:\n"
        "  - id: mumu0\n"
        "    mumu_index: 0\n"
        "    characters: []\n",
        encoding="utf-8")


def test_ensure_user_files_seeds_from_example(frozen, monkeypatch):
    exe_dir, internal = frozen
    _seed_example(internal)
    monkeypatch.setattr(mumu, "detect_mumu_paths",
                        lambda: {"mumu_manager_path": "C:/mumu/MuMuManager.exe",
                                 "adb_path": "C:/mumu/adb.exe"})

    cfg = app_paths.ensure_user_files()
    assert cfg == exe_dir / "config.yaml"
    assert cfg.is_file()
    text = cfg.read_text(encoding="utf-8")
    assert "C:/mumu/MuMuManager.exe" in text
    assert "C:/mumu/adb.exe" in text


def test_fill_detected_paths_keeps_comments(frozen, monkeypatch):
    """探测回填只能改那两行，注释必须原样留着。

    config.example.yaml 里的注释是这份配置唯一的说明书；曾经用
    yaml.safe_load→safe_dump 往返实现，首启就把注释全抹了。
    """
    exe_dir, internal = frozen
    _seed_example(internal)
    monkeypatch.setattr(mumu, "detect_mumu_paths",
                        lambda: {"mumu_manager_path": r"C:\模拟器\MuMuPlayer\nx_main\MuMuManager.exe",
                                 "adb_path": r"C:\模拟器\MuMuPlayer\nx_main\adb.exe"})

    text = app_paths.ensure_user_files().read_text(encoding="utf-8")
    assert "# 留空 = 首启自动探测" in text, "注释被抹掉了"
    assert "mumu_index: 0" in text and "id: mumu0" in text
    # 单引号包裹：反斜杠才是字面量
    assert r"mumu_manager_path: 'C:\模拟器\MuMuPlayer\nx_main\MuMuManager.exe'" in text

    # 回填后仍是合法 yaml，且值原样读回来
    import yaml
    data = yaml.safe_load(text)
    assert data["app"]["mumu_manager_path"] == r"C:\模拟器\MuMuPlayer\nx_main\MuMuManager.exe"
    assert data["app"]["adb_path"] == r"C:\模拟器\MuMuPlayer\nx_main\adb.exe"


def test_fill_detected_paths_leaves_existing_value_alone(frozen, monkeypatch):
    """示例里已经填了值就不覆盖——用户手填的优先于探测。"""
    exe_dir, internal = frozen
    (internal / "config.example.yaml").write_text(
        "app:\n  mumu_manager_path: 'D:/already/set.exe'\n  adb_path: \"\"\n",
        encoding="utf-8")
    monkeypatch.setattr(mumu, "detect_mumu_paths",
                        lambda: {"mumu_manager_path": "C:/detected.exe",
                                 "adb_path": "C:/detected_adb.exe"})

    data = __import__("yaml").safe_load(
        app_paths.ensure_user_files().read_text(encoding="utf-8"))
    assert data["app"]["mumu_manager_path"] == "D:/already/set.exe"
    assert data["app"]["adb_path"] == "C:/detected_adb.exe"


def test_ensure_user_files_never_overwrites(frozen, monkeypatch):
    """已存在就一个字都不许改——用户可能手改过并留了注释。"""
    exe_dir, internal = frozen
    _seed_example(internal)
    monkeypatch.setattr(mumu, "detect_mumu_paths",
                        lambda: {"mumu_manager_path": "X", "adb_path": "Y"})
    existing = exe_dir / "config.yaml"
    existing.write_text("# 用户自己写的\napp: {}\n", encoding="utf-8")

    app_paths.ensure_user_files()
    assert existing.read_text(encoding="utf-8") == "# 用户自己写的\napp: {}\n"


def test_ensure_user_files_without_detection_keeps_example(frozen, monkeypatch):
    """探测不到就保留示例里的空值，不该炸。"""
    exe_dir, internal = frozen
    _seed_example(internal)
    monkeypatch.setattr(mumu, "detect_mumu_paths",
                        lambda: {"mumu_manager_path": "", "adb_path": ""})

    cfg = app_paths.ensure_user_files()
    assert cfg.is_file()
    assert 'mumu_manager_path: ""' in cfg.read_text(encoding="utf-8")


def test_ensure_user_files_missing_example_is_not_fatal(frozen):
    """资源里没有示例文件时只报错，不抛异常。"""
    exe_dir, _ = frozen
    cfg = app_paths.ensure_user_files()
    assert cfg == exe_dir / "config.yaml"
    assert not cfg.exists()
