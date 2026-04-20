#!/usr/bin/env python3
"""后台输入完整演示 - 向元宝发送"你好"并回车."""

import os
import sys
import time

# 获取脚本所在目录的绝对路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

sys.path.insert(0, SCRIPT_DIR)

print("=" * 60)
print("后台输入演示 - 向元宝发送'你好'")
print("=" * 60)

try:
    # 导入后台输入控制器
    from core.background_input import BackgroundInputController
    from core.window_capture import WindowCapture
    from infrastructure.logger import LoggerFactory
    
    LoggerFactory.setup(log_level="INFO")
    
    # 步骤1: 查找窗口
    print("\n[步骤 1] 查找元宝窗口...")
    capture = WindowCapture("元宝")
    found = capture.find_window()
    
    if not found:
        print("  ✗ 未找到元宝窗口")
        sys.exit(1)
    
    hwnd = capture.hwnd
    size = capture.get_window_size()
    print(f"  ✓ 找到窗口")
    print(f"    句柄: {hwnd}")
    print(f"    大小: {size[0]}x{size[1]}")
    
    # 步骤2: 创建后台输入控制器
    print("\n[步骤 2] 创建后台输入控制器...")
    input_controller = BackgroundInputController(hwnd)
    print("  ✓ 控制器已创建")
    
    # 步骤3: 激活窗口（使窗口获得焦点）
    print("\n[步骤 3] 激活窗口...")
    import win32gui
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    print("  ✓ 窗口已激活")
    
    # 步骤4: 提示用户操作
    print("\n[步骤 4] 准备输入...")
    print("  请在 3 秒内:")
    print("  1. 确保元宝窗口中有文本输入框")
    print("  2. 点击输入框使其获得焦点")
    print("  3. 等待自动输入...")
    
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    
    # 步骤5: 发送文本"你好"
    print("\n[步骤 5] 发送文本 '你好'...")
    success = input_controller.send_text("你好")
    
    if success:
        print("  ✓ 文本发送成功")
    else:
        print("  ✗ 文本发送失败")
    
    # 等待一下
    time.sleep(1)
    
    # 步骤6: 发送回车键
    print("\n[步骤 6] 发送回车键...")
    success = input_controller.send_enter()
    
    if success:
        print("  ✓ 回车键发送成功")
    else:
        print("  ✗ 回车键发送失败")
    
    # 步骤7: 演示其他功能
    print("\n[步骤 7] 其他后台输入示例...")
    print("  演示: 鼠标点击窗口中心")
    
    center_x = size[0] // 2
    center_y = size[1] // 2
    
    time.sleep(1)
    input_controller.click(center_x, center_y)
    print(f"  ✓ 已点击 ({center_x}, {center_y})")
    
    # 完成
    print("\n" + "=" * 60)
    print("演示完成！")
    print("\n已执行的操作:")
    print("  1. ✓ 查找元宝窗口")
    print("  2. ✓ 创建后台输入控制器")
    print("  3. ✓ 激活窗口")
    print("  4. ✓ 发送文本 '你好'")
    print("  5. ✓ 发送回车键")
    print("  6. ✓ 鼠标点击窗口中心")
    print("\n技术说明:")
    print("  - 使用 Windows API (PostMessage)")
    print("  - 支持后台输入（窗口不需要在前台）")
    print("  - 支持中文字符")
    print("  - 支持键盘和鼠标操作")
    print("=" * 60)
    
except Exception as e:
    print(f"\n✗ 演示失败: {e}")
    import traceback
    traceback.print_exc()
    input("\n按 Enter 退出...")
