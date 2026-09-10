import pytest
from unittest.mock import MagicMock
from rok_assistant.infra.anti_detection import (
    AntiDetectionConfig, jitter_offset, jitter_delay, JitteringHandleSource
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

def test_jittering_handle_source_delegates_and_jitters():
    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=0, action_delay_min=0.0,
                              action_delay_max=0.0, debug_no_jitter=False)
    src = JitteringHandleSource(inner, cfg)
    src.click(100, 200)
    inner.click.assert_called_once_with(100, 200)  # offset 0 -> exact coords
    assert src.is_alive() is inner.is_alive.return_value
    assert src.capture() is inner.capture.return_value
    src.swipe(1, 2, 3, 4, duration_ms=5)
    inner.swipe.assert_called_once_with(1, 2, 3, 4, duration_ms=5)

def test_jittering_handle_source_offset_bounds():
    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=8, action_delay_min=0.0,
                              action_delay_max=0.0, debug_no_jitter=False)
    src = JitteringHandleSource(inner, cfg)
    for _ in range(50):
        src.click(100, 100)
        jx, jy = inner.click.call_args.args
        assert 92 <= jx <= 108 and 92 <= jy <= 108
