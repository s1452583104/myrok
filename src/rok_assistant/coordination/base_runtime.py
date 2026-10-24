"""模式无关的运行时骨架。

负责「一台模拟器一个 worker」这件事本身：预检、装配识别器、起
`WorkerRunner`、收工上报、停止、统计、缩略图。

**模式差异只剩下面 8 个钩子**，每个一两行：

    _instances()                     本模式跑哪些实例（必填）
    _sm_factory_for(...)             怎么给一个角色造状态机（必填）
    _pre_start(instances)            起 worker 之前的告警/校验
    _route_for(key, char)            要不要订阅 rally_launched
    _should_finish(runners)          「全都收工了」的判据
    _on_all_done(runners)            发 all_workers_done 之前的收尾
    _max_rounds()                    每 worker 的轮次上限
    _fills()                         统计条里的「填兵」列

共用的 `start` / `stop` / `stats` / `snapshot` 才是真正会漂的部分（上一轮
多模式框架评审 faebeeb 就翻在这里），所以它们**不拆**。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2

from ..core.template_registry import TemplateRegistry
from ..infra.anti_detection import HumanProfile, JitteringHandleSource
from ..infra.app_paths import resolve_asset, user_dir
from ..infra.config import RootConfig
from ..infra.logger import get_logger
from ..workers.runner import WorkerRunner
from .event_bus import EventBus
from .preflight import preflight

logger = get_logger(__name__)

_STOP_TIMEOUT = 2.0   # GUI 主线程串行 join，超时要短，避免界面长时间冻结

# GUI 缩略图的编码上限。卡片上那块只有 298×150，原帧（1920×1080）按面积
# 算要多烧 16 倍的编码、传输与解码，而它每 2s 发一轮。
_THUMB_W, _THUMB_H = 480, 270


def _shrink_for_thumbnail(frame):
    """把一帧缩到缩略图尺寸（塞进 480×270 的框，保持宽高比，不拉伸）。

    只缩不放：分辨率没调对的模拟器给了更小的画面时，放大只会糊，而卡片
    本来就画得下。返回新数组，**不动原帧**——识别链还在读它，尺寸一变
    所有 ROI 坐标全错位。
    """
    h, w = frame.shape[:2]
    scale = min(_THUMB_W / w, _THUMB_H / h, 1.0)
    if scale >= 1.0:
        return frame
    # INTER_AREA 是缩小场景的正确插值（INTER_LINEAR 缩下来会有摩尔纹）
    return cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))),
                      interpolation=cv2.INTER_AREA)


class BaseCoordinator:
    """从 RootConfig 组装运行时：每实例 1 个 HandleSource（防检测包装），
    每实例第 1 个角色 1 个 WorkerRunner。

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
        # runner_key -> rally_launched 路由处理器（stop 时统一退订）。
        # 宝石模式不用它，恒空表——留着是为了 stop/_rollback 只有一份实现。
        self._routes: dict[str, Callable] = {}
        # 自然收工的 worker 逐个上报；全部报过 → 通知 GUI 复位按钮。
        # 用户点 Stop 的路径不上报（runner 只在 stopped_reason 非 None 时发）。
        self._stopped: dict[str, str] = {}
        self._bus.subscribe("worker_finished", self._on_worker_finished)
        self._running = False

    # ---- 子类钩子 ----

    def _instances(self):
        """本模式跑哪些实例。**必填**。"""
        raise NotImplementedError

    def _sm_factory_for(self, char, handle, recognizers, profile):
        """给一个角色造状态机。**必填**（`sm_factory` 每轮重建时会再调）。"""
        raise NotImplementedError

    def _pre_start(self, instances) -> None:
        """起 worker 之前的告警/校验。默认什么都不做。"""

    def _route_for(self, key: str, char):
        """要不要给这个角色订阅 `rally_launched`。返回 handler 或 None。

        默认 None：只有寨子模式有「车头发起 → 成员填兵」这条跨实例链路，
        宝石模式一台机器一个号、各干各的。
        """
        return None

    def _should_finish(self, runners: dict) -> bool:
        """「全部收工」的判据。默认：所有 runner 都上报过。"""
        return bool(runners) and set(runners) <= set(self._stopped)

    def _on_all_done(self, runners: dict) -> None:
        """发 `all_workers_done` 之前的收尾。默认什么都不做。"""

    def _max_rounds(self) -> int:
        return self._config.app.max_rounds

    def _fills(self) -> int:
        """统计条里的「填兵」列。默认 0。"""
        return 0

    # ---- 生命周期 ----

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
        instances = self._instances()
        self._pre_start(instances)
        # 先置位再组装：若中途失败（如识别器装配失败、第 2 台 worker 起不来），
        # 必须走回滚，否则半启动的 runner 成孤儿、下次 start() 会重复拉起
        # （连接失败已由下面的预检在 worker 诞生前拦下，不走这条回滚）
        self._running = True
        try:
            # 预检先行：在任何 worker 诞生之前确认每台模拟器都截得到
            # screen_width×screen_height 的画面。放在装配识别器之前——
            # 识别器要加载 ONNX，好几秒，连不上的时候不该白花（spec §7.3）。
            handles = preflight(instances, self._config.app)
            recognizers = self._recognizers(instances)
            for inst in instances:
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

    def _fill_names(self, instances) -> list[str]:
        """配置点名的填兵目标车头名。

        只有寨子模式的 CharacterConfig 有 `fill_target_leaders`；其他模式
        `getattr` 取不到就是空表——**子类不用覆写这个方法**。
        """
        return sorted({
            t.name
            for inst in instances
            for char in inst.characters
            for t in getattr(char, "fill_target_leaders", [])
        })

    def _recognizers(self, instances):
        """装配 `{template_id: Recognizer}`：manifest + 可选 YOLO + 可选 OCR。"""
        return TemplateRegistry.load(
            self._template_dir / "manifest.yaml").build_recognizers(
            yolo_model=(resolve_asset(self._config.app.yolo_model)
                        if self._config.app.yolo_model else None),
            ocr_fallback=self._config.app.ocr_name_fallback,
            fill_names=self._fill_names(instances))

    def _spawn(self, inst, char, handle, recognizers, profile) -> None:
        key = f"{inst.id}:{char.id}"
        runner = WorkerRunner(
            instance_id=inst.id, char_id=char.id, char_name=char.name,
            sm_factory=lambda: self._sm_factory_for(char, handle, recognizers,
                                                    profile),
            handle_source=handle, event_bus=self._bus,
            human=profile,
            # 显式给失败截图目录：冻结后 CWD 可能是任意位置，runner 的
            # 默认 Path("recordings") 会把截图写到用户找不到的地方。
            screenshot_dir=user_dir() / "recordings",
            max_rounds=self._max_rounds(),
            max_consecutive_failures=self._config.app.max_consecutive_failures)
        self.runners[key] = runner
        route = self._route_for(key, char)
        if route is not None:
            self._routes[key] = route
            self._bus.subscribe("rally_launched", route)
        runner.start()

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

    def _on_worker_finished(self, payload: dict) -> None:
        """一台 worker 自然收工。满足 `_should_finish` → 收尾 → 发
        `all_workers_done`。

        只在 payload 里的 key 确实在 self.runners 里时才计入，否则
        「上一次运行遗留的迟到事件」会凑数提前复位按钮。

        本方法在发布事件的 worker 线程里被同步调用，多台 worker 近同时收工
        就会并发跑这里。**顶部拍一次 runners 快照**，后续只读快照：不这么做
        的话子类的收尾钩子会在另一线程 `runners.clear()` 时抛 RuntimeError，
        而异常被 EventBus 吞掉 → all_workers_done 永远发不出去（GUI 按钮
        不复位）。快照而非加锁：收尾钩子会 join 被停线程，若持锁等待正在
        同一处理函数里等锁的线程就死锁了。
        """
        runners = dict(self.runners)          # 快照：并发收工时另一线程可能 clear()
        key = f"{payload.get('instance_id')}:{payload.get('char_id')}"
        if key not in runners:
            return
        self._stopped[key] = payload.get("stopped_reason", "")
        if not self._should_finish(runners):
            return
        self._on_all_done(runners)
        logger.info("全部 worker 已收工：%s", self._stopped)
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

    def stats(self) -> dict:
        """运行汇总，给 GUI 统计条用。

        只读、幂等：GUI 定时器在**主线程**调它，而 worker 线程同时在写这些
        计数器。顶部 `list()` 拍一次快照——worker 自然收工时
        `_on_worker_finished` 会 `runners.clear()`，直接迭代会抛
        RuntimeError: dictionary changed size during iteration（与 `snapshot()`
        同一个坑）。普通 int 属性的读写在 CPython 下不会撕裂，最坏是某个
        数字晚一拍。

        `target` 是「设置个数」：`_max_rounds()` × 在跑的角色数。没有 runner
        时返回 0 而不是 max_rounds——界面此时该显示 0/0，不是一份假目标。
        """
        runners = list(self.runners.values())
        return {
            "ok": sum(r.rounds_ok for r in runners),
            "failed": sum(r.rounds_failed for r in runners),
            "env": sum(r.rounds_env for r in runners),
            "rounds": sum(r.rounds_done for r in runners),
            "fills": self._fills(),
            "target": self._max_rounds() * len(runners),
        }

    def snapshot(self, char_id: str) -> bytes | None:
        """该角色最近一帧的 JPEG bytes（GUI 缩略图用），无则 None。

        遍历副本：本方法在 GUI 主线程被定时器调用，而 worker 线程自然收工时
        会走 _on_worker_finished 里的 self.runners.clear()。clear() 落在迭代
        中途会抛 RuntimeError: dictionary changed size during iteration。

        **编码前先缩到缩略图尺寸**：卡片上那块只有 298×150，按面积算原帧
        （1920×1080）要多烧 16 倍的编码、传输与解码，而它每 2s 就发一轮。
        缩的是送出去给人看的那份，识别链读的仍是 `runner.last_frame` 原帧。
        """
        for runner in list(self.runners.values()):
            if runner.char_id == char_id:
                img = runner.last_frame
                if img is None:
                    return None
                ok, buf = cv2.imencode(".jpg", _shrink_for_thumbnail(img))
                return bytes(buf) if ok else None
        return None
