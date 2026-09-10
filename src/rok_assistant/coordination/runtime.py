from __future__ import annotations
from pathlib import Path
from typing import Callable

import cv2

from ..core.template_registry import TemplateRegistry
from ..core.handle_source import create_handle_source
from ..infra.config import RootConfig, RoleEnum
from ..infra.anti_detection import JitteringHandleSource
from ..infra.logger import get_logger
from ..workers.factory import create_state_machine
from ..workers.runner import WorkerRunner
from .event_bus import EventBus

logger = get_logger(__name__)

_STOP_TIMEOUT = 2.0   # GUI 主线程串行 join，超时要短，避免界面长时间冻结


class RuntimeCoordinator:
    """从 RootConfig 组装运行时：每实例 1 个 HandleSource（防检测包装），
    每实例第 1 个角色 1 个 WorkerRunner。member 角色订阅 rally_launched 路由。

    v1 限制：每实例只跑第 1 个角色（多角色切换属 v2）。
    """

    def __init__(self, config: RootConfig, event_bus: EventBus | None = None,
                 template_dir: Path | None = None):
        self._config = config
        self._bus = event_bus or EventBus()
        # 默认用配置里的模板目录；测试可注入临时目录
        self._template_dir = Path(template_dir) if template_dir \
            else Path(self._config.app.template_dir)
        self.runners: dict[str, WorkerRunner] = {}
        # runner_key -> rally_launched 路由处理器（stop 时统一退订）
        self._routes: dict[str, Callable] = {}
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        # 先置位再组装：若中途失败（如第 2 个实例连不上），必须走回滚，
        # 否则半启动的 runner 成孤儿、下次 start() 会在同一批模拟器上重复拉起
        self._running = True
        try:
            recognizers = TemplateRegistry.load(
                self._template_dir / "manifest.yaml").build_recognizers()
            for inst in self._config.instances:
                handle = create_handle_source(
                    mumu_index=inst.mumu_index,
                    mumu_manager_path=self._config.app.mumu_manager_path,
                    adb_address=inst.adb_address,
                    adb_path=self._config.app.adb_path,
                    window_title_pattern=inst.window_title_pattern)
                handle = JitteringHandleSource(handle, self._config.app.anti_detection)
                for char in inst.characters[:1]:
                    self._spawn(inst, char, handle, recognizers)
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
        self._running = False

    def _spawn(self, inst, char, handle, recognizers) -> None:
        key = f"{inst.id}:{char.id}"
        runner = WorkerRunner(
            instance_id=inst.id, char_id=char.id, char_name=char.name,
            sm_factory=lambda: create_state_machine(char, handle, recognizers, self._bus),
            handle_source=handle, event_bus=self._bus)
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
