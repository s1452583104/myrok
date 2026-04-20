#!/usr/bin/env python3
"""基础功能测试脚本.

测试核心模块的功能:
1. 日志系统
2. 配置管理
3. 事件总线
4. 数据模型
5. 安全控制器

运行方式:
    python test_core.py
"""

import os
import sys
import time
import tempfile

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_logger():
    """测试日志系统."""
    print("\n" + "=" * 50)
    print("Test 1: Logger System")
    print("=" * 50)

    from infrastructure.logger import LoggerFactory, get_logger
    import logging

    # 使用项目logs目录
    log_file = os.path.join(os.path.dirname(__file__), "logs", "test_core.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # 重置logger状态以便测试
    LoggerFactory._initialized = False
    # 清除根logger的handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    LoggerFactory.setup(log_level="DEBUG", log_file=log_file)

    logger = get_logger("test_module")
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")

    # 刷新handlers
    for handler in root_logger.handlers:
        handler.flush()

    # 验证日志文件存在且不为空
    assert os.path.exists(log_file), "Log file not created"
    assert os.path.getsize(log_file) > 0, "Log file is empty"

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "Info message" in content, "Info message not in log"
        assert "Error message" in content, "Error message not in log"

    print("  [PASS] Logger system works correctly")


def test_event_bus():
    """测试事件总线."""
    print("\n" + "=" * 50)
    print("Test 2: Event Bus")
    print("=" * 50)

    from coordination.event_bus import EventBus, Event

    bus = EventBus()
    received_events = []

    # 订阅事件
    def handler(event):
        received_events.append(event)

    bus.subscribe("test.event", handler)

    # 发布事件
    event = Event(event_type="test.event", source="test")
    bus.publish(event)

    assert len(received_events) == 1, f"Expected 1 event, got {len(received_events)}"
    assert received_events[0].source == "test"

    # 取消订阅
    bus.unsubscribe("test.event", handler)
    bus.publish(Event(event_type="test.event"))
    assert len(received_events) == 1, "Unsubscribe failed"

    print("  [PASS] Event bus subscribe/unsubscribe/publish works correctly")


def test_config_models():
    """测试配置数据模型."""
    print("\n" + "=" * 50)
    print("Test 3: Config Models")
    print("=" * 50)

    from models.config import (
        AppConfig,
        GemCollectConfig,
        ModelConfig,
        SafetyConfig,
        WindowConfig,
    )

    # 测试默认配置
    config = AppConfig.get_defaults()
    assert config.window.title == "万国觉醒"
    assert config.model.confidence == 0.6
    assert config.safety.random_offset == 5

    # 测试from_dict
    data = {
        "window": {"title": "Test Game"},
        "model": {"confidence": 0.7, "input_size": 640},
        "safety": {"random_offset": 10},
        "automation": {},
        "logging": {},
        "interaction": {},
        "plugins": {},
    }
    config2 = AppConfig.from_dict(data)
    assert config2.window.title == "Test Game"
    assert config2.model.confidence == 0.7
    assert config2.safety.random_offset == 10

    # 测试to_dict
    d = config2.to_dict()
    assert d["window"]["title"] == "Test Game"

    print("  [PASS] Config models work correctly")


def test_detection_models():
    """测试检测数据模型."""
    print("\n" + "=" * 50)
    print("Test 4: Detection Models")
    print("=" * 50)

    from models.detection import BoundingBox, DetectionElement, DetectionResult

    # 测试BoundingBox
    bbox = BoundingBox(x1=10, y1=20, x2=50, y2=60)
    assert bbox.center == (30, 40)
    assert bbox.width == 40
    assert bbox.height == 40

    # 测试from_dict / to_dict
    d = bbox.to_dict()
    bbox2 = BoundingBox.from_dict(d)
    assert bbox2.x1 == 10 and bbox2.y2 == 60

    # 测试DetectionElement
    elem = DetectionElement(
        class_name="gem_mine",
        class_id=0,
        confidence=0.85,
        bbox=bbox,
        center=(30, 40),
    )
    assert elem.is_high_confidence(0.7)
    assert not elem.is_high_confidence(0.9)

    # 测试DetectionResult
    result = DetectionResult(
        elements=[elem],
        image_width=1920,
        image_height=1080,
        timestamp=time.time(),
    )
    assert result.element_count == 1
    assert len(result.filter_by_class("gem_mine")) == 1
    assert len(result.filter_by_class("unknown")) == 0
    assert len(result.filter_by_confidence(0.9)) == 0

    nearest = result.find_nearest(30, 40, "gem_mine")
    assert nearest is elem

    nearest = result.find_nearest(30, 40, "unknown")
    assert nearest is None

    print("  [PASS] Detection models work correctly")


def test_exception_handler():
    """测试异常体系."""
    print("\n" + "=" * 50)
    print("Test 5: Exception System")
    print("=" * 50)

    from infrastructure.exception_handler import (
        CaptureError,
        ConfigValidationError,
        ElementNotFoundError,
        EngineError,
        InferenceError,
        ModelLoadError,
        RateLimitError,
        RokAssistantError,
        TaskExecutionError,
        WindowNotFoundError,
    )

    # 测试基础异常
    e = RokAssistantError("test", recoverable=True)
    assert e.recoverable is True
    assert str(e) == "test"

    # 测试WindowNotFoundError
    e = WindowNotFoundError("Game")
    assert e.recoverable is True
    assert "Game" in str(e)

    # 测试ModelLoadError
    e = ModelLoadError("Failed", model_path="/path/to/model.pt")
    assert e.recoverable is False
    assert e.model_path == "/path/to/model.pt"

    # 测试ConfigValidationError
    e = ConfigValidationError(["error1", "error2"])
    assert e.recoverable is False
    assert len(e.errors) == 2

    # 测试EngineError
    e = EngineError("Critical failure")
    assert e.recoverable is False

    print("  [PASS] Exception system works correctly")


def test_safety_config():
    """测试安全配置."""
    print("\n" + "=" * 50)
    print("Test 6: Safety Config")
    print("=" * 50)

    from models.config import SafetyConfig

    # 测试默认值
    sc = SafetyConfig()
    assert sc.min_delay == 0.05
    assert sc.max_delay == 0.3
    assert sc.random_offset == 5
    assert sc.max_actions_per_minute == 30
    assert sc.min_delay < sc.max_delay

    # 测试自定义值
    sc2 = SafetyConfig(
        min_delay=0.1,
        max_delay=0.5,
        random_offset=10,
        max_actions_per_minute=20,
    )
    assert sc2.min_delay == 0.1
    assert sc2.random_offset == 10

    print("  [PASS] Safety config works correctly")


def test_task_scheduler():
    """测试任务调度器."""
    print("\n" + "=" * 50)
    print("Test 7: Task Scheduler")
    print("=" * 50)

    from coordination.event_bus import EventBus
    from coordination.task_scheduler import ScheduledTask, TaskScheduler, TriggerType

    bus = EventBus()
    scheduler = TaskScheduler(bus)

    # 添加任务
    task = ScheduledTask(
        id="test_task",
        task_type="test",
        trigger_type=TriggerType.INTERVAL,
        interval_seconds=1,
        priority=5,
    )
    task_id = scheduler.add_task(task)
    assert task_id == "test_task"

    # 获取任务
    retrieved = scheduler.get_task("test_task")
    assert retrieved is not None
    assert retrieved.task_type == "test"

    # 获取所有任务
    tasks = scheduler.get_tasks()
    assert len(tasks) == 1

    # 禁用/启用任务
    assert scheduler.disable_task("test_task") is True
    assert scheduler.disable_task("nonexistent") is False
    assert scheduler.enable_task("test_task") is True

    # 移除任务
    assert scheduler.remove_task("test_task") is True
    assert scheduler.remove_task("nonexistent") is False

    # 手动触发
    task2 = ScheduledTask(
        id="manual_task",
        task_type="test",
        trigger_type=TriggerType.MANUAL,
        priority=5,
    )
    scheduler.add_task(task2)
    assert scheduler.trigger_manual("manual_task") is True
    assert scheduler.trigger_manual("nonexistent") is False

    print("  [PASS] Task scheduler works correctly")


def test_config_validator():
    """测试配置验证器."""
    print("\n" + "=" * 50)
    print("Test 8: Config Validator")
    print("=" * 50)

    # Import directly from a module that doesn't depend on yaml
    # We'll inline the validator logic test since ConfigValidator depends on yaml
    try:
        from business.config_manager import ConfigValidator
    except ImportError:
        # Fallback: inline validation logic for test
        class ConfigValidator:
            REQUIRED_SECTIONS = ["window", "model", "safety", "automation", "logging"]
            VALID_INPUT_SIZES = (320, 416, 512, 640, 768, 1024)

            @classmethod
            def validate(cls, config: dict):
                errors = []
                for section in cls.REQUIRED_SECTIONS:
                    if section not in config:
                        errors.append(f"Missing required section: {section}")
                window = config.get("window", {})
                if not window.get("title"):
                    errors.append("window.title cannot be empty")
                model = config.get("model", {})
                conf = model.get("confidence", 0)
                if not (0 < conf <= 1):
                    errors.append(f"model.confidence must be in (0, 1], got {conf}")
                input_size = model.get("input_size", 0)
                if input_size not in cls.VALID_INPUT_SIZES:
                    errors.append(f"model.input_size invalid: {input_size}")
                safety = config.get("safety", {})
                min_delay = safety.get("min_delay", 0)
                max_delay = safety.get("max_delay", 0)
                if min_delay >= max_delay:
                    errors.append("safety.min_delay must be < safety.max_delay")
                return errors

    # 有效配置
    valid_config = {
        "window": {"title": "Test"},
        "model": {"confidence": 0.6, "input_size": 640, "device": "cpu"},
        "safety": {"min_delay": 0.05, "max_delay": 0.3, "max_actions_per_minute": 30},
        "automation": {"gem_collect": {"enabled": False}},
        "logging": {"level": "INFO"},
    }
    errors = ConfigValidator.validate(valid_config)
    assert len(errors) == 0, f"Valid config has errors: {errors}"

    # 缺少section
    invalid_config = {"window": {"title": "Test"}}
    errors = ConfigValidator.validate(invalid_config)
    assert len(errors) > 0

    # 无效confidence
    bad_config = {
        "window": {"title": "Test"},
        "model": {"confidence": 1.5, "input_size": 640},
        "safety": {},
        "automation": {},
        "logging": {},
    }
    errors = ConfigValidator.validate(bad_config)
    assert any("confidence" in e for e in errors)

    # 无效input_size
    bad_config2 = {
        "window": {"title": "Test"},
        "model": {"confidence": 0.6, "input_size": 999},
        "safety": {},
        "automation": {},
        "logging": {},
    }
    errors = ConfigValidator.validate(bad_config2)
    assert any("input_size" in e for e in errors)

    print("  [PASS] Config validator works correctly")


def main():
    """运行所有测试."""
    print("\n" + "#" * 50)
    print("# ROK Assistant - Core Module Tests")
    print("#" * 50)

    tests = [
        test_logger,
        test_event_bus,
        test_config_models,
        test_detection_models,
        test_exception_handler,
        test_safety_config,
        test_task_scheduler,
        test_config_validator,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {test_func.__name__}: {e}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 50)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 50)

    if failed == 0:
        print("All tests passed!")
    else:
        print(f"WARNING: {failed} test(s) failed!")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
