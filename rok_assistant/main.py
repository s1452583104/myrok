#!/usr/bin/env python3
"""万国觉醒游戏辅助工具 - 主程序入口.

启动方式:
    python main.py              # 启动GUI
    python main.py --no-gui     # 无GUI模式（仅日志）
    python main.py --test       # 运行基础测试

依赖安装:
    pip install -r requirements.txt
"""

import os
import sys
import time
from typing import Optional

# 确保可以导入项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from business.config_manager import ConfigManager
from business.game_controller import GameController, SafetyConfig
from coordination.event_bus import (
    DetectionCompletedEvent,
    EngineStartedEvent,
    EngineStoppedEvent,
    EventBus,
    TaskCompletedEvent,
    TaskFailedEvent,
)
from coordination.task_scheduler import ScheduledTask, TaskScheduler, TriggerType
from core.window_capture import WindowCapture
from core.yolo_detector import YOLODetector
from infrastructure.exception_handler import WindowNotFoundError
from infrastructure.logger import LoggerFactory, get_logger
from models.config import AppConfig, GemCollectConfig


def create_application(
    config_path: str = "config.yaml",
) -> tuple:
    """创建应用核心组件.

    Args:
        config_path: 配置文件路径

    Returns:
        (event_bus, config_manager, window_capture, detector, controller, scheduler)
    """
    logger = get_logger("main")
    logger.info("Initializing application...")

    # 1. 事件总线
    event_bus = EventBus()

    # 2. 配置管理
    config_manager = ConfigManager(config_path, event_bus)
    config = config_manager.load()
    logger.info(f"Config loaded: {config_path}")

    # 3. 窗口捕获
    window_capture = WindowCapture(config.window.title)

    # 4. YOLO检测器
    detector = YOLODetector(
        model_path=config.model.path,
        confidence_threshold=config.model.confidence,
        iou_threshold=config.model.iou_threshold,
        input_size=config.model.input_size,
        device=config.model.device,
    )

    # 5. 游戏控制器
    safety_config = SafetyConfig(
        min_delay=config.safety.min_delay,
        max_delay=config.safety.max_delay,
        random_offset=config.safety.random_offset,
        click_duration=config.safety.click_duration,
        max_actions_per_minute=config.safety.max_actions_per_minute,
    )
    controller = GameController(window_capture, safety_config)

    # 6. 任务调度器
    scheduler = TaskScheduler(event_bus)

    # 注册事件监听
    event_bus.subscribe("engine.started", lambda e: logger.info("Engine started"))
    event_bus.subscribe("engine.stopped", lambda e: logger.info("Engine stopped"))
    event_bus.subscribe("engine.error", lambda e: logger.error(f"Engine error: {e.error_message}"))
    event_bus.subscribe("task.completed", lambda e: logger.info(f"Task completed: {e.task_id}"))
    event_bus.subscribe("task.failed", lambda e: logger.warning(f"Task failed: {e.task_id} - {e.error}"))

    return event_bus, config_manager, window_capture, detector, controller, scheduler


def run_gem_collection_task(
    window_capture: WindowCapture,
    detector: YOLODetector,
    controller: GameController,
    scheduler: TaskScheduler,
    config: GemCollectConfig,
) -> None:
    """注册并启动宝石采集任务.

    Args:
        window_capture: 窗口捕获器
        detector: YOLO检测器
        controller: 游戏控制器
        scheduler: 任务调度器
        config: 宝石采集配置
    """
    logger = get_logger("gem_collect_setup")

    if not config.enabled:
        logger.info("Gem collection is disabled in config")
        return

    # 创建定时触发任务
    task = ScheduledTask(
        id="gem_collect_main",
        task_type="gem_collect",
        trigger_type=TriggerType.INTERVAL,
        interval_seconds=config.check_interval,
        priority=8,
        config={
            "min_level": config.min_level,
            "army_count": config.army_count,
            "army_type": config.army_type,
        },
    )
    scheduler.add_task(task)
    logger.info(
        f"Gem collection task registered: "
        f"interval={config.check_interval}s, min_level={config.min_level}"
    )

    # 启动调度器
    scheduler.start()
    logger.info("Task scheduler started")


def run_gui(
    event_bus: EventBus,
    window_capture: WindowCapture,
    detector: YOLODetector,
    controller: GameController,
    scheduler: TaskScheduler,
) -> None:
    """启动GUI应用.

    Args:
        event_bus: 事件总线
        window_capture: 窗口捕获器
        detector: YOLO检测器
        controller: 游戏控制器
        scheduler: 任务调度器
    """
    from PyQt6.QtWidgets import QApplication

    from gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 创建窗口
    window = MainWindow(
        event_bus=event_bus,
        capture_func=window_capture.capture,
        detector=detector,
        game_controller=controller,
        task_runner=lambda: run_gem_collection_task(
            window_capture, detector, controller, scheduler,
            AppConfig().automation.gem_collect,
        ),
    )

    window.show()
    sys.exit(app.exec())


def run_no_gui(
    event_bus: EventBus,
    config_manager: ConfigManager,
    window_capture: WindowCapture,
    detector: YOLODetector,
    controller: GameController,
    scheduler: TaskScheduler,
) -> None:
    """无GUI模式运行.

    Args:
        event_bus: 事件总线
        config_manager: 配置管理器
        window_capture: 窗口捕获器
        detector: YOLO检测器
        controller: 游戏控制器
        scheduler: 任务调度器
    """
    logger = get_logger("no_gui")
    config = config_manager.get()

    logger.info("Running in no-GUI mode")
    logger.info("Press Ctrl+C to stop")

    try:
        # 查找窗口
        if window_capture.find_window():
            event_bus.publish(
                EngineStartedEvent()
            )

            # 尝试加载模型
            if detector.load_model():
                logger.info("Model loaded successfully")
            else:
                logger.warning(
                    f"Model not found at {config.model.path}, "
                    "detection will not work"
                )

            # 启动调度器
            scheduler.start()

            # 保持运行
            while True:
                time.sleep(1)
        else:
            logger.error(f"Game window '{config.window.title}' not found")
            logger.info("Please make sure the game is running and try again")

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        scheduler.stop()
        window_capture.close()
        event_bus.publish(EngineStoppedEvent())


def run_basic_test(
    window_capture: WindowCapture,
    detector: YOLODetector,
    controller: GameController,
    config: AppConfig,
) -> None:
    """运行基础功能测试.

    Args:
        window_capture: 窗口捕获器
        detector: YOLO检测器
        controller: 游戏控制器
        config: 应用配置
    """
    logger = get_logger("test")
    logger.info("=" * 50)
    logger.info("Running basic functionality test")
    logger.info("=" * 50)

    # 测试1: 窗口查找
    logger.info("Test 1: Window search...")
    try:
        found = window_capture.find_window()
        if found:
            size = window_capture.get_window_size()
            logger.info(f"  PASS - Window found, size: {size}")
        else:
            logger.warning(f"  SKIP - Window '{config.window.title}' not found")
    except Exception as e:
        logger.error(f"  FAIL - {e}")

    # 测试2: 截图
    logger.info("Test 2: Screen capture...")
    try:
        frame = window_capture.capture()
        if frame is not None:
            logger.info(f"  PASS - Captured {frame.shape}")
        else:
            logger.warning("  SKIP - Capture returned None (window may not be active)")
    except Exception as e:
        logger.error(f"  FAIL - {e}")

    # 测试3: 模型加载
    logger.info("Test 3: Model loading...")
    try:
        loaded = detector.load_model()
        if loaded:
            logger.info(f"  PASS - Model loaded, classes: {detector.class_names}")
        else:
            logger.warning(
                f"  SKIP - Model file not found at {config.model.path}"
            )
    except Exception as e:
        logger.error(f"  FAIL - {e}")

    # 测试4: 安全点击
    logger.info("Test 4: Safety config check...")
    try:
        sc = controller._safety_config
        logger.info(
            f"  PASS - Safety: delay=[{sc.min_delay},{sc.max_delay}]s, "
            f"offset=+/-{sc.random_offset}px, "
            f"max_actions={sc.max_actions_per_minute}/min"
        )
    except Exception as e:
        logger.error(f"  FAIL - {e}")

    logger.info("=" * 50)
    logger.info("Test completed")
    logger.info("=" * 50)


def main():
    """程序入口."""
    # 解析参数
    no_gui = "--no-gui" in sys.argv
    run_test = "--test" in sys.argv
    config_path = "config.yaml"

    # 查找配置文件
    for arg in sys.argv[1:]:
        if arg.endswith(".yaml") or arg.endswith(".yml"):
            config_path = arg
            break

    # 初始化日志
    LoggerFactory.setup(log_level="INFO")
    logger = get_logger("main")

    logger.info("=" * 60)
    logger.info("万国觉醒辅助工具 - ROK Assistant v1.0.0")
    logger.info("=" * 60)

    # 测试模式
    if run_test:
        event_bus, config_manager, window_capture, detector, controller, scheduler = (
            create_application(config_path)
        )
        config = config_manager.get()
        run_basic_test(window_capture, detector, controller, config)
        return

    # 创建应用
    event_bus, config_manager, window_capture, detector, controller, scheduler = (
        create_application(config_path)
    )
    config = config_manager.get()

    # 启动配置热更新
    config_manager.start_watching()

    if no_gui:
        run_no_gui(
            event_bus, config_manager, window_capture, detector, controller, scheduler
        )
    else:
        run_gui(event_bus, window_capture, detector, controller, scheduler)


if __name__ == "__main__":
    main()
