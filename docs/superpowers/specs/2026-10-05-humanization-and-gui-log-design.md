# 设计：每实例日志区 + 输入人性化层

日期：2026-10-05
状态：待评审

## 1. 背景与目标

两个独立诉求：

1. **GUI 增加每实例日志区**——现在出问题时只能去 `logs/*.log` 翻文件，界面卡片只有状态和缩略图。
2. **降低被检测概率**——用户账号**已被封禁/警告**（服务端行为分析，非客户端当场弹窗）。
   用户要求：检查随机偏移/随机延迟是否生效，并设计防检测机制，避免呆板固定的动作路径。

### 1.1 已核实的事实（不是推测）

| 事实 | 出处 |
|---|---|
| 随机化**已生效**：`debug_no_jitter: false`，每次点击 ±8px 偏移 + `uniform(3.1, 5.5)` 秒延迟 | `config.yaml:18-25`；`runtime.py:139` 给每台实例都包了 `JitteringHandleSource` |
| `state_delay_min/max`、`jitter_ratio` **是死配置**——无任何生产调用方，改了不生效也不报错 | 全仓 grep；`docs/PROGRESS.md` 已知问题 5 |
| `swipe` **完全没抖动**——`JitteringHandleSource.swipe` 是直通转发 | `anti_detection.py:62` |
| 存在**零抖动硬编码 sleep**：`1.5 / 1.5 / 1.2` 秒 | `state_machine.py:142,145,156` |
| 轮询间隔**精确恒定**：`_wait_for_result` 默认 1.0s、`_find_retry` 2.0s、返城徽标 30.0s | `state_machine.py:89-124`；`either_sm.py:14` |
| worker 线程**已有名字** `worker:<instance_id>:<char_id>` | `runner.py:117` |
| 每次状态变化都会 `logger.info("worker %s/%s[%s] -> %s")` | `runner.py:214` |
| `EventBus.publish` **同步**——订阅者在**发布者线程**里被调用 | `event_bus.py:20-27` |
| `rally_launched` 路由**立即**转发给成员 SM，无延迟 | `runtime.py:176-186` |

### 1.2 关键判断

**延迟分布本身是主要嫌疑。** 每次点击前恰好 `U(3.1, 5.5)`，**永不低于 3.1、永不超过 5.5**——这个硬下界 + 均匀分布比"随机性不足"更容易被识别。真人点击是突发式（连续快点几下）加长尾的。

**"固定动作路径"这条做不到字面意思。** 动作序列由游戏 UI 线性流程钉死（开搜索→设等级→搜索→点红集结→集结弹窗→预设→行军），**顺序无法随机化**——乱序就点不动。本设计能提供的是**时序去规律化**（每轮时间形状不同）与**冗余观察**，不是顺序随机。

## 2. 范围

### 做

- 每实例日志区（卡片内嵌）
- `HumanProfile` 策略对象；`JitteringHandleSource` 改为消费它
- 复活两个死配置字段（不新增同义字段）
- 延迟分布改造（Beta 截断 + 突发）
- 坐标散布改造（二维高斯 + 每目标 σ）
- 轮询间隔去规律化；固定 sleep 接抖动
- 两号解耦（成员号响应集结加随机延迟）

### 不做（YAGNI，理由随附）

| 不做 | 理由 |
|---|---|
| 会话内休息/作息层 | 用户手动跑、跑完就关。且该机器人本就有 25 分钟等返城的天然空档，再加休息是噪音 |
| 鼠标轨迹仿真 | 服务端在客户端之下，看不见轨迹 |
| 换注入方式（minitouch/sendevent） | 同上，对服务端模型无收益 |
| 概率性失误（点歪再纠正） | 会把状态机点乱，风险大于收益 |

## 3. 第 1 项：每实例日志区

### 3.1 归属规则

worker 线程名已经是 `worker:<instance_id>:<char_id>`（`runner.py:117`），**无需改动任何 worker 日志调用**：

1. 优先从线程名解析 `worker:*:*` → `char_id`
2. 解析不到（主线程：配置加载、连不上实例等）→ 落到**状态栏最后一行**，不进卡片

v1 每实例恰好 1 个角色（`runtime.py:140` 的 `inst.characters[:1]`），所以"按角色归属"与"按实例归属"等价。

### 3.2 组件

**新增 `src/rok_assistant/gui/log_handler.py`**

- `QtLogHandler(logging.Handler)`，同时是 `QObject`，持有 `pyqtSignal(str, str)`（`char_id`, 格式化后的行文本）
- `emit(record)`：解析 `threading.current_thread().name` → `char_id` → `self.record_emitted.emit(char_id, self.format(record))`
- 跨线程安全：worker 线程 `emit`，Qt 自动排队到主线程——与 `controller.py:89` 现有模式一致

**`MainWindow`**

- 构造时在 root logger 上 `addHandler(QtLogHandler)`，连接 `record_emitted` → `_on_log_line(char_id, text)`
- `_on_log_line`：`char_id` 为空 → `statusBar().showMessage(text)`；否则 `self._cards[char_id].append_log(text)`
- 卡片重建（`_rebuild_cards`）后 `_cards` 是新对象，槽按 `char_id` 现查即可，无需重连

**`CharacterCard`**

- 尺寸 220×280 → 约 220×430
- 新增只读 `QPlainTextEdit`，`setMaximumBlockCount(200)`（环形缓冲由 Qt 提供）
- `append_log(text)`：追加并滚到底

### 3.3 边界情况

- **无头驱动不受影响**：handler 在 `MainWindow.__init__` 里建，`_run_goal.py` 走不到
- **日志洪泛**：worker 日志频率低（状态变化 + 轮次事件，每分钟几条），200 行环形缓冲足够；不需要节流
- **主线程行**：只进状态栏，不污染卡片；`runtime.py:135` 的"连不上实例"错误会显示在状态栏

## 4. 第 2 项：HumanProfile + 节奏层

### 4.1 `HumanProfile`

`infra/anti_detection.py` 新增 `HumanProfile`：由 `AntiDetectionConfig` + **可注入的 `random.Random`** 构造（注入种子后测试完全可复现）。

对外方法：

| 方法 | 作用 |
|---|---|
| `click_delay()` | 点击前延迟，`action_delay_min/max` 内按 `delay_shape` 采样 + 突发分支 |
| `disperse(x, y, anchor)` | 二维高斯散布，σ 取 `anchor_sigma[anchor]`，缺省 `click_offset_px` |
| `poll_interval()` | 轮询间隔，从 `state_delay_min/max` 采样（无 base 参数——这两个字段是绝对值） |
| `jitter(base)` | 固定 sleep 的乘性抖动（`base ± base*jitter_ratio`） |
| `member_response_delay()` | 成员号响应集结的延迟 |
| `retry_attempts(base)` | 重试次数 `base + randint(-1, 1)`，下限 1 |

**`debug_no_jitter: true` 时全部方法返回确定性值**（延迟取中点、偏移取 0、轮询取中点），与现有语义一致——现有 `tests/unit/infra/test_anti_detection.py` 必须继续通过。

### 4.2 配置字段：复活而非新增

`AntiDetectionConfig` 现有 7 个字段**全部保留原名**，两个死字段被接上：

| 字段 | 现状 | 改后 |
|---|---|---|
| `click_offset_px` | ±N 像素方形均匀 | 变成**默认 σ**（二维高斯） |
| `action_delay_min/max` | `uniform` 延迟 | 保持为**边界**，采样改 Beta + 突发 |
| `state_delay_min/max` | **死** | 复活为**轮询间隔**（秒，绝对值）。默认由 `0.3/1.2` 调整为 `0.6/1.6`——0.3s 轮询意味着每 0.3 秒一次 screencap，而单次 adb 截图耗时 150~300ms，会打爆 adb 队列 |
| `jitter_ratio` | **死** | 复活，接到固定 sleep |
| `debug_no_jitter` | 生效 | 不变 |

新增字段（5 个）：

| 字段 | 默认 | 作用 |
|---|---|---|
| `delay_shape` | `"beta"` | `beta` \| `uniform`；后者是回退到旧行为的逃生口 |
| `burst_prob` | `0.3` | 走"连点"短间隔的概率 |
| `burst_scale` | `0.25` | 连点间隔 = `min + (max-min) * U(0, burst_scale)` |
| `anchor_sigma` | `{}` | 模板 id（如 `march_btn` / `preset_1`）→ σ 覆盖 |
| `member_response_delay_min/max` | `10.0 / 60.0` | 成员号响应延迟范围（秒） |

**Beta 形状**：硬编码 `Beta(2, 5)`（偏短、带长尾），不额外暴露 `a/b` 旋钮——两个旋钮换不来可调性收益。

`config.yaml` 与 `config.example.yaml` 需同步：新增 5 个字段；`state_delay_min/max` 改为 `0.6/1.6`；`config.example.yaml` 里三处「【当前不生效】」注释删除。

### 4.3 接线点

| 位置 | 改动 |
|---|---|
| `runtime.py:139` | `JitteringHandleSource(handle, profile)` 传 profile 而非裸 config |
| `runtime.py:161` | `create_state_machine(...)` 增加 `human=profile` 参数 |
| `factory.py:9` | `create_state_machine` 增加 `human=None` 形参，透传给三个 SM |
| `handle_source.py:19` | `HandleSource.click` 增加**可选** `anchor: str \| None = None` 形参。全部实现（Adb / Win32 / Mock / Replay）接受并忽略；`MockHandleSource.clicks` 仍记 `(x, y)`，现有断言不受影响 |
| `anti_detection.py:57` | `JitteringHandleSource.click(x, y, anchor=None)` —— 延迟与 `profile.disperse(x, y, anchor)` **都在这里做**，SM 不再自己散布（否则双重抖动） |
| `state_machine.py:68-87` | `_click_result` 把识别到的模板 id 作为 `anchor` 传下去；`_click_xy` 传自己的目标名 |
| `state_machine.py:89-124` | `_wait_for_result` / `_find_retry` / `_click_retry` 的 `interval` 默认值由 `1.0` 改为 `None`；`None` 表示走 `profile.poll_interval()`。显式传 `interval=1.0` 的调用点（`member_sm.py:228,265`）改为不传以取得抖动；`switcher_sm.py:102` 的 `2.0` **保留**——那是"等切换完成"的语义，不是轮询节奏 |
| `state_machine.py:142,145,156` | `time.sleep(1.5/1.5/1.2)` → `time.sleep(profile.jitter(...))` |
| `anti_detection.py:62` | `swipe` 补抖动 |
| `runner.py:167,193` | 冷却 30s / poll 2s → `profile.jitter(...)` |
| `either_sm.py:14` | 返城徽标 30s → `profile.jitter(...)` |

### 4.4 两号解耦（本设计收益最大的一条）

**问题**：`runtime.py:176-186` 的 `_make_router` 收到 `rally_launched` 立即转发给成员 SM。两台模拟器在**同一台机器**上、**永远成对出现**、**严格 lockstep**（一台开集结，另一台 N 秒内必然响应）——这是很强的跨账号关联信号。

**约束**：`EventBus.publish` 是**同步**的（`event_bus.py:20-27`），订阅者在**发布者线程**（车头的 worker 线程）里被调用。因此**延迟不能加在 `_make_router` 里**——那会阻塞车头线程 10~60 秒。

**做法**：延迟放在**成员 SM 自己**的线程里。

- `on_rally_launched(event)` 不再立即推进状态，改为记录 `self._respond_at = time.time() + profile.member_response_delay()`
- `WAIT_LAUNCH_EVENT` 状态的 `step()` 在 `time.time() < self._respond_at` 时**原地返回**，不动
- 车头本就在 `LEADER:WAIT_MEMBERS` 等待，成员晚 10~60 秒填兵不影响流程

### 4.5 「路径」这条实际给了什么

用户点名要"避免固定动作路径"。能做与不能做：

- ✅ **每轮时间形状不同**：轮询抖动 + 延迟分布 + 重试间隔抖动
- ✅ **重试次数可变**：`_find_retry(attempts=3)` → 2~4（`profile.retry_attempts`）
- ✅ **冗余观察**：语义等价处偶尔多截一帧再确认（无害的犹豫）
- ❌ **顺序随机化**：UI 线性流程钉死，做不到

## 5. 诚实边界：本设计治不了什么

**代码能改的是"手"，改不了"行为"。** 对服务端行为模型，以下信号可能强于点击节奏，且**不在本设计射程内**：

1. **玩法规律**：两号每次都是同样的城寨等级、同样的目标、每轮流程逐字相同、连续数小时零社交互动
2. **账号/设备指纹**：两个账号跑在同一台机器、同一 IP、同一设备指纹
3. **轮次规律**：每次都是恰好跑满 10 轮就停

**本设计不保证能躲过 RoK 的具体风控。** 上述三条需要靠"改变玩法"而不是改代码来缓解（例如错开两号的登录/在线时段、轮换目标等级、不要每次都在同一时间点跑满同样的轮数）。

## 6. 测试策略

| 层次 | 用例 |
|---|---|
| 单元 · 分布 | 注入固定种子 → 断言延迟样本**不是均匀分布**（如 Beta(2,5) 的偏度/均值偏离中点）；样本落在 `[min,max]` 内 |
| 单元 · 突发 | 种子可控下 `burst_prob=1.0` → 全部走短间隔；`0.0` → 全部走常规 |
| 单元 · 坐标 | 高斯散布的样本标准差 ≈ 给定 σ；`anchor_sigma` 覆盖生效；越界裁剪 |
| 单元 · 确定性 | `debug_no_jitter=True` → 全部方法返回确定值（**现有 `test_anti_detection.py` 继续通过**） |
| 单元 · 轮询 | `_wait_for_result` 的轮询间隔随种子变化，且落在 `state_delay` 范围内 |
| 单元 · 解耦 | `on_rally_launched` 后 `_respond_at` 落在 `member_response_delay_*` 范围内；未到时间 `step()` 不推进状态 |
| 单元 · 固定 sleep | `_refill_ap` / `_close_ap_dialog` 的 sleep 走 `jitter()`（用假 sleep 断言被调用） |
| 集成 · 日志归属 | worker 线程发一条 log → 对应卡片的日志区收到；主线程发一条 → 进状态栏、不进卡片 |

回归：`pytest tests/ -q` 全套必须绿（当前 661 条）。

## 7. 兼容性与回滚

- **配置向后兼容**：7 个现有字段全部保留原名与语义；`state_delay_*` 的默认值变了（`0.3/1.2` → `0.6/1.6`），但字段名和"秒"的含义不变
- **逃生口**：`debug_no_jitter: true` 一键回到完全确定性的旧行为；`delay_shape: "uniform"` 单独回退延迟分布
- **无头驱动**：只多了一个未安装的日志 handler 和若干随机化，行为语义不变
- **回滚**：改动集中在 `anti_detection.py` / `state_machine.py` / `factory.py` / `runtime.py` / `gui/`，无 schema 迁移、无数据迁移
