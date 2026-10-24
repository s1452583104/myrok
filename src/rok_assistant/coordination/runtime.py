from __future__ import annotations
import threading
import time
from pathlib import Path

from ..infra.config import AppMode, RootConfig, RoleEnum, find_level_collisions
from ..infra.logger import get_logger
from ..workers.factory import create_state_machine
from .action_ledger import ActionLedger
from .base_runtime import _STOP_TIMEOUT, BaseCoordinator
from .event_bus import EventBus
# TemplateRegistry 在本模块里**没有调用点**，import 它是为了保住
# `RT.TemplateRegistry` 这个属性名：tests/integration/test_runtime_preflight.py
# 用 `monkeypatch.setattr(RT.TemplateRegistry, "load", _fake_load)` 替换装配
# 识别器那一步。装配逻辑搬去了 base_runtime，但两处引用的是**同一个类对象**，
# 所以打在这个类上的补丁照样生效——前提是这个属性还在。删掉这行会让那条
# 集成测试在 import 阶段就 AttributeError。
from ..core.template_registry import TemplateRegistry   # noqa: F401

logger = get_logger(__name__)


class RallyEventTracker:
    """进程级集结事件登记簿（2026-09-18 run11 实锤修复件）：

    LeaderStateMachine / EitherStateMachine 每轮重建（runner 冷却后
    sm_factory 造新实例），事件状态不能挂在 SM 上。登记簿挂在共享
    EventBus 上、跨重建存活，按 char_id 记录最近一次 rally_launched /
    rally_skipped，供 either 车头三处决策查询：

    - 让车门槛：窗内对方已发起集结 → 本轮不开，直接转填兵
      （同一城寨同时只能一个联盟集结，后发者被游戏静默拒绝）
    - rally_rejected 降级：自己被拒且窗内对方确有集结 → 竞态输家
      轮空不计失败
    - 成员提前收尾：对方跳过开集结（转填我方）→ 无集结可填，不白烧
      6 分钟轮询

    两号 worker 线程并发读写，锁保护。时间戳在此统一打（发布方不带）。
    """

    def __init__(self, event_bus: EventBus):
        self._lock = threading.Lock()
        self._launches: dict[str, dict] = {}   # char_id -> 最近 launch payload
        self._skips: dict[str, dict] = {}      # char_id -> 最近 skip payload
        event_bus.subscribe("rally_launched", self._on_event)
        event_bus.subscribe("rally_skipped", self._on_event)

    def _on_event(self, payload: dict) -> None:
        entry = dict(payload)
        entry["ts"] = time.time()
        with self._lock:
            if "rally_id" in entry:
                self._launches[entry.get("char_id", "?")] = entry
            else:
                self._skips[entry.get("char_id", "?")] = entry

    def last_foreign_launch(self, char_id: str, max_age: float) -> dict | None:
        return self._foreign(self._launches, char_id, max_age)

    def last_foreign_skip(self, char_id: str, max_age: float) -> dict | None:
        return self._foreign(self._skips, char_id, max_age)

    def _foreign(self, table: dict, char_id: str, max_age: float) -> dict | None:
        with self._lock:
            now = time.time()
            for cid, payload in table.items():
                if cid != char_id and now - payload.get("ts", 0.0) <= max_age:
                    return dict(payload)
        return None


class RuntimeCoordinator(BaseCoordinator):
    """寨多多模式的协调器：每实例 1 个 HandleSource（防检测包装），
    每实例第 1 个角色 1 个 WorkerRunner。member 角色订阅 rally_launched 路由。

    模式专属件全在这里：集结事件登记簿、动作账本、车头/成员的分工与收工
    判据。**共用的骨架在 `BaseCoordinator`**。

    v1 限制：每实例只跑第 1 个角色（多角色切换属 v2）。
    """

    def __init__(self, config: RootConfig, event_bus: EventBus | None = None,
                 template_dir: Path | None = None):
        super().__init__(config, event_bus=event_bus, template_dir=template_dir)
        # 集结事件登记簿：跨 SM 重建存活，either 车头让车/拒绝降级决策用
        self._rally_tracker = RallyEventTracker(self._bus)
        # 进程级动作账本：跨 SM 重建存活，集结门槛的 L0 判据与「谁在外」
        # 归因都读它
        self.ledger = ActionLedger()

    # ---- 钩子实现 ----

    def _instances(self):
        return self._config.instances_for(AppMode.ZHAIDUO)

    def _pre_start(self, instances) -> None:
        # 只告警不拦启动：同等级且互为填兵目标的两号可能搜到同一寨子，
        # 撞车只会白烧一次搜索（已降级不计失败），不该阻断运行
        for msg in find_level_collisions(instances):
            logger.warning("%s", msg)

    def _sm_factory_for(self, char, handle, recognizers, profile):
        return create_state_machine(char, handle, recognizers, self._bus,
                                    self._rally_tracker, ledger=self.ledger,
                                    human=profile)

    def _route_for(self, key: str, char):
        if char.role != RoleEnum.MEMBER:
            return None
        return self._make_router(key)

    def _should_finish(self, runners: dict) -> bool:
        """收工判据是「全部 leader/either 上报」而不是「全部 runner 上报」：
        波次模式下的成员不记轮次、永不进终态，旧判据永远不成立。成员由此
        改为被协调器停，它的收工理由也由协调器代记。
        """
        return self._leaders_done(runners)

    def _on_all_done(self, runners: dict) -> None:
        self._stop_members(runners)
        # 基类（base_runtime._on_worker_finished）已经打过一行 info
        # 「全部 worker 已收工」；这里只是措辞更具体（车头 vs worker），
        # 同一时刻打两行 info 对现场没价值，降到 debug 备查。
        logger.debug("全部车头已收工：%s", self._stopped)

    def _fills(self) -> int:
        return self.ledger.total_fills()

    # ---- 寨子专属的私有件（原样搬，一字不改）----

    def _role_of(self, key: str) -> RoleEnum | None:
        """runner key（"实例id:角色id"）→ 配置里的分工。查不到返回 None。"""
        for inst in self._config.instances_for(AppMode.ZHAIDUO):
            for char in inst.characters:
                if f"{inst.id}:{char.id}" == key:
                    return char.role
        return None

    def _leaders_done(self, runners: dict) -> bool:
        """所有 leader/either 是否都已上报收工。

        配置层保证至少 1 个 leader/either（config.py 的 _cross_checks），
        所以这个集合非空，收工出口一定可达。

        `runners` 是调用方在 `_on_worker_finished` 顶部拍的**快照**：本方法在
        worker 线程里跑，另一台 worker 同时收工可能已在 `runners.clear()`，直接
        迭代 self.runners 会抛「dictionary changed size during iteration」。
        """
        leaders = [k for k in runners
                   if self._role_of(k) in (RoleEnum.LEADER, RoleEnum.EITHER)]
        return bool(leaders) and set(leaders) <= set(self._stopped)

    def _stop_members(self, runners: dict) -> None:
        """车头全收工 → 停掉还在跑的成员。

        波次模式的成员永不进终态（不记轮次，见 member_sm.is_terminal），
        只能由这里停。已自然收工过的成员跳过（避免重复 stop）。

        `runners` 同样用快照：若直接 `self.runners[key]` 取，另一线程已
        `clear()` 时会 KeyError，异常被 EventBus 吞掉 → all_workers_done
        永远发不出去（GUI 按钮不复位）。快照里的引用仍指向真实 runner，
        停线程照常。
        """
        for key, runner in runners.items():
            if self._role_of(key) != RoleEnum.MEMBER or key in self._stopped:
                continue
            runner.stop(timeout=_STOP_TIMEOUT)
            self._warn_if_alive(key, runner)
            self._stopped[key] = "车头已全部收工，协调器停止成员"

    def _make_router(self, runner_key: str):
        def route(event: dict) -> None:
            runner = self.runners.get(runner_key)
            if runner is None:
                return
            sm = runner.sm
            # 冷却重建后的新 SM 从 IDLE 等事件；已在跑的（非等待态）不吃新事件。
            # 已知 v1 窗口：事件若恰好在冷却重建期间到达会丢失（可接受的 v1 简化）。
            if sm.current in ("IDLE", "WAIT_LAUNCH_EVENT"):
                sm.on_rally_launched(event)
        return route
