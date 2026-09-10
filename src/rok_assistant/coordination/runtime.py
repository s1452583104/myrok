from __future__ import annotations
from pathlib import Path

import cv2

from ..core.template_registry import TemplateRegistry
from ..core.handle_source import create_handle_source
from ..infra.config import RootConfig, RoleEnum
from ..infra.anti_detection import JitteringHandleSource
from ..workers.factory import create_state_machine
from ..workers.runner import WorkerRunner
from .event_bus import EventBus


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
        self._running = False

    def start(self) -> None:
        if self._running:
            return
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
        self._running = True

    def _spawn(self, inst, char, handle, recognizers) -> None:
        runner = WorkerRunner(
            instance_id=inst.id, char_id=char.id, char_name=char.name,
            sm_factory=lambda: create_state_machine(char, handle, recognizers, self._bus),
            handle_source=handle, event_bus=self._bus)
        self.runners[f"{inst.id}:{char.id}"] = runner
        if char.role == RoleEnum.MEMBER:
            self._bus.subscribe("rally_launched", self._make_router(f"{inst.id}:{char.id}"))
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
        for runner in self.runners.values():
            runner.stop()
        self.runners.clear()
        self._running = False

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
