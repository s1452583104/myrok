# 万国觉醒游戏助手 · 设计稿

**项目名**：万国觉醒（RoK）游戏助手 — `rok-assistant`  
**范围**：第一期（v1）  
**作者**：brainstorm 设计稿  
**状态**：已批准，待实施  
**日期**：2026-07-05  
**仓库基线**：`363c1a1 清空重做`

---

## 1. 目标与范围

### 1.1 目标

做一个**同 PC 多开模拟器**运行的《万国觉醒》游戏辅助工具，自动化"**打寨子**"玩法：
- 用户配置多个账号 + 多个角色
- 工具自动控制其中一个角色当"**车头**"发起集结
- 工具自动控制其他角色当"**成员**"加入该集结
- 全程无需人工介入

### 1.2 范围（v1 = 本 spec）

**做**：
- 安卓模拟器（第一期支持 MuMu）上的句柄捕获、截图、后台点击
- 单个 Account 内多 Character 角色切换
- 模板匹配 + OCR + 选择性 YOLO 的混合识别
- "打寨子"完整流程：搜索 → 发起 → 等待成员加入 → 出发
- PyQt6 GUI（启动/停止/状态/日志/缩略图/配置）
- YAML 配置（账号/角色/行为参数）
- 失败自动重试 + 跳过下一目标

**不做**（明确 YAGNI）：
- ❌ 采集宝石（**延期 v2**）
- ❌ PC 官方客户端支持（**延期 v2**）
- ❌ 行为仿真 / 防封（v1 仅轻度：随机延时 + 随机偏移；不仿真鼠标轨迹、不做夜休）
- ❌ 多套模板（仅 1920×1080 中文）
- ❌ 跨机器/跨进程协调
- ❌ 大模型识别
- ❌ CLI 模式 / WebUI
- ❌ 自动选将 / 自动选 leader（玩家配置）
- ❌ 通知系统（邮件/微信/系统通知）

---

## 2. 决策表（来自 brainstorm 阶段）

| # | 维度 | 决策 |
|---|---|---|
| D1 | 项目定位 | 完全推倒重新设计 |
| D2 | 运行平台 | v1：仅安卓模拟器（PC 客户端 v2） |
| D3 | 识别方案 | 模板匹配 + OCR 为主，YOLO 仅在"战争界面 rally 列表"场景启用 |
| D4 | 玩法范围 | v1：只做"打寨子"。采集宝石 v2 |
| D5 | 多账号 | 同 PC 多开模拟器，进程内存共享 |
| D6 | Worker 粒度 | 每个 Character 一个 Worker |
| D7 | 任务互斥 | 玩法互斥（v1 只有一个玩法） |
| D8 | 成员策略 | 成员全权自动加入、出发；按角色粒度 |
| D9 | 运行方式 | PyQt6 GUI |
| D10 | 失败处理 | 自动重试下一目标（被锁、人没满、不能加入都跳过） |
| D11 | 防封策略 | 轻度：随机延时 + 点击位置随机偏移（防机器行为检测） |
| D12 | 模板库 | 单套：1920×1080 中文 UI |

---

## 3. 架构总览

### 3.1 分层

```
┌──────────────────────────────────────────────────────────────┐
│  PyQt6 GUI 层                                                 │
│  - 启动/停止 / 模式选择 / 状态总览 / 日志 / 配置             │
├──────────────────────────────────────────────────────────────┤
│  协调层 (Coordinator)                                        │
│  - RallySession: 一次「打寨子」会话                          │
│  - ScreenScheduler: 多角色共享单模拟器画面的串行调度器       │
│  - EventBus: 跨角色消息总线（rally_launched 等）             │
├──────────────────────────────────────────────────────────────┤
│  业务层 (Character Worker)                                   │
│  - LeaderStateMachine / MemberStateMachine /                 │
│    SwitcherStateMachine                                       │
├──────────────────────────────────────────────────────────────┤
│  核心能力层 (Core)                                            │
│  - HandleSource (per Account)                                │
│  - RecognizerChain                                           │
│  - TemplateRegistry                                          │
├──────────────────────────────────────────────────────────────┤
│  基础设施层 (Infra)                                           │
│  - Config / Logger / Path                                    │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 核心模型

- **Account**（一个 Android 模拟器窗口）= 1 个 `HandleSource` + 多个 `Character`
- **Character Worker** = 1 个游戏角色 = 独立状态机
- **Process = 1 个主进程**持有所有 Worker（in-memory 协调）

### 3.3 数据流（一次"打寨子"会话）

```
[GUI 启动] 
  → 加载 Account+Character 配置
  → 给每个 Account 启动 1 个 HandleSource
  → 给每个 Character 启动 1 个 Worker
  → Coordinator 选一个 Character 当车头，其余为成员

[Coordinator] 
  → 通知车头 Worker: start_session(rally_id, target_level)
  → 车头进入 LeaderStateMachine

[Leader SM] 
  → 搜索 → 选等级 → 点目标 → 点红色集结
  → 等「集结进攻」弹窗（识别锁定 = 后检法）
  → 选时间 → 点蓝色集结
  → 「组建部队」弹窗：选 preset + 兵种
  → 点「行军」  ← 关键里程碑
  → 通知 EventBus: rally_launched { ... }

[Member SM × N] 
  → 订阅 rally_launched
  → ScreenScheduler 排队（同一画面一次 1 个）
  → 轮到 → 切角色（SwitcherStateMachine）
  → 联盟 → 战争 → 改排序 → 筛选/选最近 → 点加入
  → 组建部队：选 preset + 兵种
  → 点「行军」
  → 切回原角色（如果有）
```

---

## 4. 核心模块

### 4.1 `HandleSource`（每 Account 一个）

**职责**：提供截图和点击能力。上层只看到 numpy 数组 + 像素坐标。

**接口**：
```python
class HandleSource(Protocol):
    def capture() -> np.ndarray       # BGR 格式
    def click(x: int, y: int) -> None
    def swipe(...) -> None
    def is_alive() -> bool
```

**v1 实现**：Android 模拟器
- `FindWindowW` 拿句柄（标题用 `window_title_pattern` 正则）
- `PrintWindow` 截图（避免遮挡）
- `PostMessage(WM_LBUTTONDOWN/UP)` 后台点击
- **线程安全**（ScreenScheduler 串行化）

**v2 实现**：PC 客户端（延期）
- 句柄获取同
- 截图用 `BitBlt` 到兼容 DC
- 点击同

### 4.2 `RecognizerChain`（识别策略链）

**接口**：
```python
class Recognizer(Protocol):
    def recognize(screenshot: np.ndarray) -> RecognizeResult

class RecognizerChain:
    def __init__(self, recognizers: list[Recognizer], threshold: float = 0.85)
    def recognize(screenshot: np.ndarray) -> RecognizeResult
```

**预置 Recognizer**：

| 类型 | 适用 | 例子 |
|---|---|---|
| `TemplateMatch` | 找固定按钮/图标 | 搜索按钮、Tab、+/-、×关闭 |
| `OCRText` | 找特定文字 | "集结"、"加入"、"距离最近" |
| `OCRNumber` | 读数字 | "4公里"、"224,675/2,000,000" |
| `OCRSpecificField` | 读坐标 | "X:546 Y:574" |
| `YoloDetect` | 找不定数量目标 | rally 卡片（1-几十个） |
| `YoloClassify` | 分类 | "+" 图标 vs 其他绿 + |

**策略链示例**：
```python
# 找"搜索按钮"
chain = RecognizerChain([TemplateMatch(template="search_icon.png", threshold=0.9)])

# 战争界面找 rally 卡片
chain = RecognizerChain([YoloDetect(model="rally_card.onnx", threshold=0.7)])
```

### 4.3 `ScreenScheduler`（共享画面调度器）

**问题**：一个 Account 画面同一时刻只能被一个 Worker 操作。

**接口**：
```python
class ScreenScheduler:
    def request(worker_id: str, action: Callable[[], T], priority: int = 0) -> Future[T]
    def cancel_pending(worker_id: str)
```

**调度策略**：
- FIFO 队列 + 优先级（车头 > 成员）
- 成员 Worker 必须取令牌才能执行
- 动作结束立刻释放

### 4.4 `EventBus`（in-process 同步事件）

```python
class EventBus:
    def subscribe(event: str, handler: Callable)
    def publish(event: str, payload: dict)
```

**事件清单**：

| 事件 | 发布者 | 订阅者 | payload |
|---|---|---|---|
| `rally_launched` | Leader SM | 全部 Member SM | rally_id, leader_char, fortress_id, prep_deadline |
| `rally_completed` | Coordinator | GUI | rally_id, status |
| `char_switched` | Switcher SM | Coordinator | from_char, to_char |
| `recognition_failed` | 任意 Worker | Logger | worker_id, scene, last_screenshot_path |

### 4.5 StateMachine

**A. LeaderStateMachine**（车头）
```
IDLE → SEARCH_FORTRESS → SELECT_LEVEL → CONFIRM_SEARCH 
      → CHECK_RESULT → SELECT_RALLY_TIME → FORM_TROOP 
      → LAUNCH → WAIT_MEMBERS → END
```

- `WAIT_MEMBERS`：**被动等待**。Worker 不做截图/点击动作，只在 EventBus 订阅 `rally_completed` 事件，倒计时归零后游戏自动出发，session 结束。
- `END`：Worker 切回 IDLE，可被 Coordinator 再次触发。

**B. MemberStateMachine**（成员）
```
IDLE → WAIT_LAUNCH_EVENT → SWITCH_TO_SELF → OPEN_ALLIANCE 
      → OPEN_WAR → SORT_BY_NEAREST → FILTER → CLICK_JOIN 
      → FORM_TROOP → LAUNCH → SWITCH_BACK → END
```

**C. SwitcherStateMachine**（角色切换）
```
IDLE → OPEN_PROFILE → OPEN_SETTINGS → OPEN_CHAR_MGMT 
      → PICK_CHAR → VERIFY → END
```

**状态→动作映射写在 YAML 里**（玩家可调）：

```yaml
# leader_states.yaml
states:
  SEARCH_FORTRESS:
    description: 点搜索按钮
    recognizer: search_icon
    action: click_center
    timeout: 5
    on_success: SELECT_LEVEL
    on_failure: RECOVERY
```

---

## 5. UI 流程（来自用户截图）

### 5.1 车头发起

| 步骤 | UI 操作 | 来源截图 |
|---|---|---|
| 1 | 主城 → 点左下角 🔍 搜索 | `060a09ed8570539fbf76bdbc64efdc08.png` |
| 2 | 选「野蛮人城寨」Tab → 选等级 → 搜索 | `49bd12f36af6b0ab4ae1dfa1a0bc4044.jpg` |
| 3 | 详情弹窗 → 点红色「集结」（**后检法**识别锁定：等 5 秒看「集结进攻」弹窗是否出现） | `4857c51999ce51e3a06552c73b5b24c4.jpg`、`da01f28c36d6e26d415a4b9a9d0a10a4.jpg` |
| 4 | 「集结进攻」弹窗 → 选 5 分钟 → 点蓝色「集结」 | `ff4c83c5973c4a00bf6d8da6a584e8e4.jpg` |
| 5 | 「组建部队」弹窗 → 选 preset（1-5）→ 选兵种 → 点「行军」 | `609d418e880a18c114c319598a70ef2b.png` |
| 6 | 等待成员加入，倒计时结束自动出发 | — |

**关键规则**：
- 03:07:27 倒计时 = 城寨自动消失倒计时（**不是**锁定倒计时）
- 锁定识别 = 后检法：点红色集结 → 等「集结进攻」弹窗 → 不出现 = 被锁
- ⭐ 五角星 = 与打寨子锁定**无关**
- 右上「派遣队列 0/5」= 账号总出征队列
- 兵种只支持 步兵/骑兵/弓兵（不投石机）

### 5.2 角色切换（4 层深路径）

| 步骤 | UI 操作 | 来源截图 |
|---|---|---|
| 1 | 主界面左上角头像 → 点击 | `602773e3ddc8985c8c49873f1233a73b.jpg` |
| 2 | 「执政官资料」弹窗 → 「设置」按钮（右下） | `b7ac20d2d5a8b10f8154949c280396c3.jpg` |
| 3 | 「设置」弹窗 → 「角色管理」按钮（中排左二） | `40d25589ae44fed638c58a443c71dea2.jpg` |
| 4 | 「角色管理」弹窗 → 点目标角色 | `41f4326ca39c3ff9e12a062f07fbe348.jpg` |

**注意**：
- 当前角色带绿色 ✅
- 每次切换 4 次点击 + 加载等待
- OCR 验证：切换后读左上角名字确认

### 5.3 成员加入

| 步骤 | UI 操作 | 来源截图 |
|---|---|---|
| 1 | 切到 member character | （同 5.2） |
| 2 | 主界面 → 底部「联盟」按钮 | `c1bc464230e15683b736778951c279ce.jpg` |
| 3 | 「联盟」界面 → 「战争」按钮（左上第一格） | `4d8dc0ad18c8987eef5ca72dae6b0329.jpg` |
| 4 | 「战争」界面 → 把「最新发起」改「距离最近」 | `23d54ccda651958cc393f6985d41a91b.jpg` |
| 5 | 选 rally（按 `fill_target_leaders` 策略） | 同上 |
| 6 | 点「+」加入 → 组建部队（同车头步骤 5） | — |
| 7 | 切回原角色 | — |

**rally 卡片字段**（OCR 需读）：
- 发起人名字（左侧旗帜）
- 距离
- 兵种图标
- 容量 X/总数
- 倒计时
- 目标寨子（右侧旗帜）

---

## 6. 配置 Schema

```yaml
# config.yaml

app:
  screen_width: 1920
  screen_height: 1080
  locale: zh-CN
  log_dir: ./logs
  template_dir: ./templates
  anti_detection:           # D11 详细说明见第 8 节
    click_offset_px: 8
    action_delay_min: 0.1
    action_delay_max: 0.5
    state_delay_min: 0.3
    state_delay_max: 1.2
    jitter_ratio: 0.3
    debug_no_jitter: false

accounts:
  - id: account_482A
    window_title_pattern: "MuMuPlayer-1.*"
    characters:
      - id: char_leader
        name: "阐珊爱拉野"
        role: leader
        target_level: 8
        march_preset: 1
        march_troop_types: [infantry, archer]

      # march_preset 必须是 1-5 整数（对应游戏内「组建部队」弹窗
      # 顶部的 5 个预设槽）。不设 = 用游戏当前已激活的预设。

      - id: char_jy
        name: "Jy、阐珊"
        role: member
        target_level: 6
        march_preset: 2
        march_troop_types: [infantry, cavalry, archer]
        fill_target_leaders: nearest

      - id: char_tian1
        name: "阐珊填1"
        role: member
        target_level: 5
        march_preset: 3
        march_troop_types: [infantry]
        fill_target_leaders:
          - { account: account_482A, name: "阐珊爱拉野" }

      - id: char_tian2
        name: "阐珊填2"
        role: member
        target_level: 4
        march_preset: 3
        march_troop_types: [cavalry]
        fill_target_leaders: nearest
```

**校验规则**（启动时强校验）：
- 每个 Account 至少 1 个 `leader`
- `target_level` 在 1-10
- `fill_target_leaders` 是 `nearest` 或非空 list
- Account 内 `name` 不重复
- `march_preset` 是 1-5 整数

**校验失败行为**：GUI 弹错误对话框，**拒绝启动**。错误消息必须指出是哪个字段、哪条记录、为什么错。

**模板清单**（`templates/manifest.yaml`）：
```yaml
templates:
  - id: search_icon
    file: search_icon.png
    roi: [10, 660, 100, 760]   # [x1, y1, x2, y2]，像素坐标
    threshold: 0.9
  - id: barbarian_fortress_tab
    file: tab_barbarian_fortress.png
    roi: full
    threshold: 0.92
  # ... (15 张左右)
  - id: rally_card_v1
    file: rally_card_classifier.onnx
    type: yolo_detect
    classes: [rally_card]
    threshold: 0.7
```

**ROI 格式**：
- `[x1, y1, x2, y2]`：矩形区域（像素坐标，左上→右下）
- `full`：全图（不做裁剪）
- 留空/不写：默认 `full`

---

## 7. 错误处理

| 错误 | 处理 | 重试次数 | 重试后 |
|---|---|---|---|
| 识别失败（按钮找不到） | 重试 | 3 | 跳过本步 / 跳过本 rally / 跳过本 session |
| 弹窗未出现（点红集结 5 秒无「集结进攻」） | 关闭 + ▶ 下一只 | — | 循环 |
| 被锁提示（"您的联盟已经..."） | 同上 | — | ▶ 下一只 |
| OCR 数字错误 | 前后两次值交叉验证 | — | 失败则放弃本次填兵 |
| 模拟器窗口消失 | 暂停所有 Worker | — | 等用户重启 + 恢复 |
| rally 倒计时结束没满员 | 不报错 | — | 集会自动解散，下次重试 |
| 切角色失败（OCR 名字不对） | 重新走 4 步 | 2 | 报错到 GUI |

**Fail-Soft 原则**（D10）：
- 永远不要让一个角色卡死整个流程
- 任何失败 = 跳过目标，不是停止全部
- 失败超阈值 → GUI 红色高亮

---

## 8. 防封机制（D11：轻度）

### 8.1 策略：随机延时 + 随机偏移

**目的**：避免操作节奏过于机械（同一时间间隔 + 同一点击位置），降低被游戏风控系统检测为"外挂脚本"的概率。

### 8.2 实现位置

集中在 `HandleSource` 层，**所有点击和操作都走这个层**。Worker 状态机调用 `handle_source.click(x, y)` 时，**坐标会先被偏移**，**再 sleep 一段随机时间**。

### 8.3 点击位置随机偏移

```python
# HandleSource.click 实际行为：
def click(self, x: int, y: int):
    # 偏移范围：以 (x, y) 为中心，矩形 [-offset_px, +offset_px] 内随机
    offset = config.anti_detection.click_offset_px  # 默认 8 像素
    x_jitter = x + random.randint(-offset, offset)
    y_jitter = y + random.randint(-offset, offset)
    # 限制偏移不超出 ROI
    x_jitter = clamp(x_jitter, roi.x1, roi.x2)
    y_jitter = clamp(y_jitter, roi.y1, roi.y2)
    self._raw_click(x_jitter, y_jitter)
```

**设计要点**：
- 偏移 **8 像素**（按钮通常 50-100 像素，8 像素偏移在按钮内视觉上察觉不到，但坐标不完全相同）
- **不能**偏移到按钮外面（用 ROI 框定）
- 不做"鼠标轨迹仿真"（直线点击），因为 Win32 `PostMessage` 本身没有轨迹概念

### 8.4 随机延时

**两类延时**：

| 延时 | 位置 | 范围 | 目的 |
|---|---|---|---|
| **操作间延时**（per action） | 每次 `click`/`swipe` 后 | 0.1 - 0.5 秒（默认） | 模拟人手反应时间 |
| **状态间延时**（per state） | 每个 State 转移后 | 0.3 - 1.2 秒（默认） | 避免节奏过于规律 |

```python
# 例：Leader SM 状态机配置
states:
  SEARCH_FORTRESS:
    recognizer: search_icon
    action: click_center
    delay_after: 0.5  # 状态结束后 sleep 0.3-0.7 秒
  CHECK_RESULT:
    recognizer: rally_attack_popup  # 等「集结进攻」弹窗
    action: wait_for
    timeout: 5
    delay_after: 1.0
```

**随机性实现**：每次实际 sleep = `delay_after + random.uniform(-jitter, jitter)`，jitter 默认 = delay_after × 30%。

### 8.5 配置项（YAML）

```yaml
# app 节下新增：
app:
  anti_detection:
    click_offset_px: 8          # 随机偏移半径
    action_delay_min: 0.1       # 最小操作间延时
    action_delay_max: 0.5       # 最大操作间延时
    state_delay_min: 0.3        # 最小状态间延时
    state_delay_max: 1.2        # 最大状态间延时
    jitter_ratio: 0.3           # 随机性比例（30%）
    # debug 模式（测试时用）—— 关闭所有随机化
    debug_no_jitter: false
```

### 8.6 不做什么（v1）

- ❌ **鼠标轨迹仿真**（点击之间不是直线）
- ❌ **夜休**（夜间不操作）
- ❌ **长时间不操作**（避免被识别为挂机）
- ❌ **HTTP 代理 / VPN**
- ❌ **设备指纹伪装**

理由：v1 只做"轻度"，避免过度工程。**如果上线后真被风控，再加 v2 升级**。

### 8.7 测试影响

- 单元测试：设 `debug_no_jitter: true`，所有延时 = 固定值，断言稳定
- 集成测试：默认有 jitter，用**均值/方差**断言而不是**精确值**
- 手动验收：跑 10 次完整 session，看是不是每次点击位置/间隔都不同

---

## 9. GUI（PyQt6）

```
┌──────────────────────────────────────────────────────┐
│ [启动] [停止]  [模式: 集结 ▼]  [刷新配置]  [日志]      │
├──────────────────────────────────────────────────────┤
│ 账号 482A (1 个模拟器)                                │
│  ┌──────────┬──────────┬──────────┐                  │
│  │阐珊爱拉野│ Jy、阐珊 │阐珊填1   │                  │
│  │车头     │ 成员     │ 成员     │                  │
│  │状态: 等待│状态: 寻位│状态: 待机│                  │
│  │ [缩略]   │ [缩略]   │ [缩略]  │                  │
│  └──────────┴──────────┴──────────┘                  │
├──────────────────────────────────────────────────────┤
│ 日志面板（底部）                                       │
│ [10:23:45] leader: 命中 search_icon                  │
│ [10:23:47] member_jy: 切角色 阐珊填1 → 阐珊爱拉野    │
└──────────────────────────────────────────────────────┘
```

**关键交互**：
- 每张角色卡有实时截图缩略（1-2 秒刷新）
- 缩略图右键 → 强制重置 / 查看详细日志
- 模式选择（v1 只有"打寨子"，v2 加"采集宝石"）
- 角色卡片变红 = 出错

---

## 10. 测试

### 9.1 分层

| 层级 | 工具 | 范围 |
|---|---|---|
| Unit | `pytest` | 状态机单步、Recognizer、Config、EventBus |
| Integration | `pytest` + 录制截图 | 状态机完整链路 |
| Visual regression | 自写脚本 | 模板/YOLO 准确率 |
| Manual | 你本人 | 全流程 + 异常 |

### 9.2 截图录制回放

```bash
# 录制
python tools/record.py --account account_482A --char char_leader
# 0.5 秒/帧 → recordings/session_<ts>/

# 回放
@pytest.mark.integration
def test_leader_full_session():
    session = ReplaySession("recordings/2026-07-15_leader_session")
    for frame in session.frames:
        sm.feed_screenshot(frame.image)
        assert sm.current_state in EXPECTED_STATES[frame.timestamp]
```

### 9.3 手动验收清单

- [ ] 启 1 个模拟器 + 1 角色，跑到发起 1 次集结
- [ ] 加 1 成员角色，验证自动切角色 + 加集结
- [ ] 故意造"被锁"状态 → 助手跳过 + 找下一只
- [ ] 故意造"集结点没满" → 助手重发
- [ ] 模拟器窗口关掉 → 助手暂停 + 不崩
- [ ] 给不存在的高等级（如 11）→ 配置校验拒绝
- [ ] 角色名改错 → 切角色后 OCR 验证失败 + 自动重试
- [ ] 日志里每步识别/点击都有记录 + 失败时截图存档

---

## 11. 里程碑

| ID | 内容 | 工时 |
|---|---|---|
| M0 | 项目脚手架 | 0.5 天 |
| M1 | 句柄捕获 + 截图 + 点击（含 D11 随机偏移） | 2 天 |
| M2 | 模板库（玩家手动采） | 1-2 小时 |
| M3 | 车头状态机 | 2-3 天 |
| M4 | 角色切换 | 1-2 天 |
| M5 | 成员状态机 + RallySession | 3-4 天 |
| M6 | 错误处理 + 重试 | 1-2 天 |
| M7 | GUI | 2-3 天 |
| M8 | 验收 + 修补 | 2-3 天 |
| **合计** | | **~3-4 周** |

---

## 12. 风险

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| 模板频繁失效（游戏更新） | 高 | 中 | 模板独立管理 + 失效快速采集 |
| 4 步角色切换路径耗时太长 | 中 | 中 | 调度器串行化、批量操作合并 |
| rally 列表 YOLO 检测 mAP 不够 | 中 | 中 | 回退 OCR + 截屏筛选 |
| 模拟器后台点击被风控 | 中 | 高 | D11 轻度防封（随机延时 + 偏移），严重时再上 v2 |
| 随机偏移导致点错按钮 | 低 | 中 | ROI 钳制 + 单元测试覆盖 |
| `PrintWindow` 截屏黑屏 | 低 | 高 | 回退 `BitBlt` |

---

## 13. v2 预告（不在本 spec）

- 采集宝石玩法
- PC 客户端支持
- 多套模板（多分辨率/多语言）
- 跨机器/跨进程协调
- 行为仿真 / 防封

---

## 附录 A：用户提供的 UI 截图

所有截图来自 `C:/个人应用/wechat/cache/xwechat_files/wxid_qsllfoxpatod22_a59a/temp/RWTemp/2026-07/`，已在第 5 节列出。

## 附录 B：用户的实际账号结构

| 角色 | 战力 | 用途 |
|---|---|---|
| 阐珊爱拉野 | 1.4 亿 | 车头 |
| Jy、阐珊 | 6,200 万 | 成员 |
| 阐珊填1 | 3,300 万 | 成员 |
| 阐珊填2 | 2,400 万 | 成员 |

## 修订记录

- 2026-07-18: 加入「轻度防封」机制（D11 从 0 改为：随机延时 + 随机偏移），新增第 8 节详细说明。
