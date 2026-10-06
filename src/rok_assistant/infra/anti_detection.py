import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rok_assistant.core.handle_source import HandleSource

@dataclass(frozen=True)
class AntiDetectionConfig:
    click_offset_px: int = 8
    action_delay_min: float = 0.1
    action_delay_max: float = 0.5
    state_delay_min: float = 0.8
    state_delay_max: float = 1.2
    jitter_ratio: float = 0.3
    debug_no_jitter: bool = False
    delay_shape: str = "beta"          # beta | uniform（uniform = 回退旧行为）
    burst_prob: float = 0.3            # 走「连点」短间隔的概率
    burst_scale: float = 0.25          # 连点间隔 = min + (max-min)*U(0, scale)
    anchor_sigma: dict = field(default_factory=dict)   # 模板 id -> σ 覆盖
    member_response_delay_min: float = 0.0   # 默认关闭：见 Global Constraints
    member_response_delay_max: float = 0.0

    def random_action_delay(self) -> float:
        if self.debug_no_jitter:
            return (self.action_delay_min + self.action_delay_max) / 2
        return random.uniform(self.action_delay_min, self.action_delay_max)

    def random_state_delay(self) -> float:
        if self.debug_no_jitter:
            return (self.state_delay_min + self.state_delay_max) / 2
        return random.uniform(self.state_delay_min, self.state_delay_max)

def jitter_offset(x: int, y: int, cfg: AntiDetectionConfig) -> tuple:
    if cfg.debug_no_jitter:
        return x, y
    return (x + random.randint(-cfg.click_offset_px, cfg.click_offset_px),
            y + random.randint(-cfg.click_offset_px, cfg.click_offset_px))

def jitter_delay(base: float, cfg: AntiDetectionConfig) -> float:
    if base <= 0:
        return 0.0
    if cfg.debug_no_jitter:
        return base
    jitter = base * cfg.jitter_ratio
    return max(0.0, base + random.uniform(-jitter, jitter))

# Beta(2, 5)：偏短、带长尾。真人点击是突发式的——短间隔为主，偶尔拖长，
# 而不是均匀铺满整个区间。形状硬编码，不额外暴露 a/b 旋钮。
_BETA_A, _BETA_B = 2.0, 5.0
# 高斯散布裁剪到 ±3σ：截尾避免偶发的大偏移把点击甩出目标。
_SIGMA_CLIP = 3.0


class HumanProfile:
    """一处集中全部「像人」的随机化：延迟分布、坐标散布、动作节奏。

    注入 `random.Random` 后完全可复现（测试用）。`debug_no_jitter=True`
    时**所有**方法返回确定性值 —— 这是调试逃生口，也是既有测试的依赖。
    """

    def __init__(self, cfg: "AntiDetectionConfig",
                 rng: random.Random | None = None):
        self._cfg = cfg
        self._rng = rng if rng is not None else random.Random()

    # ---- 点击前延迟 ----
    def click_delay(self) -> float:
        cfg = self._cfg
        lo, hi = cfg.action_delay_min, cfg.action_delay_max
        if cfg.debug_no_jitter:
            return (lo + hi) / 2
        if hi <= lo:
            return lo
        if cfg.burst_prob > 0 and self._rng.random() < cfg.burst_prob:
            return lo + (hi - lo) * self._rng.uniform(0.0, cfg.burst_scale)
        if cfg.delay_shape == "uniform":
            return self._rng.uniform(lo, hi)
        return lo + (hi - lo) * self._rng.betavariate(_BETA_A, _BETA_B)

    # ---- 坐标散布 ----
    def disperse(self, x: int, y: int, anchor: str | None = None) -> tuple[int, int]:
        cfg = self._cfg
        if cfg.debug_no_jitter:
            return int(x), int(y)
        sigma = cfg.click_offset_px
        if anchor is not None:
            sigma = cfg.anchor_sigma.get(anchor, sigma)
        if sigma <= 0:
            return int(x), int(y)
        limit = _SIGMA_CLIP * sigma
        dx = max(-limit, min(limit, self._rng.gauss(0.0, sigma)))
        dy = max(-limit, min(limit, self._rng.gauss(0.0, sigma)))
        return int(round(x + dx)), int(round(y + dy))

    # ---- 动作节奏 ----
    def poll_interval(self) -> float:
        """轮询间隔。精确恒定的轮询间隔是签名级的机器特征。"""
        cfg = self._cfg
        lo, hi = cfg.state_delay_min, cfg.state_delay_max
        if cfg.debug_no_jitter:
            return (lo + hi) / 2
        if hi <= lo:
            return lo
        return self._rng.uniform(lo, hi)

    def jitter(self, base: float) -> float:
        """给硬编码的固定 sleep 加乘性抖动（0 保持 0）。"""
        if base <= 0:
            return 0.0
        if self._cfg.debug_no_jitter:
            return base
        r = self._cfg.jitter_ratio
        return max(0.0, base + self._rng.uniform(-base * r, base * r))

    def retry_attempts(self, base: int) -> int:
        """重试次数 ±1 —— 每轮的重试次数也是路径形状的一部分。"""
        if self._cfg.debug_no_jitter:
            return base
        return max(1, base + self._rng.randint(-1, 1))

    def member_response_delay(self) -> float:
        """成员号收到集结事件后延迟多久响应，破两号 lockstep 关联。"""
        cfg = self._cfg
        if cfg.debug_no_jitter:
            return (cfg.member_response_delay_min
                    + cfg.member_response_delay_max) / 2
        if cfg.member_response_delay_max <= cfg.member_response_delay_min:
            return cfg.member_response_delay_min
        return self._rng.uniform(cfg.member_response_delay_min,
                                 cfg.member_response_delay_max)

class JitteringHandleSource:
    """Wraps a HandleSource: random click offset + random delay before each click.

    With debug_no_jitter=True, coordinates and delays become deterministic
    (offset 0, delay = midpoint of min/max), but clicks are still delayed.
    """

    def __init__(self, inner: "HandleSource", cfg: AntiDetectionConfig):
        self._inner = inner
        self._cfg = cfg

    def capture(self):
        return self._inner.capture()

    def click(self, x: int, y: int) -> None:
        time.sleep(self._cfg.random_action_delay())
        jx, jy = jitter_offset(int(x), int(y), self._cfg)
        self._inner.click(jx, jy)

    def swipe(self, *args, **kwargs):
        return self._inner.swipe(*args, **kwargs)

    def is_alive(self) -> bool:
        return self._inner.is_alive()
