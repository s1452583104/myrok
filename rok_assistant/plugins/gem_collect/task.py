"""宝石采集任务模块.

实现宝石采集的完整自动化流程:
检测 -> 点击宝石矿 -> 检测采集按钮 -> 点击采集 -> 选择军队 -> 确认

核心类:
- GemCollectState: 采集状态枚举
- GemCollectionTask: 宝石采集任务
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.yolo_detector import YOLODetector
from coordination.event_bus import EventBus, TaskCompletedEvent, TaskFailedEvent
from infrastructure.logger import get_logger
from models.config import GemCollectConfig
from models.detection import DetectionElement, DetectionResult


class GemCollectState(Enum):
    """宝石采集状态机."""

    IDLE = "idle"  # 空闲
    SEARCHING = "searching"  # 搜索宝石矿
    TARGET_SELECTED = "target_selected"  # 已选择目标
    CLICKING_MINE = "clicking_mine"  # 点击宝石矿
    WAITING_UI = "waiting_ui"  # 等待UI加载
    CLICKING_GATHER = "clicking_gather"  # 点击采集按钮
    SELECTING_ARMY = "selecting_army"  # 选择军队
    CONFIRMING = "confirming"  # 确认采集
    GATHERING = "gathering"  # 采集中
    COMPLETED = "completed"  # 采集完成
    FAILED = "failed"  # 失败


@dataclass
class GemCollectionTask:
    """宝石采集任务.

    职责:
    - 执行宝石采集的完整流程
    - 状态管理和转换
    - 错误处理和重试
    - 结果报告

    流程:
    1. 截取游戏画面
    2. YOLO检测宝石矿
    3. 判断宝石矿等级
    4. 点击宝石矿
    5. 等待UI加载
    6. 检测并点击采集按钮
    7. 选择军队数量和类型
    8. 确认采集
    9. 等待采集完成

    使用示例:
        task = GemCollectionTask(
            task_id="gem_001",
            detector=yolo_detector,
            game_controller=controller,
            event_bus=bus,
            config=gem_config,
        )
        result = task.execute()
    """

    task_id: str
    detector: YOLODetector
    game_controller: Any  # GameController
    event_bus: EventBus
    config: GemCollectConfig
    capture_func: Callable = None  # 截图函数
    state: GemCollectState = GemCollectState.IDLE
    retry_count: int = 0
    max_retries: int = 3
    last_error: str = ""
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    # MVP宝石矿检测的类别名称
    GEM_MINE_CLASS = "gem_mine"
    GATHER_BTN_CLASS = "gather_btn"
    CONFIRM_BTN_CLASS = "confirm_btn"

    def execute(self) -> Dict[str, Any]:
        """执行宝石采集任务.

        Returns:
            任务结果字典
        """
        self.start_time = time.time()
        self.state = GemCollectState.SEARCHING
        self._log("Starting gem collection task")

        try:
            # Step 1: 检测宝石矿
            result = self._detect_gem_mines()
            if result is None or result.element_count == 0:
                self._fail("No gem mines detected")
                return self._build_result()

            # Step 2: 筛选符合等级的宝石矿
            suitable_mines = self._filter_mines_by_level(result)
            if not suitable_mines:
                self._fail(
                    f"No gem mines >= level {self.config.min_level} found"
                )
                return self._build_result()

            # Step 3: 选择最优宝石矿（最近/最高等级）
            target = self._select_best_mine(suitable_mines)
            self.state = GemCollectState.TARGET_SELECTED
            self._log(f"Selected target: {target.class_name} "
                      f"(conf={target.confidence:.2f})")

            # Step 4: 点击宝石矿
            if not self._click_mine(target):
                self._fail("Failed to click gem mine")
                return self._build_result()

            self.state = GemCollectState.WAITING_UI
            self._wait_for_ui()

            # Step 5: 检测采集按钮
            gather_result = self._detect_gather_button()
            if gather_result is None or gather_result.element_count == 0:
                self._fail("Gather button not found")
                return self._build_result()

            # Step 6: 点击采集按钮
            gather_btn = gather_result.elements[0]
            if not self._click_element(gather_btn, "Gather button"):
                self._fail("Failed to click gather button")
                return self._build_result()

            self.state = GemCollectState.WAITING_UI
            self._wait_for_ui()

            # Step 7: 选择军队 (MVP简化: 直接确认)
            self.state = GemCollectState.SELECTING_ARMY
            self._log(
                f"Army config: count={self.config.army_count}, "
                f"type={self.config.army_type}"
            )

            # Step 8: 确认采集
            self.state = GemCollectState.CONFIRMING
            confirm_result = self._detect_confirm_button()
            if confirm_result is not None and confirm_result.element_count > 0:
                confirm_btn = confirm_result.elements[0]
                self._click_element(confirm_btn, "Confirm button")
            else:
                # MVP: 如果没有检测到确认按钮, 尝试直接确认
                self._log("Confirm button not detected, attempting direct confirm")

            # Step 9: 等待采集完成
            self.state = GemCollectState.GATHERING
            self._wait_for_gathering()

            # 完成
            self.state = GemCollectState.COMPLETED
            self._log("Gem collection completed successfully")

        except Exception as e:
            self._fail(f"Unexpected error: {e}")

        return self._build_result()

    def _detect_gem_mines(self) -> Optional[DetectionResult]:
        """检测宝石矿.

        Returns:
            检测结果, 失败时返回None
        """
        try:
            if self.capture_func is None:
                self._log("No capture function available")
                return None

            image = self.capture_func()
            if image is None:
                self._log("Failed to capture screen")
                return None

            result = self.detector.detect(image)
            gem_mines = result.filter_by_class(self.GEM_MINE_CLASS)
            self._log(f"Detected {len(gem_mines)} gem mine(s)")
            return DetectionResult(
                elements=gem_mines,
                image_width=result.image_width,
                image_height=result.image_height,
                timestamp=result.timestamp,
            )

        except Exception as e:
            self._log(f"Detection error: {e}")
            return None

    def _filter_mines_by_level(
        self, result: DetectionResult
    ) -> List[DetectionElement]:
        """按等级筛选宝石矿.

        MVP实现: 使用置信度作为等级的代理
        (实际中需要通过模型输出或额外的分类器判断等级)

        Args:
            result: 检测结果

        Returns:
            符合等级要求的宝石矿列表
        """
        # MVP: 所有检测到的宝石矿都认为是可采集的
        # 后续版本可以通过模型的metadata字段或额外分类器区分等级
        return result.elements

    def _select_best_mine(
        self, mines: List[DetectionElement]
    ) -> DetectionElement:
        """选择最优宝石矿.

        MVP实现: 选择置信度最高的
        (实际中可以结合距离、等级等因素)

        Args:
            mines: 宝石矿列表

        Returns:
            最优宝石矿
        """
        return max(mines, key=lambda m: m.confidence)

    def _click_mine(self, mine: DetectionElement) -> bool:
        """点击宝石矿.

        Args:
            mine: 宝石矿检测元素

        Returns:
            是否点击成功
        """
        self.state = GemCollectState.CLICKING_MINE
        cx, cy = mine.center
        self._log(f"Clicking gem mine at ({cx}, {cy})")

        success = self.game_controller.safe_click(cx, cy)
        if success:
            self._log("Gem mine clicked successfully")
        else:
            self._log("Failed to click gem mine")
        return success

    def _wait_for_ui(self, timeout: float = 2.0) -> None:
        """等待UI加载.

        Args:
            timeout: 超时时间(秒)
        """
        self._log(f"Waiting for UI to load ({timeout}s)")
        time.sleep(timeout)

    def _detect_gather_button(self) -> Optional[DetectionResult]:
        """检测采集按钮.

        Returns:
            检测结果, 失败时返回None
        """
        try:
            if self.capture_func is None:
                return None

            image = self.capture_func()
            if image is None:
                return None

            result = self.detector.detect(image)
            gather_btns = result.filter_by_class(self.GATHER_BTN_CLASS)
            self._log(f"Detected {len(gather_btns)} gather button(s)")

            return DetectionResult(
                elements=gather_btns,
                image_width=result.image_width,
                image_height=result.image_height,
                timestamp=result.timestamp,
            )

        except Exception as e:
            self._log(f"Gather button detection error: {e}")
            return None

    def _detect_confirm_button(self) -> Optional[DetectionResult]:
        """检测确认按钮.

        Returns:
            检测结果, 失败时返回None
        """
        try:
            if self.capture_func is None:
                return None

            image = self.capture_func()
            if image is None:
                return None

            result = self.detector.detect(image)
            confirm_btns = result.filter_by_class(self.CONFIRM_BTN_CLASS)
            self._log(f"Detected {len(confirm_btns)} confirm button(s)")

            return DetectionResult(
                elements=confirm_btns,
                image_width=result.image_width,
                image_height=result.image_height,
                timestamp=result.timestamp,
            )

        except Exception as e:
            self._log(f"Confirm button detection error: {e}")
            return None

    def _click_element(self, element: DetectionElement, name: str) -> bool:
        """点击指定元素.

        Args:
            element: 检测元素
            name: 元素名称(日志用)

        Returns:
            是否点击成功
        """
        cx, cy = element.center
        self._log(f"Clicking {name} at ({cx}, {cy})")

        success = self.game_controller.safe_click(cx, cy)
        if success:
            self._log(f"{name} clicked successfully")
        else:
            self._log(f"Failed to click {name}")
        return success

    def _wait_for_gathering(self, timeout: float = 3.0) -> None:
        """等待采集操作完成.

        Args:
            timeout: 超时时间(秒)
        """
        self._log(f"Waiting for gathering to complete ({timeout}s)")
        time.sleep(timeout)

    def _fail(self, reason: str) -> None:
        """标记任务失败.

        Args:
            reason: 失败原因
        """
        self.state = GemCollectState.FAILED
        self.last_error = reason
        self.retry_count += 1
        self._log(f"Task failed: {reason} (retry {self.retry_count}/{self.max_retries})")

    def _build_result(self) -> Dict[str, Any]:
        """构建任务结果.

        Returns:
            任务结果字典
        """
        self.end_time = time.time()
        duration = self.end_time - (self.start_time or self.end_time)

        success = self.state == GemCollectState.COMPLETED

        result = {
            "task_id": self.task_id,
            "success": success,
            "state": self.state.value,
            "duration": round(duration, 2),
            "retries": self.retry_count,
        }

        if not success:
            result["error"] = self.last_error

        # 发布事件
        if success:
            self.event_bus.publish(
                TaskCompletedEvent(task_id=self.task_id, result=result)
            )
        else:
            self.event_bus.publish(
                TaskFailedEvent(task_id=self.task_id, error=self.last_error)
            )

        return result

    def _log(self, message: str) -> None:
        """记录日志.

        Args:
            message: 日志消息
        """
        logger = get_logger(self.__class__.__name__)
        logger.info(f"[{self.task_id}] [{self.state.value}] {message}")
