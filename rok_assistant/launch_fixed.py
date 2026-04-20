#!/usr/bin/env python3
"""修复版启动脚本 - 使用绝对路径."""

import os
import sys

# 获取脚本所在目录的绝对路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)  # 切换到脚本所在目录

print("=" * 60)
print("ROK Assistant - 修复版启动")
print(f"工作目录: {SCRIPT_DIR}")
print("=" * 60)

# 确保可以导入项目模块
sys.path.insert(0, SCRIPT_DIR)

try:
    print("\n[1/5] 检查配置文件...")
    config_path = os.path.join(SCRIPT_DIR, "config.yaml")
    if os.path.exists(config_path):
        print(f"  ✓ 配置文件存在: {config_path}")
    else:
        print(f"  ✗ 配置文件不存在: {config_path}")
        sys.exit(1)
    
    print("\n[2/5] 初始化日志...")
    from infrastructure.logger import LoggerFactory
    LoggerFactory.setup(log_level="INFO")
    print("  ✓ 完成")
    
    print("\n[3/5] 创建应用...")
    from main import create_application
    event_bus, config_manager, window_capture, detector, controller, scheduler = (
        create_application(config_path)
    )
    print("  ✓ 完成")
    
    print("\n[4/5] 初始化 GUI...")
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    print("  ✓ 完成")
    
    print("\n[5/5] 创建并显示窗口...")
    from gui.main_window import MainWindow
    
    window = MainWindow(
        event_bus=event_bus,
        capture_func=window_capture.capture,
        detector=detector,
        game_controller=controller,
        task_runner=lambda: None,
    )
    
    # 确保窗口显示
    window.show()
    window.raise_()
    window.activateWindow()
    QApplication.processEvents()
    
    print("  ✓ 窗口已显示")
    print("\n" + "=" * 60)
    print("GUI 已启动！请查看窗口。")
    print("如果窗口被遮挡，请按 Alt+Tab 切换")
    print("=" * 60)
    
    sys.exit(app.exec())
    
except Exception as e:
    print(f"\n✗ 启动失败: {e}")
    import traceback
    traceback.print_exc()
    input("\n按 Enter 退出...")
    sys.exit(1)
