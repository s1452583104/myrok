from __future__ import annotations
from pathlib import Path

import yaml
from PyQt6.QtCore import QObject, pyqtSignal

from ..coordination.event_bus import EventBus
from ..coordination.runtime import RuntimeCoordinator
from ..infra.app_paths import config_path as default_config_path
from ..infra.config import RootConfig
from ..infra.licensing import guard
from ..infra.logger import get_logger

logger = get_logger(__name__)


class GuiController(QObject):
    """GUI 与运行时之间的桥。worker 线程经 EventBus 发布状态，
    这里转成 Qt 信号（跨线程安全，Qt 自动排队到主线程）。"""

    status_changed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    run_finished = pyqtSignal(dict)

    def __init__(self, config_path: Path | None = None,
                 coordinator_factory=RuntimeCoordinator, parent=None):
        super().__init__(parent)
        self.config_path = Path(config_path) if config_path else default_config_path()
        self._coordinator_factory = coordinator_factory
        self._coordinator = None
        self._config: RootConfig | None = None
        self._bus = EventBus()
        self._bus.subscribe("status_update", self._on_bus_status)
        self._bus.subscribe("all_workers_done", self._on_bus_all_done)

    # ---- 配置 ----
    @property
    def config_loaded(self) -> bool:
        return self._config is not None

    def load_config(self) -> bool:
        try:
            self._config = RootConfig.model_validate(
                yaml.safe_load(self.config_path.read_text(encoding="utf-8")))
            return True
        except Exception as e:
            logger.exception("配置加载失败")
            self.error_occurred.emit(f"配置加载失败：{e}")
            return False

    def reload_config(self) -> None:
        """强制从磁盘重读 config.yaml（GUI 配置保存后刷新用）。

        与 load_config 的静默信号路径不同：校验/读盘失败直接抛出，
        由调用方决定如何呈现 —— 避免把陈旧的内存配置当新配置用。
        """
        self._config = RootConfig.model_validate(
            yaml.safe_load(self.config_path.read_text(encoding="utf-8")))

    def characters(self) -> list[dict]:
        if self._config is None:
            self.load_config()
        out = []
        if self._config:
            for inst in self._config.instances:
                for char in inst.characters:
                    out.append({"instance_id": inst.id, "char_id": char.id,
                                "char_name": char.name, "role": char.role.value})
        return out

    # ---- 运行 ----
    def start(self) -> bool:
        """成功返回 True，捕获到异常返回 False（错误经 error_occurred 弹出）。

        返回值是给界面用的：失败时界面**不能**切到「运行中」态——启动预检
        被拒（本分支的主场景）时异常在这里被吞、方法正常返回，界面若照旧
        置位就会谎报运行中，Stop 可点而实际什么都没跑。
        """
        # 纵深防御：GUI 的 _on_start 已经拦过一道，这里再拦一道，
        # 覆盖不经过界面的调用方（预检脚本、将来的 CLI）。
        # 放在配置闸门**之前**：与 _on_start 的「先授权后配置」同序，
        # 且授权过期是最外层、最该先告知用户的阻塞原因。
        status = guard.current_guard().status()
        if not status.allows_run:
            self.error_occurred.emit(f"授权已到期：{status.label()}")
            return False
        if self._config is None and not self.load_config():
            return False
        try:
            self._coordinator = self._coordinator_factory(self._config, event_bus=self._bus)
            self._coordinator.start()
            return True
        except Exception as e:
            logger.exception("启动失败")
            self.error_occurred.emit(f"启动失败：{e}")
            return False

    def stop(self) -> None:
        if self._coordinator is not None:
            self._coordinator.stop()
            self._coordinator = None

    def snapshot(self, char_id: str) -> bytes | None:
        return self._coordinator.snapshot(char_id) if self._coordinator else None

    # ---- 内部 ----
    def _on_bus_status(self, payload: dict) -> None:
        self.status_changed.emit(payload)   # worker 线程 emit -> Qt 排队到主线程

    def _on_bus_all_done(self, payload: dict) -> None:
        """全部 worker 自然收工 → 通知界面复位（spec §6.2）。"""
        self.run_finished.emit(payload)
