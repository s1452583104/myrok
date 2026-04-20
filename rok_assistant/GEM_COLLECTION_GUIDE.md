# 宝石采集功能使用指南

## 概述

本指南介绍如何使用宝石采集功能，包括游戏启动管理和宝石采集两种模式。

## 功能特性

### 1. 游戏启动管理

- **自动启动**: 检测游戏是否运行，未运行时自动启动
- **自动登录**: 识别登录界面并自动点击登录按钮
- **进程监控**: 监控游戏进程状态，异常关闭后自动重启

### 2. 宝石采集

支持两种采集模式：

#### 重新派兵模式

- **流程**: 派遣→采集→召回→再派遣
- **特点**: 操作频率高，适合矿点距离近的场景
- **优势**: 部队频繁回城，安全性高
- **劣势**: 行军时间浪费，效率中等

#### 驻扎模式

- **流程**: 派遣→驻扎→持续采集→满载召回
- **特点**: 操作频率低，适合矿点距离远的场景
- **优势**: 无行军时间浪费，效率高
- **劣势**: 驻扎部队可能被攻击，风险中等

## 配置说明

### 游戏启动配置

在 `config.yaml` 中配置：

```yaml
game_launcher:
  game_path: "C:\\Program Files\\Rise of Kingdoms\\RiseOfKingdoms.exe"
  process_name: "RiseofKingdoms.exe"
  window_title: "万国觉醒"
  startup_timeout: 60
  login_check_delay: 10
  
  auto_login:
    enabled: true
    ocr_keywords:
      - "登录"
      - "登陆"
      - "开始游戏"
      - "Start Game"
      - "Login"
    login_button_position:
      x: 960
      y: 540
      w: 200
      h: 60
    max_retries: 3
    retry_interval: 5
  
  auto_restart:
    enabled: false
    check_interval: 30
```

### 宝石采集配置

在 `config.yaml` 中配置：

```yaml
automation:
  gem_collection:
    enabled: true
    mode: "redeploy"  # 或 "garrison"
    
    mine_coords:
      - x: 632
        y: "C9"
      - x: 645
        y: "D12"
      - x: 620
        y: "B8"
    
    teams:
      - team_id: 1
        commander: "贝利撒留"
        secondary_commander: "孙武"
        troop_type: "cavalry"
        troop_count: 10000
      
      - team_id: 2
        commander: "贞德"
        secondary_commander: "西庇阿"
        troop_type: "cavalry"
        troop_count: 10000
    
    redeploy_mode:
      recall_delay: 300      # 采集延迟(秒)
      redeploy_delay: 5      # 重新派遣延迟(秒)
    
    garrison_mode:
      check_interval: 600    # 检查满载间隔(秒)
      full_load_threshold: 0.95  # 满载阈值(95%)
```

## 使用方法

### 方法1: 运行集成示例

```bash
python gem_collection_demo.py
```

### 方法2: 在代码中使用

```python
from core import (
    GameLauncherManager,
    GemCollectionManager,
    WindowCapture,
    YOLODetector,
    BackgroundInputController,
)
from models.config import AppConfig

# 加载配置
config = AppConfig.from_dict({})

# 初始化组件
window_capture = WindowCapture(config.window.title)
yolo_detector = YOLODetector(...)
input_controller = BackgroundInputController(window_capture.hwnd)

# 游戏启动管理
game_launcher = GameLauncherManager(config.game_launcher)
game_launcher.initialize(window_capture)

# 宝石采集
if config.automation.gem_collection.enabled:
    gem_manager = GemCollectionManager(
        config.automation.gem_collection,
        window_capture,
        yolo_detector,
        input_controller,
    )
    gem_manager.start()
```

## 统计信息

宝石采集管理器会记录以下统计信息：

- **总宝石收益**: 累计采集的宝石数量
- **每小时宝石收益**: 平均每小时采集的宝石数量
- **派遣次数**: 总派遣部队次数
- **召回次数**: 总召回部队次数
- **驻扎次数**: 总驻扎部队次数
- **运行时间**: 采集功能运行的总时间

## 注意事项

1. **游戏路径**: 确保配置的游戏路径正确
2. **矿点坐标**: 需要手动配置有效的宝石矿点坐标
3. **武将配置**: 确保配置的武将名称正确
4. **兵种选择**: 推荐使用骑兵（cavalry）采集宝石
5. **后台操作**: 所有操作都在后台进行，不影响前台使用
6. **坐标映射**: 游戏坐标到屏幕坐标的映射可能需要调整

## 故障排除

### 游戏无法启动

- 检查游戏路径是否正确
- 确认游戏进程名称是否匹配
- 查看日志文件获取详细错误信息

### 自动登录失败

- 检查登录按钮位置是否正确
- 确认OCR关键词是否匹配
- 增加 `retry_interval` 和 `max_retries`

### 部队派遣失败

- 检查矿点坐标是否有效
- 确认武将名称是否正确
- 检查兵种和数量配置

### 采集效率低

- 检查采集模式是否合适
- 调整 `recall_delay` 或 `check_interval`
- 优化矿点坐标，选择距离近的矿点

## 性能指标

根据设计文档，预期性能指标：

- **重新派兵模式**: 单队列每小时≥120宝石
- **驻扎模式**: 自动驻扎成功率≥90%
- **满载检测**: 准确率≥95%
- **自动采集**: 成功率≥85%

## 下一步

1. 训练YOLO模型识别宝石矿点和采集按钮
2. 实现OCR引擎识别登录按钮
3. 优化坐标映射算法
4. 添加更多采集策略和优化
5. 实现多实例支持

## 相关文档

- [详细设计文档](详细设计文档.md)
- [需求文档](万国觉醒游戏辅助工具需求文档.md)
- [配置指南](CONFIG_GUIDE.md)
- [后台输入指南](BACKGROUND_INPUT_GUIDE.md)
