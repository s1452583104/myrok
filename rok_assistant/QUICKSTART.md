# ROK Assistant 快速开始指南

## 当前状态：M1-M3 完成

项目已完成基础框架和宝石采集MVP功能的开发。

## 快速验证（5分钟）

### 1. 安装依赖

```bash
cd rok_assistant
pip install -r requirements.txt
```

### 2. 运行测试

```bash
# 核心模块测试（8个测试）
python -m pytest test_core.py -v

# 集成测试（6个场景）
python test_integration.py
```

### 3. 检查项目结构

```bash
# 查看项目文件
ls -la
```

预期输出包含：
- `core/` - 窗口捕获和YOLO检测器
- `business/` - 游戏控制器和配置管理器
- `coordination/` - 事件总线和任务调度器
- `plugins/gem_collect/` - 宝石采集任务
- `gui/` - PyQt6主窗口
- `models/` - 数据模型
- `infrastructure/` - 日志和异常处理

## 下一步：准备真实模型

要运行实际的宝石采集功能，需要准备：

### 1. YOLO模型文件

MVP最小需求：
- 训练包含3个类别：`gem_mine`, `gather_btn`, `confirm_btn`
- 模型格式：PyTorch `.pt` 文件
- 放置路径：`models/current/rok_detector.pt`

### 2. 配置窗口标题

编辑 `config.yaml`：

```yaml
window:
  title: "你的游戏窗口标题关键词"  # 修改为你的游戏窗口标题
```

### 3. 启用宝石采集

```yaml
automation:
  gem_collect:
    enabled: true        # 改为 true
```

### 4. 启动程序

```bash
# GUI模式（推荐）
python main.py

# 无GUI模式
python main.py --no-gui
```

## 开发路线

- [x] M1: 基础框架（窗口捕获 + 基础GUI）
- [x] M2: YOLO检测（宝石矿识别）
- [x] M3: 宝石采集完整流程
- [ ] M4: 扩展到资源收集、建筑升级
- [ ] M5: 完整自动化 + 优化

## 获取帮助

- 查看 `README.md` 获取完整文档
- 查看 `详细设计文档.md` 获取架构设计
- 查看日志文件：`logs/rok_assistant.log`
