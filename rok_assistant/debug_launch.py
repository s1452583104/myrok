#!/usr/bin/env python3
"""调试启动脚本 - 显示详细的启动信息."""

import os
import sys

# 确保可以导入项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("启动调试模式...")
print("=" * 60)

try:
    print("\n[1/6] 导入模块...")
    from infrastructure.logger import LoggerFactory, get_logger
    LoggerFactory.setup(log_level="DEBUG")
    logger = get_logger("debug_launcher")
    print("  ✓ 日志系统初始化成功")
    
    print("\n[2/6] 创建应用组件...")
    from main import create_application
    event_bus, config_manager, window_capture, detector, controller, scheduler = (
        create_application("config.yaml")
    )
    print("  ✓ 应用组件创建成功")
    
    # 注意：不启动配置监视，避免在某些环境下阻塞
    # config_manager.start_watching()
    
    print("\n[3/6] 检查 PyQt6...")
    try:
        from PyQt6.QtWidgets import QApplication
        print("  ✓ PyQt6 可用")
    except ImportError as e:
        print(f"  ✗ PyQt6 导入失败: {e}")
        sys.exit(1)
    
    print("\n[4/6] 初始化 QApplication...")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    print("  ✓ QApplication 初始化成功")
    
    print("\n[5/6] 创建主窗口...")
    from gui.main_window import MainWindow
    from models.config import AppConfig
    
    window = MainWindow(
        event_bus=event_bus,
        capture_func=window_capture.capture,
        detector=detector,
        game_controller=controller,
        task_runner=lambda: None,  # 简化版，不启动任务
    )
    print("  ✓ 主窗口创建成功")
    
    print("\n[6/6] 显示窗口...")
    
    # 确保窗口显示在最前面
    window.show()
    window.raise_()  # 将窗口提到最前
    window.activateWindow()  # 激活窗口
    
    # 强制处理事件，确保窗口立即显示
    QApplication.processEvents()
    
    print("  ✓ 窗口已显示")
    print("\n提示: 请检查任务栏，窗口可能已最小化")
    
    print("\n" + "=" * 60)
    print("GUI 已启动！请检查任务栏是否有窗口。")
    print("按 Ctrl+C 退出")
    print("=" * 60)
    
    sys.exit(app.exec())
    
except Exception as e:
    print(f"\n✗ 启动失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
