# 万国觉醒游戏辅助工具

基于计算机视觉的Windows平台游戏辅助工具，通过YOLO目标检测和OCR文字识别技术识别游戏界面元素，结合PyQt构建图形用户界面，支持多游戏实例同时运行。

## 功能特性

- **游戏界面元素识别**：自动识别按钮、建筑、武将、资源点等
- **文字信息识别**：通过OCR识别资源数量、建筑等级、武将信息等文字内容
- **自动化操作**：自动采集资源、自动升级建筑、自动训练军队
- **多开支持**：同时管理多个游戏实例，独立配置和运行自动化任务
- **资源管理**：智能提醒建筑升级、科研完成、资源满仓
- **插件系统**：支持扩展功能插件

## 技术栈

- **GUI框架**：PyQt6
- **深度学习**：YOLOv8 (Ultralytics)
- **图像处理**：OpenCV
- **OCR引擎**：PaddleOCR (可选)
- **自动化控制**：PyAutoGUI + pywin32
- **配置管理**：PyYAML
- **日志系统**：logging

## 安装依赖

```bash
# 安装基础依赖
pip install -r requirements.txt

# 可选：安装OCR依赖
pip install paddleocr paddlepaddle
```

## 配置文件

修改 `config.yaml` 文件配置游戏参数：

```yaml
window:
  title: "万国觉醒"  # 游戏窗口标题
  process_name: "RiseofKingdoms.exe"

model:
  path: "models/current/rok_detector.pt"  # YOLO模型路径
  confidence: 0.6  # 置信度阈值
  input_size: 640  # 输入尺寸
  device: "cpu"  # 运行设备 (cpu/cuda)

# 其他配置...
```

## 运行程序

```bash
# 启动辅助工具
python main.py
```

## 目录结构

```
rok_assistant/
├── main.py                # 主程序入口
├── config.yaml            # 配置文件
├── requirements.txt       # 依赖列表
├── core/                  # 核心能力层
│   ├── window_capture.py  # 窗口捕获
│   ├── yolo_detector.py   # YOLO检测器
│   ├── input_controller.py # 输入控制
│   └── image_processor.py # 图像处理
├── business/              # 业务逻辑层
│   ├── config_manager.py  # 配置管理
│   ├── detection_service.py # 检测服务
│   ├── game_controller.py # 游戏控制
│   └── automation_engine.py # 自动化引擎
├── coordination/          # 协调层
│   ├── event_bus.py       # 事件总线
│   ├── task_scheduler.py  # 任务调度
│   └── plugin_manager.py  # 插件管理
├── plugins/               # 插件目录
│   ├── base_plugin.py     # 插件基类
│   └── gem_collect/       # 宝石采集插件
├── gui/                   # 界面层
│   ├── main_window.py     # 主窗口
│   ├── settings_dialog.py # 设置对话框
│   ├── debug_window.py    # 调试窗口
│   └── log_panel.py       # 日志面板
├── models/                # 数据模型
│   ├── task.py            # 任务模型
│   ├── detection.py       # 检测模型
│   ├── game_element.py    # 游戏元素模型
│   └── config.py          # 配置模型
├── infrastructure/        # 基础设施层
│   ├── logger.py          # 日志系统
│   ├── exception_handler.py # 异常处理
│   ├── cache.py           # 缓存系统
│   └── state_manager.py   # 状态管理
└── resources/             # 资源文件
    ├── models/            # 模型文件
    └── icons/             # 图标文件
```

## 注意事项

1. **反作弊**：本工具使用模拟人工操作的方式，添加了随机延迟和偏移，以减少被检测的风险
2. **分辨率**：支持1920×1080和2560×1440分辨率
3. **权限**：需要管理员权限运行
4. **模型**：需要YOLO模型文件才能进行目标检测
5. **多开**：支持最多5个游戏实例同时运行

## 开发说明

### 添加新插件

1. 在 `plugins` 目录下创建新的插件文件夹
2. 创建 `plugin.py` 和 `strategy.py` 文件
3. 继承 `BasePlugin` 类实现插件逻辑
4. 在 `strategy.py` 中实现具体的任务策略

### 模型训练

1. 收集游戏界面截图
2. 使用标注工具标注目标
3. 使用 Ultralytics YOLO 训练模型
4. 将训练好的模型放入 `models/current/` 目录

## 免责声明

本工具仅供学习和研究使用，请勿用于任何违反游戏规则的行为。使用本工具产生的一切后果由使用者自行承担。