#!/usr/bin/env python3
"""测试 PrintWindow 后台截图方法."""

import os
import sys
import cv2
import numpy as np

# 获取脚本所在目录的绝对路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

sys.path.insert(0, SCRIPT_DIR)

print("=" * 60)
print("PrintWindow 后台截图测试")
print("=" * 60)

try:
    # 初始化
    print("\n[1/3] 初始化窗口捕获器...")
    from core.window_capture import WindowCapture
    from infrastructure.logger import LoggerFactory
    
    LoggerFactory.setup(log_level="DEBUG")
    
    capture = WindowCapture("元宝")
    print("  ✓ 完成")
    
    # 查找窗口
    print("\n[2/3] 查找窗口...")
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
    
    # 测试截图
    print("\n[3/3] 测试 PrintWindow 截图...")
    frame = capture.capture()
    
    if frame is not None:
        print(f"  ✓ 截图成功")
        print(f"    图像大小: {frame.shape}")
        print(f"    图像类型: {frame.dtype}")
        
        # 保存截图
        output_path = os.path.join(SCRIPT_DIR, "test_printwindow.png")
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
            
        # 显示截图（可选）
        print(f"\n  提示: 请查看生成的截图文件")
        print(f"  文件位置: {output_path}")
        
    else:
        print("  ✗ 截图失败")
        print("\n请检查:")
        print("1. 窗口是否最小化")
        print("2. 是否有管理员权限")
        print("3. 窗口是否使用了特殊的渲染方式")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("\n查看日志文件了解详细信息:")
    print("  logs/rok_assistant.log")
    print("=" * 60)
    
except Exception as e:
    print(f"\n✗ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    input("\n按 Enter 退出...")
