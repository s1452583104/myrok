from __future__ import annotations
import threading
import time
from pathlib import Path
from typing import Callable

import cv2

from ..core.template_registry import TemplateRegistry
from ..core.handle_source import create_handle_source
from ..infra.app_paths import resolve_asset, user_dir
from ..infra.config import RootConfig, RoleEnum, find_level_collisions
from ..infra.anti_detection import HumanProfile, JitteringHandleSource
from ..infra.logger import get_logger
from ..workers.factory import create_state_machine
from ..workers.runner import WorkerRunner
from .action_ledger import ActionLedger
from .event_bus import EventBus

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
        # 只告警不拦启动：同等级且互为填兵目标的两号可能搜到同一寨子，
        # 撞车只会白烧一次搜索（已降级不计失败），不该阻断运行
        for msg in find_level_collisions(self._config):
            logger.warning("%s", msg)
        # 先置位再组装：若中途失败（如第 2 个实例连不上），必须走回滚，
        # 否则半启动的 runner 成孤儿、下次 start() 会在同一批模拟器上重复拉起
        self._running = True
        try:
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
                try:
                    handle = create_handle_source(
                        mumu_index=inst.mumu_index,
                        mumu_manager_path=self._config.app.mumu_manager_path,
                        adb_address=inst.adb_address,
                        adb_path=self._config.app.adb_path,
                        window_title_pattern=inst.window_title_pattern)
                except Exception as e:
                    # **报错必须点名是哪一台。** 2026-10-05 用户报「只连上一个，
                    # 另一个成员实例报错」——配了两台时，裸异常里只有
                    # 「模拟器 1 可能没有启动」这种编号，界面又只弹一个泛泛的
                    # 「启动失败」，用户根本不知道说的是哪台、该去开哪个。
                    #
                    # 这段**整个落在日志之外**：worker 还没起来，运行日志里一个字
                    # 都没有（用户的 logs/ 里那次就是 0 字节），事后查不出来。
                    # 所以这里既点名又写日志，别指望下一个人能从别处还原现场。
                    where = f"MuMu 编号 {inst.mumu_index}" if inst.mumu_index is not None \
                        else (f"adb {inst.adb_address}" if inst.adb_address
                              else f"窗口 {inst.window_title_pattern!r}")
                    logger.error("模拟器「%s」（%s，%s）连接失败：%s",
                                 inst.name, inst.id, where, e)
                    raise RuntimeError(
                        f"模拟器「{inst.name}」（{inst.id}，{where}）连不上：{e}") from e
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
        self._stopped.clear()
        self._running = False

    def _on_worker_finished(self, payload: dict) -> None:
        """一台 worker 自然收工。全部收工 → 发 all_workers_done（spec §6.2）。

        只在 payload 里的 key 确实在 self.runners 里时才计入，否则
        「上一次运行遗留的迟到事件」会凑数提前复位按钮。
        """
        key = f"{payload.get('instance_id')}:{payload.get('char_id')}"
        if key not in self.runners:
            return
        self._stopped[key] = payload.get("stopped_reason", "")
        if not set(self.runners) <= set(self._stopped):
            return
        logger.info("全部 worker 已收工：%s", self._stopped)
        self._bus.publish("all_workers_done", {"reasons": dict(self._stopped)})
        self._running = False

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
        """该角色最近一帧的 JPEG bytes（GUI 缩略图用），无则 None。"""
        for runner in self.runners.values():
            if runner.char_id == char_id:
                img = runner.last_frame
                if img is None:
                    return None
                ok, buf = cv2.imencode(".jpg", img)
                return bytes(buf) if ok else None
        return None
