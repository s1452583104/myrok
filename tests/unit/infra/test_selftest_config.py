from rok_assistant.infra import selftest
from rok_assistant.infra.config import LEGACY_FLAT_INSTANCES_HINT


def test_legacy_hint_flags_flat_and_half_migrated():
    """老格式与半迁移（顶层 instances 与 zhaiduo 都在）都要接住，给同一条可操作提示。

    判据必须与 config.py 校验器一致：顶层出现 instances 即命中——否则半迁移配置
    被 config.py 拒绝、selftest 却给出泛泛诊断（F 之后两者的不一致）。
    """
    assert selftest._legacy_flat_instances_hint(
        {"instances": [{"id": "m0"}]}) == LEGACY_FLAT_INSTANCES_HINT
    assert selftest._legacy_flat_instances_hint(
        {"instances": [], "zhaiduo": {"instances": []}}) == LEGACY_FLAT_INSTANCES_HINT


def test_legacy_hint_ignores_normal_config():
    """正常配置（只有 zhaiduo）不误报，既有诊断保持原样。"""
    assert selftest._legacy_flat_instances_hint(
        {"zhaiduo": {"instances": []}}) is None
    assert selftest._legacy_flat_instances_hint({"app": {}}) is None
    assert selftest._legacy_flat_instances_hint({}) is None
    assert selftest._legacy_flat_instances_hint(None) is None
