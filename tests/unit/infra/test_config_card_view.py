"""`app.card_view`（文字/图文模式偏好）的模型与落盘。

落盘走**单键行内改写**而不是 `yaml.safe_dump` 整份重写：config.yaml 是用户
手改的文件，里面有一整块解释 YOLO 权重取舍的注释，整份重写会静默清掉它
（配置对话框保存时就是这个行为，那是历史包袱，不该扩大到「切一下显示模式
就删注释」）。
"""
import yaml

from rok_assistant.infra.config import (
    AppConfig, RootConfig, load_config, set_card_view,
)

CONFIG_TEXT = """\
# 顶部注释：解释 YOLO 权重为什么切 v9
app:
  screen_width: 1920
  # 权重取舍：见 docs/HISTORY.md
  yolo_model: models/detect.onnx
  max_rounds: 10
  anti_detection:
    click_offset_px: 8
zhaiduo:
  instances:
    - id: mumu0
      mumu_index: 0
      characters:
        - id: c0
          name: 车头
          role: leader
          target_levels: [5]
          march_preset: 1
          march_troop_types: [cavalry]
"""


def _write(tmp_path, text=CONFIG_TEXT):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_card_view_defaults_to_image():
    """没配这个字段的老配置照常加载，默认图文模式（行为与改动前一致）。"""
    assert AppConfig().card_view == "image"
    cfg = RootConfig.model_validate(yaml.safe_load(CONFIG_TEXT))
    assert cfg.app.card_view == "image"


def test_card_view_accepts_text():
    cfg = RootConfig.model_validate(
        yaml.safe_load(CONFIG_TEXT.replace(
            "  max_rounds: 10", "  max_rounds: 10\n  card_view: text")))
    assert cfg.app.card_view == "text"


def test_card_view_rejects_unknown_value():
    """拼错的值要在加载时就报错，不能静默退化成图文模式。"""
    import pytest
    with pytest.raises(Exception):
        RootConfig.model_validate(
            yaml.safe_load(CONFIG_TEXT.replace(
                "  max_rounds: 10", "  max_rounds: 10\n  card_view: txt")))


def test_set_card_view_rewrites_in_place_and_keeps_comments(tmp_path):
    """已存在该键时原地替换，其余内容一字不动。"""
    p = _write(tmp_path, CONFIG_TEXT.replace(
        "  max_rounds: 10", "  max_rounds: 10\n  card_view: image"))

    assert set_card_view(p, "text") is True

    text = p.read_text(encoding="utf-8")
    assert "# 顶部注释：解释 YOLO 权重为什么切 v9" in text
    assert "# 权重取舍：见 docs/HISTORY.md" in text
    assert "card_view: text" in text
    assert "card_view: image" not in text
    assert load_config(p).app.card_view == "text"      # 真的能读回来
    assert text.count("card_view") == 1                # 没有写重复


def test_set_card_view_inserts_when_key_absent(tmp_path):
    """配置里还没有这个键时插进 app 段，缩进对齐同段其他键。"""
    p = _write(tmp_path)

    assert set_card_view(p, "text") is True

    text = p.read_text(encoding="utf-8")
    assert "# 顶部注释：解释 YOLO 权重为什么切 v9" in text
    assert load_config(p).app.card_view == "text"
    assert text.count("card_view") == 1
    # 插在 app 段里，而不是文件开头或顶层
    app_body = text.split("app:", 1)[1].split("zhaiduo:", 1)[0]
    assert "card_view: text" in app_body


def test_set_card_view_leaves_other_sections_alone(tmp_path):
    """只认 app 段自己的那个键。

    顶层若有个同名键（旧配置残留 / 用户手写），改 app 的不能顺手把它也改了
    —— 那是「看着对、改错了地方」。
    """
    p = _write(tmp_path, CONFIG_TEXT + "card_view: image\n")

    assert set_card_view(p, "text") is True

    text = p.read_text(encoding="utf-8")
    assert text.count("card_view") == 2                 # 顶层那个还在
    assert text.rstrip().endswith("card_view: image")   # 且没被改成 text
    assert load_config(p).app.card_view == "text"


def test_set_card_view_refuses_broken_yaml_without_touching_file(tmp_path):
    """文件本身解析不了时不写盘 —— 改坏用户的配置比不保存严重得多。"""
    broken = "app:\n  screen_width: [unclosed\n"
    p = _write(tmp_path, broken)

    assert set_card_view(p, "text") is False
    assert p.read_text(encoding="utf-8") == broken
