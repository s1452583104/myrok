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
    assert cfg.state_delay_min == 0.8
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
    src = JitteringHandleSource(inner, HumanProfile(cfg, rng=random.Random(0)))
    src.click(100, 200)
    inner.click.assert_called_once_with(100, 200)  # offset 0 -> exact coords
    assert src.is_alive() is inner.is_alive.return_value
    assert src.capture() is inner.capture.return_value
    src.swipe(1, 2, 3, 4, duration_ms=5)
    args = inner.swipe.call_args.args
    assert args[:4] == (1, 2, 3, 4)          # offset 0 -> 端点不变
    assert 3 <= args[4] <= 7                 # 5 ± 30%

def test_jittering_handle_source_offset_bounds():
    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=8, action_delay_min=0.0,
                              action_delay_max=0.0, debug_no_jitter=False)
    src = JitteringHandleSource(inner, HumanProfile(cfg, rng=random.Random(7)))
    for _ in range(50):
        src.click(100, 100)
        jx, jy = inner.click.call_args.args[:2]
        assert 76 <= jx <= 124 and 76 <= jy <= 124      # ±3σ

def test_jittering_handle_source_sleeps_before_click(monkeypatch):
    import rok_assistant.infra.anti_detection as ad_mod
    calls = []
    monkeypatch.setattr(ad_mod.time, "sleep", lambda s: calls.append(("sleep", s)))
    inner = MagicMock()
    inner.click.side_effect = lambda x, y: calls.append(("click", x, y))
    cfg = AntiDetectionConfig(click_offset_px=0, action_delay_min=0.01,
                              action_delay_max=0.02, debug_no_jitter=False)
    src = JitteringHandleSource(inner, HumanProfile(cfg, rng=random.Random(0)))
    src.click(100, 200)
    assert len(calls) == 2
    assert calls[0][0] == "sleep"
    assert 0.01 <= calls[0][1] <= 0.02
    assert calls[1] == ("click", 100, 200)

def test_jittering_handle_source_debug_no_jitter_exact_coords():
    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=8, action_delay_min=0.0,
                              action_delay_max=0.0, debug_no_jitter=True)
    src = JitteringHandleSource(inner, HumanProfile(cfg, rng=random.Random(0)))
    src.click(100, 200)
    inner.click.assert_called_once_with(100, 200)

import random

from rok_assistant.infra.anti_detection import HumanProfile


def _profile(**kw):
    return HumanProfile(AntiDetectionConfig(**kw), rng=random.Random(1234))


def test_click_delay_within_bounds():
    p = _profile(action_delay_min=1.0, action_delay_max=2.0, burst_prob=0.0)
    for _ in range(200):
        assert 1.0 <= p.click_delay() <= 2.0


def test_click_delay_is_not_uniform():
    """beta 形状应当偏短：均值明显低于区间中点。"""
    p = _profile(action_delay_min=0.0, action_delay_max=1.0, burst_prob=0.0)
    samples = [p.click_delay() for _ in range(400)]
    mean = sum(samples) / len(samples)
    assert mean < 0.40            # Beta(2,5) 均值 = 2/7 ≈ 0.286
    assert mean > 0.15            # 但也不能退化到 0


def test_click_delay_uniform_shape_is_centered():
    """delay_shape=uniform 时均值回到区间中点附近（回退路径）。"""
    p = _profile(action_delay_min=0.0, action_delay_max=1.0,
                 burst_prob=0.0, delay_shape="uniform")
    samples = [p.click_delay() for _ in range(400)]
    mean = sum(samples) / len(samples)
    assert 0.40 < mean < 0.60


def test_uniform_shape_short_circuits_burst():
    """delay_shape=uniform 是独立回滚杠杆：burst_prob 非零也不得走突发分支。

    判据：uniform 路径每次只消耗一个随机数（`rng.uniform(lo, hi)`），而突发
    分支会**先**多抽一次 `rng.random()` 再抽样。用两枚同种子的 rng——一枚驱动
    `click_delay()`，另一枚独立生成 `uniform(lo, hi)` 流——只要有一次进过突发
    分支（或 beta 分支），两条流就会错位，逐位比较必然不等。
    """
    cfg = AntiDetectionConfig(action_delay_min=1.0, action_delay_max=2.0,
                              burst_prob=0.5, burst_scale=0.25,
                              delay_shape="uniform")
    p = HumanProfile(cfg, rng=random.Random(2026))
    ref = random.Random(2026)
    expected = [ref.uniform(1.0, 2.0) for _ in range(200)]
    got = [p.click_delay() for _ in range(200)]
    # 值域佐证：突发路径永远 ≤ lo + burst_scale*(hi-lo) = 1.25。
    assert max(got) > 1.5
    # 逐位判据：整条流与纯 uniform 流完全相同 → 无任何一个样本来自突发路径。
    assert got == expected


def test_burst_prob_one_always_short():
    p = _profile(action_delay_min=1.0, action_delay_max=2.0,
                 burst_prob=1.0, burst_scale=0.25)
    for _ in range(200):
        assert 1.0 <= p.click_delay() <= 1.25


def test_click_delay_debug_no_jitter_is_midpoint():
    p = _profile(action_delay_min=1.0, action_delay_max=3.0,
                 debug_no_jitter=True)
    assert p.click_delay() == 2.0


def test_disperse_is_gaussian_around_target():
    p = _profile(click_offset_px=10)
    xs = [p.disperse(500, 500)[0] - 500 for _ in range(500)]
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / len(xs)
    assert abs(mean) < 2.0
    assert 8.0 < var ** 0.5 < 12.0      # 标准差 ≈ σ = 10


def test_disperse_clipped_at_three_sigma():
    p = _profile(click_offset_px=10)
    for _ in range(500):
        x, y = p.disperse(500, 500)
        assert abs(x - 500) <= 30 and abs(y - 500) <= 30


def test_disperse_anchor_sigma_overrides_default():
    p = _profile(click_offset_px=20, anchor_sigma={"preset_slot": 2})
    xs = [p.disperse(500, 500, "preset_slot")[0] - 500 for _ in range(300)]
    assert all(abs(x) <= 6 for x in xs)          # 3 * σ(2)


def test_disperse_unknown_anchor_falls_back_to_default():
    p = _profile(click_offset_px=10, anchor_sigma={"preset_slot": 2})
    xs = [p.disperse(500, 500, "march_btn")[0] - 500 for _ in range(300)]
    assert max(abs(x) for x in xs) > 6           # 用的是 σ=10 而不是 2


def test_disperse_debug_no_jitter_is_exact():
    p = _profile(click_offset_px=10, debug_no_jitter=True)
    assert p.disperse(500, 500) == (500, 500)
    assert p.disperse(500, 500, "march_btn") == (500, 500)


def test_poll_interval_within_state_delay_bounds():
    p = _profile(state_delay_min=0.5, state_delay_max=1.5)
    samples = [p.poll_interval() for _ in range(200)]
    assert all(0.5 <= s <= 1.5 for s in samples)
    assert len(set(samples)) > 50        # 不是恒定值


def test_poll_interval_debug_is_midpoint():
    p = _profile(state_delay_min=0.8, state_delay_max=1.2,
                 debug_no_jitter=True)
    assert p.poll_interval() == 1.0      # 与改动前的固定 1.0s 一致


def test_jitter_scales_base():
    p = _profile(jitter_ratio=0.3)
    for _ in range(200):
        assert 0.7 <= p.jitter(1.0) <= 1.3


def test_jitter_zero_base_is_zero():
    assert _profile().jitter(0.0) == 0.0


def test_jitter_debug_is_identity():
    p = _profile(debug_no_jitter=True)
    assert p.jitter(1.5) == 1.5


def test_retry_attempts_varies_but_stays_positive():
    p = _profile()
    seen = {p.retry_attempts(3) for _ in range(200)}
    assert seen <= {2, 3, 4}
    assert len(seen) == 3
    assert all(p.retry_attempts(1) >= 1 for _ in range(50))


def test_retry_attempts_debug_is_identity():
    assert _profile(debug_no_jitter=True).retry_attempts(3) == 3


def test_member_response_delay_default_is_zero():
    """默认关闭：不能凭空给成员号加一分钟延迟。"""
    assert _profile().member_response_delay() == 0.0


def test_member_response_delay_within_bounds():
    p = _profile(member_response_delay_min=10.0, member_response_delay_max=60.0)
    samples = [p.member_response_delay() for _ in range(200)]
    assert all(10.0 <= s <= 60.0 for s in samples)


def test_member_response_delay_debug_is_midpoint():
    p = _profile(member_response_delay_min=10.0, member_response_delay_max=60.0,
                 debug_no_jitter=True)
    assert p.member_response_delay() == 35.0


def test_jittering_handle_source_passes_anchor_to_profile():
    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=20,
                              anchor_sigma={"preset_slot": 0},
                              action_delay_min=0.0, action_delay_max=0.0)
    src = JitteringHandleSource(inner, HumanProfile(cfg, rng=random.Random(3)))
    for _ in range(30):
        src.click(100, 200, anchor="preset_slot")
        assert inner.click.call_args.args[:2] == (100, 200)   # σ=0 -> 精确


def test_jittering_handle_source_does_not_forward_anchor():
    """anchor 只用于选 σ，不往下传 —— MockHandleSource.clicks 仍是 (x, y)。"""
    inner = MagicMock()
    cfg = AntiDetectionConfig(click_offset_px=0, action_delay_min=0.0,
                              action_delay_max=0.0)
    src = JitteringHandleSource(inner, HumanProfile(cfg, rng=random.Random(1)))
    src.click(100, 200, anchor="march_btn")
    inner.click.assert_called_once_with(100, 200)


def test_mock_handle_source_accepts_anchor_and_records_xy():
    from rok_assistant.core.handle_source import MockHandleSource
    import numpy as np
    h = MockHandleSource(np.zeros((2, 2, 3), np.uint8))
    h.click(1, 2, anchor="march_btn")
    assert h.clicks == [(1, 2)]
