# 万国觉醒游戏辅助工具 - ROK Assistant

基于计算机视觉的《万国觉醒》(Rise of Kingdoms) 游戏辅助工具, 通过YOLO目标检测识别游戏界面元素, 实现自动化宝石采集等功能.

## 功能特性

- **窗口捕获**: 自动查找游戏窗口并截取画面
- **YOLO检测**: 识别宝石矿、采集按钮等游戏元素
- **安全操作**: 随机延迟和偏移, 模拟人类操作
- **宝石采集**: 自动检测宝石矿并完成采集流程
- **任务调度**: 支持定时触发、条件触发、手动触发
- **实时预览**: GUI实时显示游戏画面和检测结果
- **配置驱动**: 所有参数通过config.yaml配置
- **日志系统**: 完善的运行日志记录

## 项目结构

```
rok_assistant/
├── main.py                         # 程序入口
├── config.yaml                     # 配置文件
├── requirements.txt                # 依赖列表
├── test_core.py                    # 核心功能测试
│
├── core/                           # 核心能力层
│   ├── window_capture.py           # 窗口捕获
│   └── yolo_detector.py            # YOLO检测器
│
├── business/                       # 业务逻辑层
│   ├── game_controller.py          # 游戏交互控制
│   └── config_manager.py           # 配置管理器
│
├── coordination/                   # 协调层
│   ├── event_bus.py                # 事件总线
│   └── task_scheduler.py           # 任务调度器
│
├── plugins/                        # 插件目录
│   └── gem_collect/                # 宝石采集插件
│       └── task.py                 # 宝石采集任务
│
├── gui/                            # 表现层
│   └── main_window.py              # 主窗口
│
├── models/                         # 数据模型
│   ├── config.py                   # 配置模型
│   └── detection.py                # 检测结果模型
│
└── infrastructure/                 # 基础设施层
    ├── logger.py                   # 日志系统
    └── exception_handler.py        # 异常处理
```

## 环境要求

- Python 3.10+
- Windows 10/11
- 《万国觉醒》PC版 (模拟器或官方PC版)

## 安装

### 1. 安装依赖

```bash
cd rok_assistant
pip install -r requirements.txt
```

### 2. 准备YOLO模型

将训练好的YOLO模型文件放置到指定路径:

```
models/current/rok_detector.pt
```

MVP阶段所需的最小检测类别:
- `gem_mine` - 宝石矿
- `gather_btn` - 采集按钮
- `confirm_btn` - 确认按钮

### 3. 配置参数

编辑 `config.yaml` 文件:

```yaml
window:
  title: "万国觉醒"          # 你的游戏窗口标题关键词

model:
  path: "models/current/rok_detector.pt"  # 模型路径
  confidence: 0.6                          # 置信度阈值

safety:
  min_delay: 0.05        # 操作最小间隔
  max_delay: 0.3         # 操作最大间隔
  random_offset: 5       # 点击随机偏移

automation:
  gem_collect:
    enabled: true        # 启用宝石采集
    min_level: 5         # 最低采集等级
    check_interval: 300  # 检查间隔(秒)
```

## 使用

### 启动GUI模式

```bash
python main.py
```

GUI界面包含:
- 游戏画面实时预览
- 检测结果叠加显示
- 开始/停止控制
- 运行日志面板

### 无GUI模式 (仅日志)

```bash
python main.py --no-gui
```

### 运行基础测试

```bash
python main.py --test
```

测试项目:
1. 窗口查找
2. 截图功能
3. 模型加载
4. 安全配置

### 运行核心模块测试

```bash
python test_core.py
```

测试覆盖:
- 日志系统
- 事件总线
- 配置模型
- 检测模型
- 异常体系
- 安全配置
- 任务调度器
- 配置验证器

### 运行集成测试

```bash
python test_integration.py
```

集成测试验证:
- 检测流程端到端
- 游戏控制器安全点击
- 宝石采集任务完整流程
- 任务调度器集成
- 事件总线通信
- 异常处理机制

## 宝石采集流程

```
触发采集任务
    │
    ▼
检查游戏窗口 ──失败──> 等待/报警
    │成功
    ▼
截取游戏画面
    │
    ▼
YOLO检测宝石矿
    │
    ├─否──> 重新搜索
    │
   找到
    │
    ▼
判断宝石矿等级 ──<min_level──> 跳过
    │>=min_level
    ▼
点击宝石矿
    │
    ▼
检测采集按钮 ──否──> 失败
    │是
    ▼
点击采集按钮
    │
    ▼
选择军队 (MVP简化)
    │
    ▼
确认采集
    │
    ▼
等待采集完成
    │
    ▼
发布采集完成事件
```

## 安全机制

| 机制 | 实现 |
|------|------|
| 随机延迟 | 每次操作添加 50-300ms 随机延迟 |
| 随机偏移 | 点击位置添加 ±5px 随机偏移 |
| 操作间隔 | 两次操作间保持 1-3s 间隔 |
| 频率限制 | 每分钟最大操作数限制 (默认30次) |
| 失败重试 | 检测失败自动重试 (最多3次) |
| 安全暂停 | 连续失败后暂停任务 |

## 配置说明

### config.yaml 完整配置

```yaml
window:
  title: "万国觉醒"
  process_name: "RiseofKingdoms.exe"

model:
  path: "models/current/rok_detector.pt"
  confidence: 0.6
  input_size: 640
  iou_threshold: 0.45
  device: "cpu"

safety:
  min_delay: 0.05
  max_delay: 0.3
  random_offset: 5
  click_duration: 0.1
  max_actions_per_minute: 30

automation:
  gem_collect:
    enabled: false
    min_level: 5
    collect_radius: 10
    army_count: 1
    army_type: "infantry"
    check_interval: 300
    max_concurrent: 3

logging:
  level: "INFO"
  file: "logs/rok_assistant.log"
  max_size: 10485760
  backup_count: 5
```

## 开发

### 代码规范

- 遵循 PEP 8 编码规范
- 所有函数包含类型注解
- 所有模块包含 docstring
- 关键操作记录日志

### 架构设计

采用五层架构:
1. **表现层**: PyQt6 GUI
2. **协调层**: 事件总线、任务调度
3. **业务逻辑层**: 自动化引擎、游戏控制
4. **核心能力层**: 窗口捕获、YOLO检测
5. **基础设施层**: 日志、异常处理

### 事件驱动

模块间通过 EventBus 通信:
- `EngineStartedEvent` / `EngineStoppedEvent` - 引擎状态
- `TaskCompletedEvent` / `TaskFailedEvent` - 任务结果
- `DetectionCompletedEvent` - 检测结果
- `WindowFoundEvent` / `WindowLostEvent` - 窗口状态
- `ConfigChangedEvent` - 配置变更

## 免责声明

本工具仅供学习研究使用. 使用自动化工具可能违反游戏服务条款, 请自行承担使用风险.

## License

MIT License
