#!/usr/bin/env python3
"""测试"元宝"窗口的启动脚本."""

import os
import sys

# 获取脚本所在目录的绝对路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)  # 切换到脚本所在目录

print("=" * 60)
print("ROK Assistant - 元宝窗口测试")
print(f"工作目录: {SCRIPT_DIR}")
print("=" * 60)

# 确保可以导入项目模块
sys.path.insert(0, SCRIPT_DIR)

try:
    print("\n[1/6] 检查配置文件...")
    config_path = os.path.join(SCRIPT_DIR, "config_yuanbao.yaml")
    if os.path.exists(config_path):
        print(f"  ✓ 配置文件存在: {config_path}")
    else:
        print(f"  ✗ 配置文件不存在: {config_path}")
        sys.exit(1)
    
    print("\n[2/6] 初始化日志...")
    from infrastructure.logger import LoggerFactory
    LoggerFactory.setup(log_level="INFO")
    print("  ✓ 完成")
    
    print("\n[3/6] 创建应用...")
    from main import create_application
    event_bus, config_manager, window_capture, detector, controller, scheduler = (
        create_application(config_path)
    )
    print(f"  ✓ 完成 - 目标窗口: {window_capture.window_title}")
    
    print("\n[4/6] 查找窗口...")
    found = window_capture.find_window()
    if found:
        size = window_capture.get_window_size()
        print(f"  ✓ 找到窗口 - 大小: {size[0]}x{size[1]}")
    else:
        print(f"  ✗ 未找到包含'元宝'的窗口")
        print("  提示: 请先打开元宝应用，然后再运行此程序")
        print("  提示: 窗口标题需要包含'元宝'两个字")
    
    print("\n[5/6] 初始化 GUI...")
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    print("  ✓ 完成")
    
    print("\n[6/6] 创建并显示窗口...")
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
    
    # 自动启动画面捕获
    window._on_start()
    QApplication.processEvents()
    
    print("  ✓ 窗口已显示")
    print("  ✓ 画面捕获已自动启动")
    print("\n" + "=" * 60)
    print("测试程序已启动！")
    print("\n说明:")
    print("1. ✓ 左侧应该显示'元宝'窗口的实时画面")
    print("2. ✓ 画面捕获已自动启动")
    print("3. 点击'检测'按钮可以测试YOLO目标检测")
    print("4. 当前使用的是通用YOLOv8n模型（80个类别）")
    print("\n提示:")
    print("- 如果画面不显示，请检查截图文件 test_capture.png")
    print("- 可以调整 config_yuanbao.yaml 中的模型参数")
    print("  * confidence: 置信度阈值（降低可以检测更多对象）")
    print("  * 当前值: 0.6")
    print("=" * 60)
    
    sys.exit(app.exec())
    
except Exception as e:
    print(f"\n✗ 启动失败: {e}")
    import traceback
    traceback.print_exc()
    input("\n按 Enter 退出...")
    sys.exit(1)
