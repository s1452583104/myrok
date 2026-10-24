"""宝石模式的协调器。

与寨子模式的 RuntimeCoordinator 相比，这里**没有**：事件总线跨实例路由、
动作账本、集结事件登记簿、车头/成员分工、集结前置门槛。宝石模式一台
模拟器一个号、各干各的，队列与宝石都是本机的事实（spec §2）。

共用的骨架（预检 / 装配识别器 / 起 worker / 收工上报 / 停止 / 统计 /
缩略图）全在 `BaseCoordinator`。
"""
from __future__ import annotations

from ..infra.config import AppMode
from ..workers.factory import create_gem_state_machine
from .base_runtime import BaseCoordinator


class GemCoordinator(BaseCoordinator):
    """每实例 1 个 HandleSource（防检测包装），每实例第 1 个角色 1 个
    WorkerRunner，各自扫图 / 采集，互不通信。"""

    def _instances(self):
        return self._config.instances_for(AppMode.GEM)

    def _sm_factory_for(self, char, handle, recognizers, profile):
        gem = self._config.gem
        return create_gem_state_machine(
            char, handle, recognizers,
            queue_limit=gem.queue_limit, scan_rings=gem.scan_rings,
            scan_drag_px=gem.scan_drag_px, scan_drag_ms=gem.scan_drag_ms,
            idle_wait_min=gem.idle_wait_min, idle_wait_max=gem.idle_wait_max,
            human=profile)

    def _max_rounds(self) -> int:
        """`gem.max_rounds`，**不是** `app.max_rounds`：宝石模式跑得慢
        （一轮含 20~30 分钟等待），轮次上限是它自己的旋钮（spec §9）。"""
        return self._config.gem.max_rounds
