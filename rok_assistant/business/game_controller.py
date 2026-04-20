"""游戏交互控制模块.

提供安全的鼠标/键盘操作, 包含随机延迟和偏移以防止被反作弊检测.

核心功能:
- 安全的鼠标点击/拖拽/移动
- 随机延迟和偏移
- 操作频率限制
- 坐标转换（相对窗口坐标 -> 屏幕绝对坐标）

线程安全: 是（操作串行化）
"""

import random
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple

from core.window_capture import WindowCapture
from infrastructure.exception_handler import RateLimitError
from infrastructure.logger import get_logger

try:
    import pyautogui

    _PYAUTOGUI_AVAILABLE = True
    # 设置pyautogui的安全选项
    pyautogui.FAILSAFE = True  # 移动鼠标到屏幕左上角可以中断
    pyautogui.PAUSE = 0  # 我们不使用pyautogui的内置暂停, 使用自己的
except ImportError:
    _PYAUTOGUI_AVAILABLE = False


@dataclass
class SafetyConfig:
    """安全操作配置.

    Attributes:
        min_delay: 最小操作间隔(秒)
        max_delay: 最大操作间隔(秒)
        random_offset: 随机偏移(像素)
        click_duration: 点击持续时间(秒)
        max_actions_per_minute: 每分钟最大操作数
    """

    min_delay: float = 0.05
    max_delay: float = 0.3
    random_offset: int = 5
    click_duration: float = 0.1
    max_actions_per_minute: int = 30


class BaseInputController(ABC):
    """输入控制抽象基类.

    定义所有输入控制器必须实现的接口, 支持切换不同输入库.
    """

    @abstractmethod
    def click(self, x: int, y: int, button: str = "left") -> None:
        pass

    @abstractmethod
    def double_click(self, x: int, y: int) -> None:
        pass

    @abstractmethod
    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        pass

    @abstractmethod
    def move_mouse(self, x: int, y: int) -> None:
        pass


class GameController:
    """游戏交互控制器.

    职责:
    - 安全的鼠标/键盘操作
    - 随机延迟和偏移
    - 操作频率限制
    - 坐标转换（相对窗口坐标）

    线程安全: 是（操作串行化）

    使用示例:
        capture = WindowCapture("Game")
        capture.find_window()
        safety = SafetyConfig(min_delay=0.1, max_delay=0.3, random_offset=5)
        controller = GameController(capture, safety)
        controller.safe_click(100, 200)
    """

    def __init__(
        self,
        window_capture: WindowCapture,
        safety_config: SafetyConfig,
    ):
        """初始化游戏控制器.

        Args:
            window_capture: 窗口捕获实例
            safety_config: 安全配置
        """
        self._window_capture = window_capture
        self._safety_config = safety_config
        self._lock = threading.Lock()
        self._action_timestamps: List[float] = []
        self._logger = get_logger(self.__class__.__name__)

    def safe_click(self, x: int, y: int, button: str = "left") -> bool:
        """安全点击（带随机延迟和偏移）.

        Args:
            x: X坐标（相对于窗口客户区）
            y: Y坐标（相对于窗口客户区）
            button: 鼠标按钮 (left, right, middle)

        Returns:
            操作是否成功
        """
        with self._lock:
            if not _PYAUTOGUI_AVAILABLE:
                self._logger.error("pyautogui is not installed")
                return False

            try:
                # 检查操作频率
                self._check_rate_limit()

                # 随机偏移
                rx, ry = self._randomize_position(x, y)

                # 转换到屏幕绝对坐标
                screen_x, screen_y = self._to_screen_coords(rx, ry)

                # 移动鼠标
                pyautogui.moveTo(screen_x, screen_y, duration=0.1)

                # 随机延迟
                self._apply_safety_delay()

                # 执行点击
                pyautogui.click(screen_x, screen_y, button=button)

                self._logger.debug(
                    f"Click: ({x},{y}) -> screen({screen_x},{screen_y})"
                )
                return True

            except RateLimitError as e:
                self._logger.warning(f"Rate limit: {e}")
                return False
            except Exception as e:
                self._logger.error(f"Click failed: {e}", exc_info=True)
                return False

    def safe_double_click(self, x: int, y: int) -> bool:
        """安全双击（带随机延迟和偏移）.

        Args:
            x: X坐标（相对于窗口客户区）
            y: Y坐标（相对于窗口客户区）

        Returns:
            操作是否成功
        """
        with self._lock:
            if not _PYAUTOGUI_AVAILABLE:
                self._logger.error("pyautogui is not installed")
                return False

            try:
                self._check_rate_limit()
                rx, ry = self._randomize_position(x, y)
                screen_x, screen_y = self._to_screen_coords(rx, ry)

                pyautogui.moveTo(screen_x, screen_y, duration=0.1)
                self._apply_safety_delay()
                pyautogui.doubleClick(screen_x, screen_y)

                self._logger.debug(f"Double click: ({x},{y}) -> screen({screen_x},{screen_y})")
                return True

            except RateLimitError as e:
                self._logger.warning(f"Rate limit: {e}")
                return False
            except Exception as e:
                self._logger.error(f"Double click failed: {e}", exc_info=True)
                return False

    def safe_drag(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """安全拖拽（带随机延迟和偏移）.

        Args:
            x1: 起始X坐标
            y1: 起始Y坐标
            x2: 目标X坐标
            y2: 目标Y坐标

        Returns:
            操作是否成功
        """
        with self._lock:
            if not _PYAUTOGUI_AVAILABLE:
                self._logger.error("pyautogui is not installed")
                return False

            try:
                self._check_rate_limit()
                rx1, ry1 = self._randomize_position(x1, y1)
                rx2, ry2 = self._randomize_position(x2, y2)

                screen_x1, screen_y1 = self._to_screen_coords(rx1, ry1)
                screen_x2, screen_y2 = self._to_screen_coords(rx2, ry2)

                pyautogui.moveTo(screen_x1, screen_y1, duration=0.1)
                self._apply_safety_delay()
                pyautogui.drag(
                    screen_x2 - screen_x1,
                    screen_y2 - screen_y1,
                    button="left",
                    duration=0.3,
                )

                self._logger.debug(
                    f"Drag: ({x1},{y1}) -> ({x2},{y2})"
                )
                return True

            except RateLimitError as e:
                self._logger.warning(f"Rate limit: {e}")
                return False
            except Exception as e:
                self._logger.error(f"Drag failed: {e}", exc_info=True)
                return False

    def safe_key_press(self, key: str) -> bool:
        """安全按键按下.

        Args:
            key: 按键名称

        Returns:
            操作是否成功
        """
        with self._lock:
            if not _PYAUTOGUI_AVAILABLE:
                self._logger.error("pyautogui is not installed")
                return False

            try:
                self._check_rate_limit()
                self._apply_safety_delay()
                pyautogui.press(key)
                self._logger.debug(f"Key press: {key}")
                return True

            except RateLimitError as e:
                self._logger.warning(f"Rate limit: {e}")
                return False
            except Exception as e:
                self._logger.error(f"Key press failed: {e}", exc_info=True)
                return False

    def safe_key_combo(self, keys: List[str]) -> bool:
        """安全组合按键.

        Args:
            keys: 按键列表

        Returns:
            操作是否成功
        """
        with self._lock:
            if not _PYAUTOGUI_AVAILABLE:
                self._logger.error("pyautogui is not installed")
                return False

            try:
                self._check_rate_limit()
                self._apply_safety_delay()
                pyautogui.hotkey(*keys)
                self._logger.debug(f"Key combo: {keys}")
                return True

            except RateLimitError as e:
                self._logger.warning(f"Rate limit: {e}")
                return False
            except Exception as e:
                self._logger.error(f"Key combo failed: {e}", exc_info=True)
                return False

    def click_element(self, element) -> bool:
        """点击检测到的元素.

        Args:
            element: DetectionElement实例

        Returns:
            操作是否成功
        """
        if element is None:
            self._logger.warning("Cannot click None element")
            return False

        cx, cy = element.center
        return self.safe_click(cx, cy)

    def _randomize_position(self, x: int, y: int) -> Tuple[int, int]:
        """添加随机偏移.

        Args:
            x: 原始X坐标
            y: 原始Y坐标

        Returns:
            添加偏移后的坐标
        """
        offset = self._safety_config.random_offset
        offset_x = random.randint(-offset, offset)
        offset_y = random.randint(-offset, offset)
        return x + offset_x, y + offset_y

    def _to_screen_coords(self, x: int, y: int) -> Tuple[int, int]:
        """将窗口相对坐标转换为屏幕绝对坐标.

        Args:
            x: 窗口相对X坐标
            y: 窗口相对Y坐标

        Returns:
            屏幕绝对坐标 (screen_x, screen_y)
        """
        hwnd = self._window_capture.hwnd
        if hwnd is None:
            raise RuntimeError("Window not found")

        try:
            import win32gui

            window_rect = win32gui.GetWindowRect(hwnd)
            # GetWindowRect returns (left, top, right, bottom)
            # The client area starts after the title bar and borders
            client_rect = self._window_capture.get_client_rect()
            # Calculate the border/title bar offset
            border_x = window_rect[0]
            border_y = window_rect[1]

            screen_x = border_x + x
            screen_y = border_y + y
            return screen_x, screen_y

        except Exception as e:
            self._logger.error(f"Failed to convert coords: {e}")
            return x, y

    def _apply_safety_delay(self) -> None:
        """应用随机安全延迟."""
        delay = random.uniform(
            self._safety_config.min_delay,
            self._safety_config.max_delay,
        )
        time.sleep(delay)

    def _check_rate_limit(self) -> None:
        """检查操作频率限制.

        Raises:
            RateLimitError: 超出频率限制
        """
        now = time.time()
        # 清理60秒前的记录
        self._action_timestamps = [
            t for t in self._action_timestamps if now - t < 60
        ]
        if len(self._action_timestamps) >= self._safety_config.max_actions_per_minute:
            raise RateLimitError(
                f"Action rate limit exceeded: "
                f"{len(self._action_timestamps)} actions in last 60s"
            )
        self._action_timestamps.append(now)
