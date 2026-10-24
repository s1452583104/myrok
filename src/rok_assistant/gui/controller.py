from __future__ import annotations
from pathlib import Path

import yaml
from PyQt6.QtCore import QObject, pyqtSignal

from ..coordination.event_bus import EventBus
from ..coordination.gem_runtime import GemCoordinator
from ..coordination.quiz_runtime import QuizCoordinator
from ..coordination.runtime import RuntimeCoordinator
from ..infra.app_paths import config_path as default_config_path
from ..infra.config import AppMode, IMPLEMENTED_MODES, MODE_LABELS, RootConfig
from ..infra.licensing import guard
from ..infra.logger import get_logger

logger = get_logger(__name__)

# 未跑过任何一轮时的统计读数。字段与 RuntimeCoordinator.stats() 一一对应
# （界面统计条按名字取值，两处改名要一起改）。
_EMPTY_STATS = {"ok": 0, "failed": 0, "env": 0, "rounds": 0, "fills": 0,
                "target": 0}


class GuiController(QObject):
    """GUI 与运行时之间的桥。worker 线程经 EventBus 发布状态，
    这里转成 Qt 信号（跨线程安全，Qt 自动排队到主线程）。"""

    status_changed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    run_finished = pyqtSignal(dict)

    def __init__(self, config_path: Path | None = None,
                 coordinator_factory=RuntimeCoordinator,
                 gem_coordinator_factory=GemCoordinator,
                 quiz_coordinator_factory=QuizCoordinator, parent=None):
        super().__init__(parent)
        self.config_path = Path(config_path) if config_path else default_config_path()
        self._coordinator_factory = coordinator_factory
        # 按模式分开注入，而不是收成一个 `{AppMode: factory}` 字典参数：
        # 既有测试传的都是「一个假协调器」，合成字典要它们全部改签名。
        self._gem_coordinator_factory = gem_coordinator_factory
        self._quiz_coordinator_factory = quiz_coordinator_factory
        self._coordinator = None
        # 停止后 coordinator 就被丢了，最后一次读数留在这里继续给界面显示
        self._last_stats: dict = dict(_EMPTY_STATS)
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

    def card_view(self) -> str:
        """角色卡片的显示模式（`"text"` / `"image"`）。

        配置没加载时给默认值：这是纯观感开关，读不出来不该拦着开窗。
        """
        if self._config is None:
            return "image"
        return self._config.app.card_view

    def set_card_view(self, mode: str) -> bool:
        """切换显示模式并落盘（**只动 config.yaml 里那一行**）。

        成功返回 True。失败返回 False 且不改内存配置——调用方保留本次会话
        内的切换、提示「未能写入」即可。为了一个观感开关把界面卡住，比
        不保存糟得多。
        """
        from ..infra.config import set_card_view as write_card_view
        if not write_card_view(self.config_path, mode):
            return False
        if self._config is not None:
            # 内存一起改：只写盘的话，界面显示的和配置里写的会短暂两回事
            self._config.app.card_view = mode
        return True

    def characters(self, mode: AppMode = AppMode.ZHAIDUO) -> list[dict]:
        """本模式的角色清单（卡片按它建）。

        `role` 用 getattr 兜底：宝石/答题的角色模型**没有** role 字段
        （两个模式都是一个实例一个号，既不开车也不填兵），直接取会
        AttributeError。回落值**按模式给**：宝石给 `"gem"` → 卡片标题
        「采集号（宝石采集）」，答题给 `"quiz"` → 「答题号（自动答题）」。
        写死成同一个词会让另一个模式的卡片显示成错的玩法。
        """
        if self._config is None:
            self.load_config()
        out = []
        if self._config:
            for inst in self._config.instances_for(mode):
                for char in inst.characters:
                    role = getattr(char, "role", None)
                    out.append({"instance_id": inst.id, "char_id": char.id,
                                "char_name": char.name,
                                "role": role.value if role is not None
                                else mode.value})
        return out

    # ---- 运行 ----
    def start(self, mode: AppMode = AppMode.ZHAIDUO) -> bool:
        """成功返回 True，捕获到异常返回 False（错误经 error_occurred 弹出）。

        返回值是给界面用的：失败时界面**不能**切到「运行中」态——启动预检
        被拒（本分支的主场景）时异常在这里被吞、方法正常返回，界面若照旧
        置位就会谎报运行中，Stop 可点而实际什么都没跑。

        mode 是模式进入运行时的**唯一入口**：五行的边界检查换掉「某个
        setEnabled 漏了就直接跑起来」。能不能跑由 IMPLEMENTED_MODES 裁决，
        跑什么由 _factory_for(mode) 决定。
        """
        if mode not in IMPLEMENTED_MODES:
            self.error_occurred.emit(
                f"{MODE_LABELS[mode]}尚未开放，无法启动任务")
            return False
        # 纵深防御：GUI 的 _on_start 已经拦过一道，这里再拦一道，
        # 覆盖不经过界面的调用方（预检脚本、将来的 CLI）。
        # 放在配置闸门**之前**：与 _on_start 的「先授权后配置」同序，
        # 且授权过期是最外层、最该先告知用户的阻塞原因。
        # 读状态本身也要兜：这些非 GUI 调用方要的是 False + error_occurred，
        # 不是一个未处理异常（docstring 承诺的「捕获到异常返回 False」）。
        try:
            status = guard.current_guard().status()
        except Exception:                      # noqa: BLE001 - 见上
            logger.exception("读取授权状态失败")
            self.error_occurred.emit("授权状态读取失败，无法启动")
            return False
        if not status.allows_run:
            self.error_occurred.emit(f"授权已到期：{status.label()}")
            return False
        if self._config is None and not self.load_config():
            return False
        # 两道闸门都过了才算「真的开跑」：被授权/配置拒掉时保持上一轮读数，
        # 用户看到的是「没跑起来」而不是「战绩被清零了」。
        self._last_stats = dict(_EMPTY_STATS)
        try:
            self._coordinator = self._factory_for(mode)(self._config,
                                                        event_bus=self._bus)
            self._coordinator.start()
            return True
        except Exception as e:
            logger.exception("启动失败")
            self.error_occurred.emit(f"启动失败：{e}")
            return False

    def _factory_for(self, mode: AppMode):
        """模式 → 协调器工厂。**这是模式分派唯一的一处**。

        放在这里而不是字典常量里：`coordinator_factory` 是构造参数（测试
        注入假协调器），字典常量就只能是模块级的、吃不到注入值。
        """
        if mode == AppMode.GEM:
            return self._gem_coordinator_factory
        if mode == AppMode.QUIZ:
            return self._quiz_coordinator_factory
        return self._coordinator_factory

    def stop(self) -> None:
        if self._coordinator is not None:
            # 先留存读数再丢 coordinator：用户点停止正是为了看这一轮的战绩，
            # 丢完再读只能读到 0。
            self._last_stats = self._coordinator.stats()
            self._coordinator.stop()
            self._coordinator = None

    def snapshot(self, char_id: str) -> bytes | None:
        return self._coordinator.snapshot(char_id) if self._coordinator else None

    def stats(self) -> dict:
        """运行汇总，给界面统计条用。

        运行中现读 coordinator；未运行（含启动中、已停止）返回上一次读数。
        返回副本，调用方改它不影响内部状态。
        """
        if self._coordinator is not None:
            return self._coordinator.stats()
        return dict(self._last_stats)

    # ---- 内部 ----
    def _on_bus_status(self, payload: dict) -> None:
        self.status_changed.emit(payload)   # worker 线程 emit -> Qt 排队到主线程

    def _on_bus_all_done(self, payload: dict) -> None:
        """全部 worker 自然收工 → 通知界面复位（spec §6.2）。"""
        self.run_finished.emit(payload)
