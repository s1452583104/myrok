import random
import time
from dataclasses import dataclass

@dataclass(frozen=True)
class AntiDetectionConfig:
    click_offset_px: int = 8
    action_delay_min: float = 0.1
    action_delay_max: float = 0.5
    state_delay_min: float = 0.3
    state_delay_max: float = 1.2
    jitter_ratio: float = 0.3
    debug_no_jitter: bool = False

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

class JitteringHandleSource:
    """Wraps a HandleSource: random click offset + random delay before each click.

    With debug_no_jitter=True, jitter_offset returns the original coords and
    random_action_delay returns its midpoint, so this wrapper degrades to a
    pass-through.
    """

    def __init__(self, inner, cfg: AntiDetectionConfig):
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
