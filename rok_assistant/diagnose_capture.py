#!/usr/bin/env python3
"""诊断窗口捕获问题."""

import os
import sys
import cv2
import numpy as np

# 获取脚本所在目录的绝对路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

sys.path.insert(0, SCRIPT_DIR)

print("=" * 60)
print("窗口捕获诊断工具")
print("=" * 60)

try:
    # 初始化
    print("\n[1/4] 初始化窗口捕获器...")
    from core.window_capture import WindowCapture
    
    capture = WindowCapture("元宝")
    print("  ✓ 完成")
    
    # 查找窗口
    print("\n[2/4] 查找窗口...")
    found = capture.find_window()
    if found:
        hwnd = capture.hwnd
        size = capture.get_window_size()
        print(f"  ✓ 找到窗口")
        print(f"    句柄: {hwnd}")
        print(f"    大小: {size[0]}x{size[1]}")
        print(f"    DPI缩放: {capture.dpi_scale}")
    else:
        print("  ✗ 未找到窗口")
        sys.exit(1)
    
    # 尝试截图
    print("\n[3/4] 尝试截图...")
    frame = capture.capture()
    
    if frame is not None:
        print(f"  ✓ 截图成功")
        print(f"    图像大小: {frame.shape}")
        print(f"    图像类型: {frame.dtype}")
        
        # 保存截图
        output_path = os.path.join(SCRIPT_DIR, "test_capture.png")
        cv2.imwrite(output_path, frame)
        print(f"    已保存到: {output_path}")
        
        # 显示图像信息
        print(f"\n  图像统计:")
        print(f"    宽度: {frame.shape[1]}")
        print(f"    高度: {frame.shape[0]}")
        print(f"    通道: {frame.shape[2] if len(frame.shape) == 3 else 1}")
        
        # 检查是否是黑屏
        avg_brightness = np.mean(frame)
        print(f"    平均亮度: {avg_brightness:.2f}")
        
        if avg_brightness < 10:
            print(f"    ⚠ 警告: 图像很暗，可能是黑屏")
        elif avg_brightness < 50:
            print(f"    ⚠ 警告: 图像较暗")
        else:
            print(f"    ✓ 亮度正常")
            
    else:
        print("  ✗ 截图失败")
        print("\n可能的原因:")
        print("1. 窗口最小化了")
        print("2. 窗口被其他窗口完全遮挡")
        print("3. 窗口使用了特殊的渲染方式（如硬件加速）")
    
    # 尝试区域截图
    print("\n[4/4] 测试不同截图方法...")
    
    # 方法1: 使用 pyautogui
    try:
        import pyautogui
        import win32gui
        
        # 获取窗口位置
        left, top, right, bottom = win32gui.GetWindowRect(capture.hwnd)
        width = right - left
        height = bottom - top
        
        print(f"\n  方法1: pyautogui")
        print(f"    窗口位置: ({left}, {top}, {right}, {bottom})")
        print(f"    窗口大小: {width}x{height}")
        
        # 截图
        screenshot = pyautogui.screenshot(region=(left, top, width, height))
        screenshot_np = np.array(screenshot)
        screenshot_bgr = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)
        
        output_path2 = os.path.join(SCRIPT_DIR, "test_capture_pyautogui.png")
        cv2.imwrite(output_path2, screenshot_bgr)
        print(f"    ✓ 已保存到: {output_path2}")
        
    except Exception as e:
        print(f"    ✗ 失败: {e}")
    
    print("\n" + "=" * 60)
    print("诊断完成！")
    print("\n请检查生成的截图文件:")
    print("1. test_capture.png - 使用窗口捕获")
    print("2. test_capture_pyautogui.png - 使用pyautogui")
    print("\n如果截图是黑色的，可能需要:")
    print("- 确保窗口没有被最小化")
    print("- 尝试将窗口带到前台")
    print("- 检查窗口是否使用了硬件加速")
    print("=" * 60)
    
except Exception as e:
    print(f"\n✗ 诊断失败: {e}")
    import traceback
    traceback.print_exc()
    input("\n按 Enter 退出...")
