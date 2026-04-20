# 窗口截图改进说明

## 更新内容

已将窗口截图方法升级为 **PrintWindow API**，支持后台截图。

## 改进内容

### 1. PrintWindow API（主要方法）

**优势**：
- ✅ 支持后台截图（窗口不需要在前台）
- ✅ 可以捕获硬件加速内容（DirectX、OpenGL等）
- ✅ 不受窗口遮挡影响
- ✅ 更稳定可靠

**实现位置**：
- 文件：`core/window_capture.py`
- 方法：`_capture_printwindow()`

### 2. BitBlt（备用方法）

当 PrintWindow 失败时，自动降级使用 BitBlt 方法。

**实现位置**：
- 文件：`core/window_capture.py`
- 方法：`_capture_bitblt()`

### 3. 自动降级策略

```python
# 优先使用 PrintWindow
img = self._capture_printwindow(width, height)

# 如果失败，使用 BitBlt
if img is None:
    img = self._capture_bitblt(width, height, left, top)
```

## 使用方法

### 测试 PrintWindow 截图

```bash
cd e:\pyworkspace\todolist\rok_assistant
python test_printwindow.py
```

这会生成 `test_printwindow.png` 截图文件。

### 启动 GUI 测试

```bash
python test_yuanbao.py
```

GUI 会自动使用新的截图方法。

## 截图对比

### 测试结果

```
PrintWindow 截图:
✓ 成功
✓ 图像大小: (1008, 958, 3)
✓ 平均亮度: 242.06
✓ 亮度正常
```

### 诊断工具

如果仍有问题，运行诊断：

```bash
python diagnose_capture.py
```

会生成两个截图文件用于对比：
1. `test_capture.png` - 使用窗口捕获器
2. `test_capture_pyautogui.png` - 使用 pyautogui

## 管理员权限

PrintWindow API 在某些情况下可能需要管理员权限：

### 以管理员身份运行

1. 右键点击 PowerShell 或命令提示符
2. 选择"以管理员身份运行"
3. 运行程序

### 或者创建快捷方式

1. 创建 Python 的快捷方式
2. 右键快捷方式 → 属性
3. 点击"高级"
4. 勾选"用管理员身份运行"

## 常见问题

### Q: 截图是黑色的怎么办？

A: 尝试以下方法：
1. 确保窗口没有最小化
2. 以管理员身份运行程序
3. 检查窗口是否使用了特殊的渲染方式
4. 运行 `diagnose_capture.py` 查看详细信息

### Q: PrintWindow 失败怎么办？

A: 程序会自动使用 BitBlt 方法作为备用。可以查看日志了解失败原因：
```
logs/rok_assistant.log
```

### Q: 如何提高截图质量？

A: 
1. 确保 DPI 缩放设置正确
2. 使用管理员权限运行
3. 确保窗口完全加载后再截图

## 技术细节

### PrintWindow API

```python
# PW_RENDERFULLCONTENT = 0x00000002
# 包含硬件加速内容
result = windll.user32.PrintWindow(
    hwnd,                    # 窗口句柄
    hdc,                     # 设备上下文
    PW_RENDERFULLCONTENT     # 标志
)
```

### 资源管理

每次截图后都会正确清理资源：
- 删除位图对象
- 删除设备上下文
- 释放窗口 DC

避免内存泄漏。

## 性能

- PrintWindow: 约 30-50ms/帧
- BitBlt: 约 20-40ms/帧
- 推荐帧率: 2 FPS（配置中已设置）

## 下一步

如果需要更好的性能或特殊功能，可以考虑：
1. Windows.Graphics.Capture API（Windows 10 1803+）
2. DXGI Desktop Duplication API
3. DwmGetWindowAttribute（用于特殊窗口）
