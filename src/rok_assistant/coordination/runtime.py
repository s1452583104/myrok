from __future__ import annotations
import threading
import time
from pathlib import Path
from typing import Callable

import cv2

from ..core.template_registry import TemplateRegistry
from ..infra.app_paths import resolve_asset, user_dir
from ..infra.config import RootConfig, RoleEnum, find_level_collisions
from ..infra.anti_detection import HumanProfile, JitteringHandleSource
from ..infra.logger import get_logger
from ..workers.factory import create_state_machine
from ..workers.runner import WorkerRunner
from .action_ledger import ActionLedger
from .event_bus import EventBus
from .preflight import preflight

logger = get_logger(__name__)

_STOP_TIMEOUT = 2.0   # GUI 主线程串行 join，超时要短，避免界面长时间冻结


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


class RuntimeCoordinator:
    """从 RootConfig 组装运行时：每实例 1 个 HandleSource（防检测包装），
    每实例第 1 个角色 1 个 WorkerRunner。member 角色订阅 rally_launched 路由。

    v1 限制：每实例只跑第 1 个角色（多角色切换属 v2）。
    """

    def __init__(self, config: RootConfig, event_bus: EventBus | None = None,
                 template_dir: Path | None = None):
        self._config = config
        self._bus = event_bus or EventBus()
        # 默认用配置里的模板目录；测试可注入临时目录。配置里写的是相对路径，
        # 按 resource_dir() 解开——冻结后它是 _internal，不是 CWD。
        self._template_dir = Path(template_dir) if template_dir \
            else resolve_asset(self._config.app.template_dir)
        self.runners: dict[str, WorkerRunner] = {}
        # runner_key -> rally_launched 路由处理器（stop 时统一退订）
        self._routes: dict[str, Callable] = {}
        # 集结事件登记簿：跨 SM 重建存活，either 车头让车/拒绝降级决策用
        self._rally_tracker = RallyEventTracker(self._bus)
        # 进程级动作账本：跨 SM 重建存活，集结门槛的 L0 判据与「谁在外」
        # 归因都读它
        self.ledger = ActionLedger()
        # 自然收工的 worker 逐个上报；全部报过 → 通知 GUI 复位按钮。
        # 用户点 Stop 的路径不上报（runner 只在 stopped_reason 非 None 时发）。
        self._stopped: dict[str, str] = {}
        self._bus.subscribe("worker_finished", self._on_worker_finished)
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        # worker_finished 的订阅与「运行」同寿：先撤后挂，保证恰好一份
        # （__init__ 已挂一份；自然收工 / stop / 回滚 都会撤掉）。unsubscribe
        # 幂等，重复撤订无副作用。
        self._bus.unsubscribe("worker_finished", self._on_worker_finished)
        self._bus.subscribe("worker_finished", self._on_worker_finished)
        # 复用同一 coordinator（自然收工后没 stop 就再 start）时，runners 里
        # 留的是已死线程的引用、_stopped 已满——不清的话第二轮第一台 worker
        # 一收工就会满足「全部收工」提前触发，把运行中的 Stop 按钮禁掉。
        self.runners.clear()
        self._stopped.clear()
        # 只告警不拦启动：同等级且互为填兵目标的两号可能搜到同一寨子，
        # 撞车只会白烧一次搜索（已降级不计失败），不该阻断运行
        for msg in find_level_collisions(self._config):
            logger.warning("%s", msg)
        # 先置位再组装：若中途失败（如识别器装配失败、第 2 台 worker 起不来），
        # 必须走回滚，否则半启动的 runner 成孤儿、下次 start() 会重复拉起
        # （连接失败已由上面的预检在 worker 诞生前拦下，不再走这条回滚）
        self._running = True
        try:
            # 预检先行：在任何 worker 诞生之前确认每台模拟器都截得到
            # screen_width×screen_height 的画面。放在装配识别器之前——
            # 识别器要加载 ONNX，好几秒，连不上的时候不该白花（spec §7.3）。
            handles = preflight(self._config.instances, self._config.app)
            # 配置点名的车头交给 registry 兜底装配：manifest 是随包静态资源，
            # 用户改 fill_target_leaders 换车头时不会自动多出 fill_<名字> 条目
            fill_names = sorted({
                t.name
                for inst in self._config.instances
                for char in inst.characters
                for t in char.fill_target_leaders
            })
            recognizers = TemplateRegistry.load(
                self._template_dir / "manifest.yaml").build_recognizers(
                yolo_model=(resolve_asset(self._config.app.yolo_model)
                            if self._config.app.yolo_model else None),
                ocr_fallback=self._config.app.ocr_name_fallback,
                fill_names=fill_names)
            for inst in self._config.instances:
                # 预检已经建好并验过帧，这里直接复用——见 preflight 的 docstring
                handle = handles[inst.id]
                profile = HumanProfile(self._config.app.anti_detection)
                handle = JitteringHandleSource(handle, profile)
                for char in inst.characters[:1]:
                    self._spawn(inst, char, handle, recognizers, profile)
        except Exception:
            logger.exception("运行时启动失败，回滚已创建的 worker")
            self._rollback()
            raise

    def _rollback(self) -> None:
        for key, runner in self.runners.items():
            runner.stop(timeout=_STOP_TIMEOUT)
            self._warn_if_alive(key, runner)
        self.runners.clear()
        for handler in self._routes.values():
            self._bus.unsubscribe("rally_launched", handler)
        self._routes.clear()
        self._bus.unsubscribe("worker_finished", self._on_worker_finished)
        self._stopped.clear()
        self._running = False

    def _role_of(self, key: str) -> RoleEnum | None:
        """runner key（"实例id:角色id"）→ 配置里的分工。查不到返回 None。"""
        for inst in self._config.instances:
            for char in inst.characters:
                if f"{inst.id}:{char.id}" == key:
                    return char.role
        return None

    def _leaders_done(self) -> bool:
        """所有 leader/either 是否都已上报收工。

        配置层保证至少 1 个 leader/either（config.py 的 _cross_checks），
        所以这个集合非空，收工出口一定可达。
        """
        leaders = [k for k in self.runners
                   if self._role_of(k) in (RoleEnum.LEADER, RoleEnum.EITHER)]
        return bool(leaders) and set(leaders) <= set(self._stopped)

    def _stop_members(self) -> None:
        """车头全收工 → 停掉还在跑的成员。

        波次模式的成员永不进终态（不记轮次，见 member_sm.is_terminal），
        只能由这里停。已自然收工过的成员跳过（避免重复 stop）。
        """
        for key in list(self.runners):
            if self._role_of(key) != RoleEnum.MEMBER or key in self._stopped:
                continue
            self.runners[key].stop(timeout=_STOP_TIMEOUT)
            self._warn_if_alive(key, self.runners[key])
            self._stopped[key] = "车头已全部收工，协调器停止成员"

    def _on_worker_finished(self, payload: dict) -> None:
        """一台 worker 自然收工。**所有车头收工** → 停成员 → 发
        all_workers_done（spec §2.4）。

        收工判据从「全部 runner 上报」改成「全部 leader/either 上报」：
        波次模式下的成员不记轮次、永不进终态，旧判据永远不成立。成员由此
        改为被协调器停，它的收工理由也由协调器代记。

        只在 payload 里的 key 确实在 self.runners 里时才计入，否则
        「上一次运行遗留的迟到事件」会凑数提前复位按钮。
        """
        key = f"{payload.get('instance_id')}:{payload.get('char_id')}"
        if key not in self.runners:
            return
        self._stopped[key] = payload.get("stopped_reason", "")
        if not self._leaders_done():
            return
        self._stop_members()
        logger.info("全部车头已收工：%s", self._stopped)
        self._bus.publish("all_workers_done", {"reasons": dict(self._stopped)})
        self._running = False
        # 收工即退订：订阅与运行同寿。否则旧 coordinator 仍挂在同一根 bus 上，
        # 下一次运行中途会被它凑满再发一次 all_workers_done（把 Stop 禁掉）。
        # EventBus.publish 遍历的是 handler 列表副本，循环内退订安全。
        self._bus.unsubscribe("worker_finished", self._on_worker_finished)
        # 清掉陈旧状态：自然收工后 runners 里是已死线程的引用、_stopped 已满，
        # 留着会让复用时下一轮第一次上报就提前凑满。
        self._stopped.clear()
        self.runners.clear()

    def _spawn(self, inst, char, handle, recognizers, profile) -> None:
        key = f"{inst.id}:{char.id}"
        runner = WorkerRunner(
            instance_id=inst.id, char_id=char.id, char_name=char.name,
            sm_factory=lambda: create_state_machine(char, handle, recognizers,
                                                    self._bus, self._rally_tracker,
                                                    ledger=self.ledger,
                                                    human=profile),
            handle_source=handle, event_bus=self._bus,
            human=profile,
            # 显式给失败截图目录：冻结后 CWD 可能是任意位置，runner 的
            # 默认 Path("recordings") 会把截图写到用户找不到的地方。
            screenshot_dir=user_dir() / "recordings",
            max_rounds=self._config.app.max_rounds,
            max_consecutive_failures=self._config.app.max_consecutive_failures)
        self.runners[key] = runner
        if char.role == RoleEnum.MEMBER:
            self._routes[key] = self._make_router(key)
            self._bus.subscribe("rally_launched", self._routes[key])
        runner.start()

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

    def stop(self) -> None:
        leftover: dict[str, WorkerRunner] = {}
        for key, runner in self.runners.items():
            runner.stop(timeout=_STOP_TIMEOUT)
            if self._warn_if_alive(key, runner):
                # 超时未停的守护线程不能丢引用：留在 runners 里，
                # 用户再点一次 Stop（或进程退出前）仍有句柄可控可查
                leftover[key] = runner
        for handler in self._routes.values():
            self._bus.unsubscribe("rally_launched", handler)
        self._routes.clear()
        self._bus.unsubscribe("worker_finished", self._on_worker_finished)
        self.runners = leftover
        self._stopped.clear()
        self._running = False

    @staticmethod
    def _warn_if_alive(key: str, runner) -> bool:
        """WorkerRunner 未暴露线程属性，这里读私有 _thread 做超时判断。"""
        thread = getattr(runner, "_thread", None)
        if thread is not None and thread.is_alive():
            logger.warning("worker %s 在 %.1fs 内未停止，守护线程仍在运行；"
                           "引用已保留，可再次 stop", key, _STOP_TIMEOUT)
            return True
        return False

    def snapshot(self, char_id: str) -> bytes | None:
        """该角色最近一帧的 JPEG bytes（GUI 缩略图用），无则 None。

        遍历副本：本方法在 GUI 主线程被定时器调用，而 worker 线程自然收工时
        会走 _on_worker_finished 里的 self.runners.clear()。clear() 落在迭代
        中途会抛 RuntimeError: dictionary changed size during iteration。
        """
        for runner in list(self.runners.values()):
            if runner.char_id == char_id:
                img = runner.last_frame
                if img is None:
                    return None
                ok, buf = cv2.imencode(".jpg", img)
                return bytes(buf) if ok else None
        return None
