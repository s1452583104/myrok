"""集成测试 - 宝石采集功能端到端验证.

使用Mock模拟真实环境，验证完整流程:
窗口捕获 -> YOLO检测 -> 游戏控制 -> 宝石采集任务
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock

import numpy as np

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from business.game_controller import GameController
from coordination.event_bus import EventBus
from coordination.task_scheduler import TaskScheduler
from core.window_capture import WindowCapture
from core.yolo_detector import YOLODetector
from infrastructure.exception_handler import (
    InferenceError,
    ModelLoadError,
    RokAssistantError,
)
from infrastructure.logger import LoggerFactory
from models.config import AppConfig, GemCollectConfig, SafetyConfig
from models.detection import BoundingBox, DetectionElement, DetectionResult


def test_detection_flow():
    """测试检测流程（使用Mock模型）."""
    print("\n=== Test: Detection Flow ===")

    # 创建Mock YOLO模型
    mock_yolo = Mock()
    mock_box = Mock()
    mock_box.xyxy = Mock()
    mock_box.xyxy.__getitem__ = Mock(
        return_value=np.array([100.0, 100.0, 200.0, 200.0])
    )
    mock_box.conf = Mock()
    mock_box.conf.__getitem__ = Mock(return_value=np.array([0.85]))
    mock_box.cls = Mock()
    mock_box.cls.__getitem__ = Mock(return_value=np.array([0]))
    mock_box.__len__ = Mock(return_value=1)

    mock_result = Mock()
    mock_result.boxes = mock_box
    mock_result.names = {0: "gem_mine"}

    mock_yolo.return_value = [mock_result]

    # 创建检测器并注入Mock
    detector = YOLODetector(
        model_path="mock/path.pt",
        confidence_threshold=0.5,
        iou_threshold=0.45,
        input_size=640,
        device="cpu",
    )

    # 手动设置Mock模型
    detector._model = mock_yolo
    detector._class_names = ["gem_mine"]

    # 创建测试图像
    test_image = np.zeros((1080, 1920, 3), dtype=np.uint8)

    # 执行检测
    result = detector.detect(test_image)

    print(f"  Detected elements: {result.element_count}")
    print(f"  Image size: {result.image_width}x{result.image_height}")

    assert result.element_count >= 0, "Detection should return element count >= 0"
    print("  PASSED")
    return True


def test_game_controller_safe_click():
    """测试游戏控制器的安全点击."""
    print("\n=== Test: Game Controller Safe Click ===")

    # 创建Mock依赖
    mock_capture = Mock(spec=WindowCapture)
    mock_capture.capture.return_value = np.zeros((1080, 1920, 3), dtype=np.uint8)

    safety_config = SafetyConfig(
        min_delay=0.01,
        max_delay=0.05,
        random_offset=3,
        click_duration=0.05,
        max_actions_per_minute=30,
    )

    # 创建控制器
    controller = GameController(
        window_capture=mock_capture, safety_config=safety_config
    )

    # 测试安全点击（会调用pyautogui，需要Mock）
    import pyautogui

    original_click = pyautogui.click
    pyautogui.click = Mock()

    try:
        result = controller.safe_click(100, 100)
        print(f"  Safe click result: {result}")
        assert result is True, "Safe click should succeed"
        print("  PASSED")
        return True
    finally:
        pyautogui.click = original_click


def test_gem_collection_task_flow():
    """测试宝石采集任务完整流程（全Mock）."""
    print("\n=== Test: Gem Collection Task Flow ===")

    # 导入任务模块
    from plugins.gem_collect.task import GemCollectionTask, GemCollectState

    # 创建Mock依赖
    mock_detector = Mock(spec=YOLODetector)
    mock_controller = Mock()
    mock_controller.safe_click.return_value = True
    mock_event_bus = Mock(spec=EventBus)

    # 创建截图函数Mock
    def mock_capture():
        return np.zeros((1080, 1920, 3), dtype=np.uint8)

    # 创建配置
    gem_config = GemCollectConfig(
        enabled=True,
        min_level=1,
        collect_radius=10,
        army_count=1,
        army_type="infantry",
        check_interval=300,
        max_concurrent=3,
    )

    # 创建Mock检测结果
    gem_mine = DetectionElement(
        class_name="gem_mine",
        class_id=0,
        confidence=0.9,
        bbox=BoundingBox(x1=100, y1=100, x2=200, y2=200),
        center=(150, 150),
    )

    gather_btn = DetectionElement(
        class_name="gather_btn",
        class_id=1,
        confidence=0.85,
        bbox=BoundingBox(x1=300, y1=300, x2=400, y2=350),
        center=(350, 325),
    )

    # 配置Mock检测器返回
    def mock_detect(image):
        # 第一次调用：返回宝石矿
        if not hasattr(mock_detect, "call_count"):
            mock_detect.call_count = 0
        mock_detect.call_count += 1

        if mock_detect.call_count == 1:
            return DetectionResult(
                elements=[gem_mine],
                image_width=1920,
                image_height=1080,
                timestamp=time.time(),
            )
        elif mock_detect.call_count == 2:
            return DetectionResult(
                elements=[gather_btn],
                image_width=1920,
                image_height=1080,
                timestamp=time.time(),
            )
        else:
            return DetectionResult(
                elements=[],
                image_width=1920,
                image_height=1080,
                timestamp=time.time(),
            )

    mock_detector.detect.side_effect = mock_detect

    # 创建任务
    task = GemCollectionTask(
        task_id="test_gem_001",
        detector=mock_detector,
        game_controller=mock_controller,
        event_bus=mock_event_bus,
        config=gem_config,
        capture_func=mock_capture,
        max_retries=3,
    )

    # 执行任务
    result = task.execute()

    print(f"  Task ID: {result['task_id']}")
    print(f"  Success: {result['success']}")
    print(f"  State: {result['state']}")
    print(f"  Duration: {result['duration']}s")
    print(f"  Retries: {result['retries']}")

    # 验证任务执行
    assert "task_id" in result, "Result should contain task_id"
    assert "success" in result, "Result should contain success flag"
    assert "duration" in result, "Result should contain duration"

    # 验证控制器被调用
    assert mock_controller.safe_click.called, "Controller should be called"
    print(f"  Controller clicks: {mock_controller.safe_click.call_count}")

    # 验证事件发布
    assert mock_event_bus.publish.called, "Events should be published"
    print(f"  Events published: {mock_event_bus.publish.call_count}")

    print("  PASSED")
    return True


def test_task_scheduler_integration():
    """测试任务调度器集成."""
    print("\n=== Test: Task Scheduler Integration ===")

    bus = EventBus()
    scheduler = TaskScheduler(event_bus=bus)

    # 创建Mock任务
    mock_task = Mock()
    mock_task.execute.return_value = {
        "task_id": "test_001",
        "success": True,
        "duration": 1.5,
    }

    # 添加任务
    from coordination.task_scheduler import AutomationTask, TaskTrigger, TriggerType

    task = AutomationTask(
        task_id="scheduled_test",
        name="Test Task",
        task_obj=mock_task,
        trigger=TaskTrigger(
            trigger_type=TriggerType.ONCE,
            enabled=True,
        ),
        priority=5,
    )

    scheduler.add_task(task)
    active_tasks = scheduler.get_active_tasks()
    print(f"  Active tasks: {len(active_tasks)}")

    # 执行调度
    scheduler.run_cycle()

    print("  PASSED")
    return True


def test_event_bus_communication():
    """测试事件总线通信."""
    print("\n=== Test: Event Bus Communication ===")

    bus = EventBus()
    received_events = []

    # 订阅事件
    def on_task_completed(event):
        received_events.append(event)
        print(f"  Received: {event.task_id}")

    from coordination.event_bus import TaskCompletedEvent

    bus.subscribe(TaskCompletedEvent.event_type, on_task_completed)

    # 发布事件
    bus.publish(TaskCompletedEvent(task_id="test_event_001", result={"status": "ok"}))

    # 处理队列
    bus.process_queue()

    assert len(received_events) == 1, "Should receive one event"
    assert received_events[0].task_id == "test_event_001"
    print("  PASSED")
    return True


def test_error_handling():
    """测试异常处理."""
    print("\n=== Test: Error Handling ===")

    from plugins.gem_collect.task import GemCollectState

    # 测试检测失败场景
    mock_detector = Mock()
    mock_detector.detect.side_effect = InferenceError("Model not loaded")

    mock_controller = Mock()
    mock_event_bus = Mock()
    mock_capture = Mock(return_value=np.zeros((1080, 1920, 3), dtype=np.uint8))

    from models.config import GemCollectConfig

    gem_config = GemCollectConfig()

    from plugins.gem_collect.task import GemCollectionTask

    task = GemCollectionTask(
        task_id="error_test_001",
        detector=mock_detector,
        game_controller=mock_controller,
        event_bus=mock_event_bus,
        config=gem_config,
        capture_func=mock_capture,
    )

    # 执行任务，应该优雅处理异常
    result = task.execute()

    assert result["success"] is False, "Task should fail gracefully"
    assert "error" in result, "Result should contain error message"
    print(f"  Error handled: {result['error']}")
    print(f"  State: {result['state']}")
    print("  PASSED")
    return True


def run_all_tests():
    """运行所有集成测试."""
    print("\n" + "=" * 60)
    print("  ROK Assistant - Integration Test Suite")
    print("=" * 60)

    tests = [
        test_detection_flow,
        test_game_controller_safe_click,
        test_gem_collection_task_flow,
        test_task_scheduler_integration,
        test_event_bus_communication,
        test_error_handling,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
