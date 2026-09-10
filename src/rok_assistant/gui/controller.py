from __future__ import annotations
from pathlib import Path

import yaml
from PyQt6.QtCore import QObject, pyqtSignal

from ..coordination.event_bus import EventBus
from ..coordination.runtime import RuntimeCoordinator
from ..infra.config import RootConfig
from ..infra.logger import get_logger

logger = get_logger(__name__)


class GuiController(QObject):
    """GUI 与运行时之间的桥。worker 线程经 EventBus 发布状态，
    这里转成 Qt 信号（跨线程安全，Qt 自动排队到主线程）。"""

    status_changed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, config_path: Path | None = None,
                 coordinator_factory=RuntimeCoordinator, parent=None):
        super().__init__(parent)
        self.config_path = Path(config_path) if config_path else Path("config.yaml")
        self._coordinator_factory = coordinator_factory
        self._coordinator = None
        self._config: RootConfig | None = None
        self._bus = EventBus()
        self._bus.subscribe("status_update", self._on_bus_status)

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
    def start(self) -> None:
        if self._config is None and not self.load_config():
            return
        try:
            self._coordinator = self._coordinator_factory(self._config, event_bus=self._bus)
            self._coordinator.start()
        except Exception as e:
            logger.exception("启动失败")
            self.error_occurred.emit(f"启动失败：{e}")

    def stop(self) -> None:
        if self._coordinator is not None:
            self._coordinator.stop()
            self._coordinator = None

    def snapshot(self, char_id: str) -> bytes | None:
        return self._coordinator.snapshot(char_id) if self._coordinator else None

    # ---- 内部 ----
    def _on_bus_status(self, payload: dict) -> None:
        self.status_changed.emit(payload)   # worker 线程 emit -> Qt 排队到主线程
