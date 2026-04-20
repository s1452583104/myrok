#!/usr/bin/env python3
"""逐步调试启动 - 找出问题所在."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("逐步调试启动...")
print("=" * 60)

try:
    print("\n[步骤 1] 初始化日志...")
    from infrastructure.logger import LoggerFactory, get_logger
    LoggerFactory.setup(log_level="INFO")
    logger = get_logger("step_debug")
    print("  ✓ 完成")
    
    print("\n[步骤 2] 创建事件总线...")
    from coordination.event_bus import EventBus
    event_bus = EventBus()
    print("  ✓ 完成")
    
    print("\n[步骤 3] 加载配置...")
    from business.config_manager import ConfigManager
    config_manager = ConfigManager("config.yaml", event_bus)
    config = config_manager.load()
    print(f"  ✓ 完成 - 窗口标题: {config.window.title}")
    
    print("\n[步骤 4] 创建窗口捕获器...")
    from core.window_capture import WindowCapture
    window_capture = WindowCapture(config.window.title)
    print("  ✓ 完成")
    
    print("\n[步骤 5] 创建YOLO检测器...")
    from core.yolo_detector import YOLODetector
    detector = YOLODetector(
        model_path=config.model.path,
        confidence_threshold=config.model.confidence,
        iou_threshold=config.model.iou_threshold,
        input_size=config.model.input_size,
        device=config.model.device,
    )
    print("  ✓ 完成")
    
    print("\n[步骤 6] 加载模型...")
    loaded = detector.load_model()
    print(f"  ✓ 完成 - 模型加载: {'成功' if loaded else '失败'}")
    
    print("\n[步骤 7] 创建游戏控制器...")
    from business.game_controller import GameController, SafetyConfig
    safety_config = SafetyConfig(
        min_delay=config.safety.min_delay,
        max_delay=config.safety.max_delay,
        random_offset=config.safety.random_offset,
        click_duration=config.safety.click_duration,
        max_actions_per_minute=config.safety.max_actions_per_minute,
    )
    controller = GameController(window_capture, safety_config)
    print("  ✓ 完成")
    
    print("\n[步骤 8] 创建任务调度器...")
    from coordination.task_scheduler import TaskScheduler
    scheduler = TaskScheduler(event_bus)
    print("  ✓ 完成")
    
    print("\n[步骤 9] 初始化 PyQt6 QApplication...")
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    print("  ✓ 完成")
    
    print("\n[步骤 10] 创建主窗口...")
    from gui.main_window import MainWindow
    
    window = MainWindow(
        event_bus=event_bus,
        capture_func=window_capture.capture,
        detector=detector,
        game_controller=controller,
        task_runner=lambda: None,
    )
    print("  ✓ 完成")
    
    print("\n[步骤 11] 显示窗口...")
    window.show()
    window.raise_()
    window.activateWindow()
    QApplication.processEvents()
    print("  ✓ 窗口已显示")
    
    print("\n" + "=" * 60)
    print("所有步骤完成！GUI应该已经显示。")
    print("按 Ctrl+C 退出")
    print("=" * 60)
    
    sys.exit(app.exec())
    
except Exception as e:
    print(f"\n✗ 错误: {e}")
    import traceback
    traceback.print_exc()
    input("\n按 Enter 退出...")
    sys.exit(1)
