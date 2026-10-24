from pathlib import Path
import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import load_config, RootConfig

FIX = Path(__file__).parent.parent.parent / "fixtures"


def test_load_valid_config():
    cfg = load_config(FIX / "config_valid.yaml")
    assert isinstance(cfg, RootConfig)
    assert len(cfg.zhaiduo.instances) == 1
    assert cfg.zhaiduo.instances[0].id == "inst0"
    assert cfg.zhaiduo.instances[0].name == "阑珊号"
    assert cfg.app.mumu_manager_path.endswith("MuMuManager.exe")


def test_load_no_leader_raises():
    with pytest.raises(ValidationError, match="整个配置至少需要"):
        load_config(FIX / "config_no_leader.yaml")


def test_load_invalid_level_raises():
    with pytest.raises(ValidationError, match="target_levels"):
        load_config(FIX / "config_invalid_level.yaml")


def test_load_rejects_half_migrated_config(tmp_path):
    """顶层 instances 与 zhaiduo 同时存在（半迁移）也必须报错。

    旧守卫要求「zhaiduo 缺席」才拦，于是这种半迁移配置会被 pydantic 静默丢弃
    顶层那段、加载成功——对「硬报错、不迁移」的设计来说，静默丢数据比报错更糟。
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "instances:\n"
        "  - id: mumu0\n"
        "    characters: []\n"
        "zhaiduo:\n"
        "  instances:\n"
        "    - id: inst0\n"
        "      name: \"号\"\n"
        "      mumu_index: 0\n"
        "      characters:\n"
        "        - id: leader1\n"
        "          name: \"Hero\"\n"
        "          role: leader\n"
        "          target_levels: [8]\n"
        "          march_preset: 1\n"
        "          march_troop_types: [infantry]\n",
        encoding="utf-8")
    with pytest.raises(ValidationError, match="配置格式已更新"):
        load_config(cfg)


def test_example_config_loads_and_has_gem_section():
    """config.example.yaml 是随包分发的模板，它必须能加载。

    用户首启时程序就复制它生成 config.yaml；示例配错 = 所有人开箱即坏。
    """
    from pathlib import Path
    from rok_assistant.infra.config import AppMode, load_config
    root = Path(__file__).resolve().parents[3]
    cfg = load_config(root / "config.example.yaml")
    assert cfg.gem.queue_limit >= 1
    # 示例里宝石段默认不给实例（用户按需填），但字段得在
    assert isinstance(cfg.instances_for(AppMode.GEM), list)


def test_example_config_has_quiz_section():
    """示例的答题段必须真的被读进来，不能因拼错键静默回落默认值。

    示例里大多数值与小节标的默认值相同，所以**光看解析结果抓不到拼错的键**
    （拼错 → 该键不走校验 → 拿到的还是默认值）。因此先断言原始 YAML 里
    这几个键确实存在，再断言解析后的值——两层一起才锁得住示例块。
    """
    import yaml
    from rok_assistant.infra.config import AppMode, load_config
    root = Path(__file__).resolve().parents[3]
    raw = yaml.safe_load((root / "config.example.yaml").read_text(encoding="utf-8"))
    assert {"max_rounds", "round_cooldown_min",
            "verify_delay", "llm"} <= set(raw["quiz"])
    assert "enabled" in raw["quiz"]["llm"]

    cfg = load_config(root / "config.example.yaml")
    assert cfg.quiz.max_rounds == 3
    assert cfg.quiz.round_cooldown_min == 10
    assert cfg.quiz.verify_delay == 1.2
    assert cfg.quiz.llm.enabled is False
    assert isinstance(cfg.instances_for(AppMode.QUIZ), list)
