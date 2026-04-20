#!/usr/bin/env python3
"""测试后台键盘鼠标输入 - 使用 Windows API."""

import os
import sys
import time

# 获取脚本所在目录的绝对路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

sys.path.insert(0, SCRIPT_DIR)

print("=" * 60)
print("后台键盘鼠标输入测试")
print("=" * 60)

try:
    import win32con
    import win32gui
    import win32api
    from infrastructure.logger import LoggerFactory
    
    LoggerFactory.setup(log_level="INFO")
    
    # 初始化
    print("\n[1/5] 查找元宝窗口...")
    from core.window_capture import WindowCapture
    
    capture = WindowCapture("元宝")
    found = capture.find_window()
    
    if found:
        hwnd = capture.hwnd
        size = capture.get_window_size()
        print(f"  ✓ 找到窗口")
        print(f"    句柄: {hwnd}")
        print(f"    大小: {size[0]}x{size[1]}")
    else:
        print("  ✗ 未找到窗口")
        sys.exit(1)
    
    # 将窗口带到前台
    print("\n[2/5] 激活窗口...")
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    print("  ✓ 窗口已激活")
    
    # 测试键盘输入 - 输入"你好"
    print("\n[3/5] 测试键盘输入 '你好'...")
    print("  提示: 请确保元宝窗口中有文本输入框被聚焦")
    time.sleep(2)  # 给用户时间聚焦输入框
    
    # 使用 WM_CHAR 消息发送中文字符
    def send_char(hwnd, char):
        """发送单个字符到窗口."""
        # 获取字符的 Unicode 码点
        code_point = ord(char)
        
        # 发送 WM_CHAR 消息
        win32api.PostMessage(hwnd, win32con.WM_CHAR, code_point, 0)
        time.sleep(0.05)  # 短暂延迟
    
    # 发送"你好"
    text = "你好"
    print(f"  发送文本: {text}")
    for char in text:
        send_char(hwnd, char)
        print(f"    ✓ 已发送: {char}")
    
    print("  ✓ 文本发送完成")
    
    # 测试回车键
    print("\n[4/5] 测试回车键...")
    time.sleep(1)
    
    # 发送回车键 (VK_RETURN = 0x0D)
    VK_RETURN = 0x0D
    win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, VK_RETURN, 0)
    time.sleep(0.05)
    win32api.PostMessage(hwnd, win32con.WM_KEYUP, VK_RETURN, 0)
    
    print("  ✓ 回车键已发送")
    
    # 测试鼠标点击
    print("\n[5/5] 测试鼠标点击...")
    time.sleep(1)
    
    # 在窗口中心点击
    center_x = size[0] // 2
    center_y = size[1] // 2
    
    print(f"  点击位置: ({center_x}, {center_y})")
    
    # 构建 LPARAM (x, y 坐标)
    lparam = (center_y << 16) | (center_x & 0xFFFF)
    
    # 发送鼠标左键点击
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.05)
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
    
    print("  ✓ 鼠标点击已发送")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("\n说明:")
    print("1. 文本 '你好' 已发送到元宝窗口")
    print("2. 回车键已发送")
    print("3. 窗口中心位置已点击")
    print("\n注意:")
    print("- 这些是后台消息，窗口不需要在前台")
    print("- 某些应用可能不响应后台消息")
    print("- 如果需要前台输入，可以使用 pyautogui")
    print("=" * 60)
    
except Exception as e:
    print(f"\n✗ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    input("\n按 Enter 退出...")
