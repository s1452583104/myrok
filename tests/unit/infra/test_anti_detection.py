import pytest
from rok_assistant.infra.anti_detection import (
    AntiDetectionConfig, jitter_offset, jitter_delay
)

def test_default_config():
    cfg = AntiDetectionConfig()
    assert cfg.click_offset_px == 8
    assert cfg.action_delay_min == 0.1
    assert cfg.action_delay_max == 0.5
    assert cfg.state_delay_min == 0.3
    assert cfg.state_delay_max == 1.2
    assert cfg.jitter_ratio == 0.3
    assert cfg.debug_no_jitter is False

def test_jitter_offset_within_bounds():
    cfg = AntiDetectionConfig(click_offset_px=10)
    for _ in range(100):
        dx, dy = jitter_offset(100, 200, cfg)
        assert 90 <= dx <= 110
        assert 190 <= dy <= 210

def test_jitter_offset_debug_no_jitter():
    cfg = AntiDetectionConfig(debug_no_jitter=True)
    for _ in range(100):
        dx, dy = jitter_offset(100, 200, cfg)
        assert (dx, dy) == (100, 200)

def test_jitter_delay_within_range():
    cfg = AntiDetectionConfig(jitter_ratio=0.3)
    for _ in range(100):
        d = jitter_delay(1.0, cfg)
        assert 0.7 <= d <= 1.3

def test_jitter_delay_zero_base():
    cfg = AntiDetectionConfig()
    d = jitter_delay(0.0, cfg)
    assert d == 0.0

def test_jitter_delay_debug_no_jitter():
    cfg = AntiDetectionConfig(debug_no_jitter=True)
    assert jitter_delay(1.5, cfg) == 1.5
