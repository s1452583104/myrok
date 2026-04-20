# 后台键盘鼠标输入说明

## 概述

已实现使用 Windows API 进行后台键盘和鼠标输入的功能。

## 核心技术

### Windows API 消息

使用 `PostMessage` API 发送窗口消息：

- **WM_CHAR** - 字符输入
- **WM_KEYDOWN** - 按键按下
- **WM_KEYUP** - 按键释放
- **WM_LBUTTONDOWN** - 鼠标左键按下
- **WM_LBUTTONUP** - 鼠标左键释放
- **WM_RBUTTONDOWN** - 鼠标右键按下
- **WM_RBUTTONUP** - 鼠标右键释放
- **WM_MOUSEMOVE** - 鼠标移动

## 使用方法

### 1. 快速测试

```bash
cd e:\pyworkspace\todolist\rok_assistant
python test_background_input.py
```

这会：
1. 查找元宝窗口
2. 发送"你好"
3. 发送回车键
4. 点击窗口中心

### 2. 完整演示

```bash
python demo_background_input.py
```

有详细的步骤说明和倒计时。

### 3. 在自己的代码中使用

```python
from core.background_input import BackgroundInputController
from core.window_capture import WindowCapture

# 查找窗口
capture = WindowCapture("元宝")
capture.find_window()

# 创建控制器
controller = BackgroundInputController(capture.hwnd)

# 发送文本
controller.send_text("你好")

# 发送回车
controller.send_enter()

# 鼠标点击
controller.click(100, 200)
```

## 功能列表

### 键盘输入

| 方法 | 说明 | 示例 |
|------|------|------|
| `send_char(char)` | 发送单个字符 | `send_char('A')` |
| `send_text(text)` | 发送文本 | `send_text('你好')` |
| `send_key_press(vk)` | 发送按键 | `send_key_press(0x0D)` |
| `send_enter()` | 发送回车 | `send_enter()` |
| `send_escape()` | 发送ESC | `send_escape()` |
| `send_tab()` | 发送TAB | `send_tab()` |
| `send_space()` | 发送空格 | `send_space()` |

### 鼠标输入

| 方法 | 说明 | 示例 |
|------|------|------|
| `click(x, y)` | 鼠标点击 | `click(100, 200)` |
| `double_click(x, y)` | 双击 | `double_click(100, 200)` |
| `move_mouse(x, y)` | 移动鼠标 | `move_mouse(100, 200)` |
| `drag(x1, y1, x2, y2)` | 拖拽 | `drag(0, 0, 100, 100)` |

### 常用键码

```python
from core.background_input import VKCodes

VKCodes.VK_RETURN    # 回车
VKCodes.VK_ESCAPE    # ESC
VKCodes.VK_TAB       # TAB
VKCodes.VK_SPACE     # 空格
VKCodes.VK_BACK      # 退格
VKCodes.VK_DELETE    # Delete
VKCodes.VK_UP        # 上箭头
VKCodes.VK_DOWN      # 下箭头
VKCodes.VK_LEFT      # 左箭头
VKCodes.VK_RIGHT     # 右箭头
VKCodes.VK_F1~F12    # F1-F12
```

## 优势

### 后台输入 ✅

- 窗口不需要在前台
- 不影响用户其他操作
- 可以后台自动化

### 支持中文 ✅

- 使用 WM_CHAR 消息
- 支持 Unicode 字符
- 完美支持中文输入

### 精确控制 ✅

- 可以指定精确坐标
- 支持各种键盘鼠标操作
- 灵活的组合操作

## 限制

### 应用兼容性

某些应用可能不响应后台消息：

- 游戏可能使用 DirectInput
- 某些应用可能忽略后台消息
- UWP 应用可能有限制

### 解决方案

如果后台输入不工作：

1. **使用前台输入** - pyautogui
2. **先激活窗口** - SetForegroundWindow
3. **尝试不同的消息** - WM_CHAR vs WM_KEYDOWN

## 测试方法

### 测试后台输入

```bash
python test_background_input.py
```

### 测试前台输入

使用现有的游戏控制器：

```python
from business.game_controller import GameController, SafetyConfig
from core.window_capture import WindowCapture

capture = WindowCapture("元宝")
capture.find_window()

safety = SafetyConfig()
controller = GameController(capture, safety)

# 前台输入
controller.safe_click(100, 200)
controller.safe_key_press('enter')
```

## 示例代码

### 示例1: 输入文本并回车

```python
from core.background_input import BackgroundInputController
from core.window_capture import WindowCapture
import time

# 查找窗口
capture = WindowCapture("元宝")
capture.find_window()

# 创建控制器
controller = BackgroundInputController(capture.hwnd)

# 激活窗口
import win32gui
win32gui.SetForegroundWindow(capture.hwnd)
time.sleep(0.5)

# 输入文本
controller.send_text("你好世界")
time.sleep(0.5)

# 发送回车
controller.send_enter()
```

### 示例2: 鼠标操作

```python
# 点击
controller.click(100, 200)

# 双击
controller.double_click(100, 200)

# 拖拽
controller.drag(100, 100, 200, 200)
```

### 示例3: 组合键

```python
# Ctrl+C
controller.send_key_down(VKCodes.VK_CONTROL)
controller.send_char('c')
controller.send_key_up(VKCodes.VK_CONTROL)
```

## 文件位置

- **后台输入控制器**: `core/background_input.py`
- **测试脚本**: `test_background_input.py`
- **演示脚本**: `demo_background_input.py`
- **游戏控制器**: `business/game_controller.py` (前台输入)

## 下一步

可以扩展的功能：

1. **快捷键支持** - 组合键
2. **宏录制** - 记录和操作重放
3. **输入队列** - 异步输入处理
4. **错误恢复** - 自动重试机制
5. **日志记录** - 详细的输入日志

## 注意事项

⚠️ **重要提示**：

1. 某些应用可能需要管理员权限
2. 游戏可能使用反作弊系统
3. 后台输入可能被某些应用阻止
4. 使用时请遵守应用的使用条款

## 故障排除

### 问题：字符没有发送成功

**解决方案**：
1. 确保窗口已激活
2. 确保输入框有焦点
3. 尝试先点击输入框

### 问题：鼠标点击没有响应

**解决方案**：
1. 检查坐标是否正确
2. 尝试使用前台输入
3. 检查窗口是否接受后台消息

### 问题：中文显示为乱码

**解决方案**：
1. 确保使用 WM_CHAR 消息
2. 检查系统编码设置
3. 尝试逐个字符发送
