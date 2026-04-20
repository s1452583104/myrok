# 启动说明

## 在 Qoder 中运行 GUI

### 方式1：使用调试启动脚本（推荐，有详细输出）
```bash
cd e:\pyworkspace\todolist\rok_assistant
python debug_launch.py
```

### 方式2：正常运行
```bash
cd e:\pyworkspace\todolist\rok_assistant
python main.py
```

### 方式3：测试模式（不启动GUI）
```bash
cd e:\pyworkspace\todolist\rok_assistant
python main.py --test
```

### 方式4：无GUI模式
```bash
cd e:\pyworkspace\todolist\rok_assistant
python main.py --no-gui
```

## 如果窗口没有出现

1. **检查任务栏** - 窗口可能已最小化
2. **Alt+Tab 切换** - 窗口可能在后台
3. **查看终端输出** - 检查是否有错误信息
4. **检查日志** - 查看 `logs/rok_assistant.log`

## 常见问题

### Q: 窗口启动了但看不到
A: 窗口可能被其他窗口遮挡，尝试：
- 按 Alt+Tab 切换窗口
- 查看任务栏是否有 Python 或 ROK Assistant 图标

### Q: 提示找不到游戏窗口
A: 这是正常的，因为游戏没有运行。GUI 仍然会显示，只是无法进行截图和检测。

### Q: 模型加载失败
A: 已修复！现在使用 `yolov8n.pt` 预训练模型，应该可以正常加载。

## 测试 GUI 是否正常

运行简单的 GUI 测试：
```bash
python test_gui.py
```

如果能看到测试窗口，说明 PyQt6 工作正常。
