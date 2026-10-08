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
    # 连点段（同一控件上的连续点击，如等级 +/-）的间隔。人手调数字盘是连着
    # 点好几下，不该套用跨动作延迟；而突发分支在 action_delay_min=3.1 下
    # 算出来只有 3.1–3.7s，等于没有突发（spec §5.2）。
    # 下限 0.35 沿用原 leader_sm._LEVEL_CLICK_PACE 的取值：那是**低于** 2026-09-11
    # 实测安全值（0.4s 间隔连点 19 次零丢失）的取值，故真机需确认不丢点击。
    rapid_click_min: float = 0.35
    rapid_click_max: float = 0.8
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
    def _shaped(self, lo: float, hi: float) -> float:
        """同一套形状换一个区间（顺序即 spec §7 的回滚杠杆，别重排）。"""
        if hi <= lo:
            return lo
        if self._cfg.delay_shape == "uniform":
            return self._rng.uniform(lo, hi)
        if self._cfg.burst_prob > 0 and self._rng.random() < self._cfg.burst_prob:
            return lo + (hi - lo) * self._rng.uniform(0.0, self._cfg.burst_scale)
        return lo + (hi - lo) * self._rng.betavariate(_BETA_A, _BETA_B)

    def click_delay(self) -> float:
        cfg = self._cfg
        if cfg.debug_no_jitter:
            return (cfg.action_delay_min + cfg.action_delay_max) / 2
        return self._shaped(cfg.action_delay_min, cfg.action_delay_max)

    def rapid_click_delay(self) -> float:
        """连点段的间隔（见 AntiDetectionConfig.rapid_click_min）。"""
        cfg = self._cfg
        if cfg.debug_no_jitter:
            return (cfg.rapid_click_min + cfg.rapid_click_max) / 2
        return self._shaped(cfg.rapid_click_min, cfg.rapid_click_max)

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
        """成员号收到集结事件后延迟多久响应，破两号 lockstep 关联。

        线程注意：`on_rally_launched` 在**车头** worker 线程上同步触发（EventBus
        是同步的），会调到这里读 `self._rng`；而成员号自己的线程同时在用同一
        `_rng` 抽点击 / 轮询样本。`random.Random` 未声明线程安全——最坏只是两次
        抽取交错、随机流略乱，不会崩。影响不值得加锁，刻意不加。
        """
        cfg = self._cfg
        if cfg.debug_no_jitter:
            return (cfg.member_response_delay_min
                    + cfg.member_response_delay_max) / 2
        if cfg.member_response_delay_max <= cfg.member_response_delay_min:
            return cfg.member_response_delay_min
        return self._rng.uniform(cfg.member_response_delay_min,
                                 cfg.member_response_delay_max)

class JitteringHandleSource:
    """Wraps a HandleSource: 每次点击前随机延迟 + 坐标散布（含 swipe）。

    `anchor` 只用于挑选散布 σ（见 HumanProfile.disperse），**不往下传** ——
    下游 MockHandleSource.clicks 仍记 (x, y)。
    """

    def __init__(self, inner: "HandleSource", profile: HumanProfile):
        self._inner = inner
        self._profile = profile

    def capture(self):
        return self._inner.capture()

    def click(self, x: int, y: int, anchor: str | None = None,
              rapid: bool = False) -> None:
        delay = (self._profile.rapid_click_delay() if rapid
                 else self._profile.click_delay())
        time.sleep(delay)
        jx, jy = self._profile.disperse(int(x), int(y), anchor)
        # `anchor` 到此为止（既有约定，见类 docstring）；`rapid` 同理——
        # 两者都只对本层有意义，不往下传
        self._inner.click(jx, jy)

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        # 原实现是直通转发，零抖动 —— 滑动端点与时长都该抖
        time.sleep(self._profile.click_delay())
        jx1, jy1 = self._profile.disperse(int(x1), int(y1), "swipe_start")
        jx2, jy2 = self._profile.disperse(int(x2), int(y2), "swipe_end")
        self._inner.swipe(jx1, jy1, jx2, jy2,
                          int(self._profile.jitter(duration_ms)))

    def is_alive(self) -> bool:
        return self._inner.is_alive()
