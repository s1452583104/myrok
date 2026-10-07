# 防检测加固与运维闭环 · 设计稿

**项目名**：万国觉醒（RoK）游戏助手 — `rok-assistant`
**范围**：v1.1 加固（不动主流程骨架）
**状态**：待评审
**日期**：2026-10-07
**仓库基线**：`1eb9936 fix: 填兵车头判据改由配置驱动，换车头不再需要改 manifest`

---

## 1. 背景与目标

### 1.1 触发

用户收到风控警告邮件，**判据只笼统写「检测到异常/自动化」，没有点名任何具体行为**。

因此本设计不猜判据，回到通用原则：**消除机器签名**——机器签名最典型的两种是
「**固定步数**」和「**固定间隔**」。凡是让动作序列变得更像人手的改动都做；
凡是把动作钉成常量的改动都不做，哪怕它能提速。

### 1.2 四条用户诉求与设计结论

| # | 用户诉求 | 结论 |
|---|---|---|
| 1 | 智能识别当前寨子等级，不要固定步数 | **做**，且是本设计的核心 |
| 2 | 加快速率 + 记住点击坐标复用 | **提速不做**（见 §2 D6/D7）；**坐标缓存不做** |
| 3 | 轮数可配置 + 完成后自动 stop | **做**（缺口在 GUI，不在配置） |
| 4 | Start 时先自动做一次连接测试 | **做** |

### 1.3 现状硬事实（均已核对代码）

**① 第 3 项基本已实现，只是没接到界面上。**
`max_rounds` 早就是配置项（`infra/config.py:99`，默认 10），但配置对话框里**一个
字段都没有**（`gui/config_dialog.py` 无 `max_rounds`）——只能在 yaml 里手改。
「完成后自动变 stop」是真缺口：runner 跑满轮数后置 `done` 并退出主循环
（`workers/runner.py:201-214`），但 GUI 的 `_on_status_changed` 只更新卡片文字
（`gui/main_window.py:160-163`），Start/Stop 按钮**永远停在「运行中」**。

**② 第 2 项的「加快速率」已经是可配的。**
动作延迟下限/上限就在配置界面上（`gui/config_dialog.py:236-239`），当前
`config.yaml` 是 3.1–5.5s。用户要的「下限秒数」就是 `action_delay_min`。

**③ 第 1 项的零件已经躺在那儿，只是没接进运行时。**
`zhaizi_level_text` 是数据集第 52 类（`dataset/dataset.yaml:54`），
`tools/tune_zhaizi_ocr.py` 与 `tools/fix_zhaizi_level_labels.py` 已能从
「等级：N」抠出数字，**但运行时 manifest 里没有这个条目**，所以跑起来仍是盲点。

**④ 盲进是固定步数的来源。**
`workers/leader_sm.py:375-380`：缓存未命中时**硬连点 12 次 `level_minus`**；
每次无结果还把缓存清掉（`leader_sm.py:411-412`）逼下一次重来。每一下点击前还挂着
3.1–5.5s 的 `click_delay`，所以「降到 1 级再升上来」是**约 56 秒的固定动作序列**。
`leader_sm.py:64` 的类注释自己写着「v1 已知限制：等级设置盲进」。

### 1.4 目标

- 等级调整的**点击次数随当前等级自然变化**，不再有固定 12 步。
- 调完等级**当场回读校验**，点击丢失可被检测并自纠（消掉一条已知限制）。
- 连点段有自己的、有下限的节奏，不再复用 3.1s 的跨动作延迟。
- 跑满轮数后 GUI 自动复位到停止态，并在界面暴露轮数配置。
- Start 前预检连接，失败点名报错且不产生半启动状态。

### 1.5 非目标（明确 YAGNI）

- ❌ **坐标经验值缓存**（详见 §2 D6）
- ❌ 全局压缩 `action_delay`（用户确认目标不是吞吐，是「不要死板」）
- ❌ 鼠标轨迹仿真 / 夜休 / 随机游玩时段
- ❌ `max_rounds` 无限档（见 §10 未决）
- ❌ 读等级以外的其它数值回读（体力值等）

---

## 2. 决策表

| # | 维度 | 决策 | 理由 |
|---|---|---|---|
| D1 | 判据缺失下的取向 | 消除机器签名（可变的步数 + 节奏） | 无判据可猜，只能按通用原则 |
| D2 | 等级读法 | 固定 ROI + RapidOCR 数字提取 | 见 §3.2；YOLO 腿的「抗布局漂移」在本项目是伪收益 |
| D3 | 读不出时 | 退回现有盲降路径（原样保留） | 最坏情况与现状**逐字相同**，OCR 抖动不烧轮次 |
| D4 | `_LEVEL_CACHE` | **删除** | 它是盲进的补偿手段；有回读后是多余的跨轮可变状态 |
| D5 | 连点节奏 | 新增独立旋钮 `rapid_click_min/max` | 复用全局下限要么仍是 3.1s，要么得压低**每一处**点击 |
| D6 | 坐标经验值缓存 | **不做** | 时间耗在 sleep 不在识别；且会把人性化层的高斯散布钉成常量，**加回「坐标重复」签名** |
| D7 | 全局 `action_delay` | 不动 | 用户确认目标不是吞吐 |
| D8 | 轮数 | 暴露到 GUI；保持 `ge=1`，不加无限档 | 见 §10 |
| D9 | 自动复位判据 | `stopped_reason is not None` | 天然区分「跑完/失败停机」与「用户点 Stop」 |
| D10 | 预检方式 | `capture()` + 分辨率判定 + 最多尝试 3 次，并返回 handle 复用 | 见 §7 |

---

## 3. §1 识别链路：读等级

### 3.1 manifest 新增顶层小节

沿用既有分区模式（`templates:` / `pixel_stats:`），`templates/manifest.yaml` 顶层新增：

```yaml
text_fields:
- id: fortress_level
  roi: [100, 470, 1040, 620]
  # 必须整块匹配。面板里另有「推荐兵力：1,400,000等级4的战斗单位集结进攻」
  # 这类含「等级」的长句，子串匹配会锚错对象——这正是那次标注污染的成因
  # （见 tools/fix_zhaizi_level_labels.py 的 docstring）。
  pattern: '^等级\s*[：:]\s*(\d+)$'
```

`roi` 与 `pattern` 都取自离线已验证的配方：`tools/fix_zhaizi_level_labels.py:62`
（ROI）与 `:68`（`LEVEL_RE`）。

### 3.2 新增 `core/recognizers/text_field.py`

```python
class TextFieldRecognizer:
    """裁 ROI + OCR，用正则**整块**匹配取一个文本块，返回 data={"text","value"}。"""
    def __init__(self, field_id: str, roi: BBox, pattern: str,
                 engine, name: str | None = None): ...
    def recognize(self, screenshot) -> RecognizeResult: ...
```

行为规格：

- 裁 ROI → 调**已有的** `RapidOcrEngine.detect_text`。复用同一个 engine 实例，
  因此吃到它的单帧缓存——同一帧读两次是免费的。
- 对每个文本块做 `pattern.fullmatch(text.strip())`，取**最左命中块**
  （`min(bbox.x1)`），与离线脚本 `anchor_from_blocks` 的取法一致。
- 命中 → `matched=True`，`data={"text": 原文, "value": 捕获组}`。
- 未命中 → `matched=False`，`data={"text": ""}`。

**为什么 pattern 放在 manifest 而不是写死在类里**：正则就是那条已经离线验证过的
配方，它是**数据不是代码**。以后要读别的数字（体力值等）只需加一条，不用改类。

### 3.3 装配

`core/template_registry.py`：

- `load` 读顶层 `text_fields:`（与 `raw.get("pixel_stats")` 同构，未知键本就忽略）。
- `build_recognizers` 增加装配分支，与 `_build_pixel_stats`（`template_registry.py:209`）
  同构，产出 `out[spec.id] = TextFieldRecognizer(...)`。
- 未配置 `text_fields` → 不产出该 id → 运行时按 D3 走盲降（与旧行为一致）。

---

## 4. §2 等级选择状态机

### 4.1 新流程

替换 `leader_sm._select_level`（`workers/leader_sm.py:362`）：

```
_select_level(ctx):
    self._click("tab_fortress")              # 不变：模板只在未选中态匹配，已选中则跳过
    target = self._current_level(ctx)

    current = self._read_level()             # 最多 3 帧，见 4.2
    if current is None:
        logger.warning("[车头] 等级文本读不出（面板可能不在城寨页），退回盲降")
        return self._blind_set_level(target) # 见 4.4：即今天「缓存为 None」那一支
    if current == target:
        logger.info("[车头] 面板等级已是 %s 级，跳过调整", target)
        return

    self._set_level(target, current)         # 点 |delta| 次，走 §5 的连点节奏
    self._verify_level(target)               # 回读校验，最多 2 轮修正
```

### 4.2 常量

| 常量 | 值 | 含义 |
|---|---|---|
| `_LEVEL_READ_ATTEMPTS` | 3 | 读不出时的重读次数（间隔走 `_pause(None)`） |
| `_LEVEL_VERIFY_ROUNDS` | 2 | 回读校验 + 修正的轮数上限 |
| `_LEVEL_MAX_CLICKS` | 10 | 单次 `_set_level` 的点击硬上限（等级 1..10，安全边界） |

合法等级范围 `1..10` 硬编码在状态机里（域知识），不放进识别器。越界视为读失败
（走 D3 盲降）——`target_levels` 的校验器（`infra/config.py:55-57`）已经保证目标
在这个范围内。

### 4.3 回读校验

```
_verify_level(target):
    for round in range(_LEVEL_VERIFY_ROUNDS):
        read = self._read_level()
        if read is None:
            break                       # 读不出就不再纠缠，交给 no_result 计数
        if read == target:
            logger.info("[车头] 等级回读确认 %s 级", target)
            return
        logger.warning("[车头] 等级回读 %s 级 ≠ 目标 %s 级，补点 %s 次",
                       read, target, abs(target - read))
        self._set_level(target, read)
    logger.warning("[车头] 等级回读仍未确认（目标 %s 级），继续本轮",
                   target)
```

最后一条**只记 warning 不抛错**：等级偏差会被后续 `no_result` 计数自然兜住
（`_check_result` 的既有机制），不该为此直接烧掉一轮。

### 4.4 删除 `_LEVEL_CACHE`，盲降固定为「全量降底」

**盲降路径只保留今天「缓存为 None」那一支**（`leader_sm.py:375-380`）：
12 次 `level_minus` 降到底，再升到目标。这是刻意选的——它**不依赖任何跨轮状态**，
所以删掉缓存后它仍然自洽，而且它就是今天首轮的行为，最坏情况与现状逐字相同。
（今天那条「缓存命中则只点差量」的支线随缓存一起删除：回读接管了它的职责。）

删除清单：`_LEVEL_CACHE` / `_LEVEL_CACHE_LOCK`（`leader_sm.py:29-30`）、
`_select_level` 里的读写（`:370-371`、`:388-389`）、`_check_result` 里清缓存那段
（`:411-412`）。

理由：缓存本来就是盲进的补偿手段，自己的注释都承认「若玩家在 GUI 运行期间手动改过
面板等级，缓存会偏一轮」。有了回读它就是**多余的跨轮可变状态**，删掉是净简化——
而且 `_check_result` 清缓存那个动作今天会强制一次 12 连点，回读之后不再需要。

`_blind_set_level` 的点击数（12 + 最多 9）**不受** `_LEVEL_MAX_CLICKS` 约束——
那个上限只针对回读成功后的差量点击。

`_switch_level`（`:423`）不动：它仍走 `_retry_search` → `_select_level`，只是后者
现在会真读一次等级，比盲降更准。

### 4.5 文档同步

`leader_sm.py:64-65` 的「v1 已知限制：等级设置盲进」随之失效，必须改；
`docs/PROGRESS.md` 与 `docs/HISTORY.md` 里引用了该限制的地方一并更正。

---

## 5. §3 节奏：连点段

### 5.1 新旋钮

`infra/anti_detection.py` 的 `AntiDetectionConfig` 新增：

```yaml
rapid_click_min: 0.35   # 连点段下限。实测 0.35s 连点 19 次零丢失（原 _LEVEL_CLICK_PACE）
rapid_click_max: 0.8
```

`HumanProfile.rapid_click_delay()` 复用同一套 beta + 突发形状，只是换区间
（即把 `click_delay` 的 lo/hi 换成这一对）。下限就是用户要的「下限秒数」——
防止点得比游戏 UI 反应更快而丢点击。

### 5.2 为什么必须是独立旋钮

现在等级连点的间隔**不是** `_LEVEL_CLICK_PACE` 决定的，是 `JitteringHandleSource.click`
里那个 3.1–5.5s 的 `click_delay`（`anti_detection.py:157-160`）。而突发分支算的是
`lo + (hi-lo)*U(0, burst_scale)`（`anti_detection.py:81-82`），在 `lo=3.1` 下只有
**3.1–3.7s——等于没有突发**。人性化层的突发分支在当前配置下几乎空转。

复用全局下限只有两条路，两条都不对：保持 3.1s（人手调数字盘不长这样），
或者压低全局下限把**每一处**点击都提速（用户明确不要）。

### 5.3 接口改动

`core/handle_source.py:19` 的 `HandleSource.click` 协议加一个带默认值的关键字：

```python
def click(self, x: int, y: int, anchor: str | None = None,
          rapid: bool = False) -> None: ...
```

- `JitteringHandleSource.click` 按 `rapid` 选 `rapid_click_delay()` 或 `click_delay()`。
- 其余实现（`MockHandleSource` / `AdbHandleSource` / `Win32HandleSource` /
  `ReplayHandleSource`）收下参数并忽略。
- **调用方向后兼容**，但 5 个实现类都必须收下这个参数，否则传了会 `TypeError`。

`state_machine.py` 的 `_click_result`（`:74`）与 `_click`（`:89`）各加一个
`rapid: bool = False` 透传；默认值保证其余调用点（14 处）逐字不变。

### 5.4 删掉 `_LEVEL_CLICK_PACE`

`leader_sm.py:24` 的 `_LEVEL_CLICK_PACE` 与 `:379`、`:387` 两处
`time.sleep(_LEVEL_CLICK_PACE)` 删除。节奏统一由 handle 层拥有，不再有第二处
硬编码的、无抖动的 sleep。原注释里「0.35s 零丢失」这条实测值迁到
`rapid_click_min` 的默认值注释里，作为证据保留。

---

## 6. §4 轮数与自动停止

### 6.1 暴露到配置界面

`gui/config_dialog.py` 新增一组「运行」，放 `max_rounds` 与
`max_consecutive_failures`（`infra/config.py:99-102`）。这两个字段早就有、
一直吃默认值 10/3，但界面一个都没有。

### 6.2 自动复位

```
runner 主循环退出 且 stopped_reason is not None
    └─ publish("worker_finished", {instance_id, char_id, char_name, stopped_reason})
RuntimeCoordinator 订阅 worker_finished
    └─ self.runners 里全部报过 → publish("all_workers_done", {reasons: [...]})
GuiController 订阅 all_workers_done
    └─ 新信号 run_finished = pyqtSignal(dict)
MainWindow 接上 run_finished
    └─ start_btn.setEnabled(True) / stop_btn.setEnabled(False)
       statusBar 写停机原因
```

要点：

- **判据用 `stopped_reason is not None`**（`runner.py:112` 注释即「非 None = 主循环已
  退出」）。用户点 Stop 时主循环经 `_stop_event` 退出而 `stopped_reason` 保持
  `None`，因此**不会**误触发复位。
- 发布点放在 `_run` **主循环退出之后**，用 `if self.stopped_reason is not None`
  守卫。`_run` 里有三个 `break` 出口（轮数/失败停机、冷却期收到 stop、连续 step
  异常超限），挂在循环出口统一发一次，比在每个 `break` 前各发一次更难漏。
- 状态栏文案直接用 `stopped_reason`（已是人类可读中文，如「已完成 10 轮，达到轮数上限」）。
- 不弹模态框：跑完是正常结束，`QMessageBox` 会打断无人值守场景。

### 6.3 多 worker 的语义

`max_rounds` 是**每角色**的。两号轮次天然不同长（车头一轮含等成员回城），所以
先跑完的 worker 先 `done` 并停止，其余继续；**全部** `done` 才复位按钮。这是现有
行为，本设计不改。

---

## 7. §5 启动预检

### 7.1 新增 `coordination/preflight.py`

```
preflight(instances, app_config) -> dict[instance_id, HandleSource]
```

逐台：

1. `create_handle_source(...)`（与 `runtime.py:126-131` 同参）。
2. `capture()` 真截一帧，**最多尝试 3 次**（首次 + 2 次重试，间隔 1s / 2s）。
3. 解出的帧必须是 `1920×1080`（`(1080, 1920, 3)`），否则按失败处理，错误文案
   里带**实际尺寸**。
4. 成功 → 把建好的 handle 收进返回值。

任一实例最终失败 → 抛 `RuntimeError`，文案复用 `runtime.py:141-147` 那套点名格式
（「模拟器「阑珊填1」（mumu1，MuMu 编号 1）连不上：…」），并带耗时。

### 7.2 为什么这样选

- **用 `capture()` 而不是 `is_alive()`**：`is_alive()` 只查 `adb devices` 的状态字段
  （`handle_source.py:151-160`），而实机上真正会炸的是 `screencap`。
- **判定分辨率**：运行手册 Step 1 特意警告过竖屏/登录页会让门槛白等 900s。与其
  静默烧 15 分钟，不如启动时就说清楚实际尺寸。
- **最多尝试 3 次**：断线是常态而非异常（adb server 重启、模拟器刚唤醒），
  `AdbHandleSource._run_checked` 已内置一次重连重试，这里再给一层启动级退避。
- **返回 handle 复用**：`create_handle_source` 走 `mumu_index` 时要调 MuMuManager，
  冻结包里实测 0.67–1.11s（PROGRESS 已知问题 10）。不该建两遍。

### 7.3 挂载位置

`coordination/runtime.py` 的 `RuntimeCoordinator.start()` **最开头**，在
`TemplateRegistry.load(...).build_recognizers(...)`（`runtime.py:118-123`）**之前**。

识别器装配要加载 ONNX，好几秒；连不上的时候不该白花。然后原
`create_handle_source` 那段循环改为消费预检返回的 handle，`try/except` 的点名逻辑
移进 `preflight`。

**因为预检在任何 runner 诞生之前，`_rollback()` 不再需要为「连接失败」服务——
半启动状态从根上消失。**（`_rollback` 本身保留，仍为识别器装配失败等路径服务。）

### 7.4 成功也要报一句

预检通过 → 状态栏「预检通过：2 台模拟器」，让用户知道连接**真的测过了**，
而不是「没报错」。

### 7.5 无头驱动白捡

`_run_goal.py:48` 也构造 `RuntimeCoordinator`，因此自动获得预检，无需单独接线。

---

## 8. 测试策略

按 TDD 补，全部走假件，不依赖真模拟器。

| 对象 | 测试要点 |
|---|---|
| `TextFieldRecognizer` | 假 engine 喂文本块序列：整块命中 / 长句含「等级」**不得**命中 / 多块取最左 / 无命中返回 `matched=False` |
| `TemplateRegistry` | `text_fields` 装配出对应 id；未配置时不产出该 id |
| `_select_level` | ① 读到 == 目标 → **零点击**；② 读到 3、目标 6 → 恰好 3 次 `level_plus`；③ 读到 9、目标 4 → 5 次 `level_minus`；④ 读不出 → 退回盲降（12 次 minus）；⑤ 越界值（如 15）→ 视为读失败 |
| 回读校验 | 首轮点击被「吞掉」（假 handle 只记部分点击）→ 第二轮补点后读数收敛；`_LEVEL_VERIFY_ROUNDS` 用尽 → 只 warning 不抛错 |
| 连点节奏 | `rapid=True` 走 `rapid_click_delay` 区间、`rapid=False` 走 `click_delay` 区间（注入 `random.Random` 定种子断言） |
| 预检 | ① 两台全通 → 返回 2 个 handle；② 一台尝试 3 次后仍失败 → 抛错且文案含实例名；③ 尺寸非 1920×1080 → 抛错且文案含实际尺寸；④ 失败时**未**装配识别器 |
| 自动复位 | ① `stopped_reason` 非 None → 发 `worker_finished`；② 用户 Stop（`stopped_reason is None`）→ **不**发；③ 全部报过 → 发 `all_workers_done`；④ `MainWindow` 收到后按钮复位 |

回归范围：`leader_sm` / `anti_detection` / `handle_source` / `template_registry` /
`runner` / `runtime` / `controller` / `config_dialog` 相关单测，外加
`tests/integration/test_controller.py`。收尾跑一次全量。

---

## 9. 风险与回滚

| 风险 | 说明 | 处置 |
|---|---|---|
| **ROI 锚到「野蛮人」页的等级** | 面板记住上次 Tab，野蛮人页**也有等级**。若 `tab_fortress` 那次点击失败而野蛮人页的等级行恰好落在同一 ROI，回读会读到一个**看似合法**的数字，且因为回读自洽而**不会被自纠机制发现** | **实机必须验**：在城寨页与野蛮人页各截一帧，确认该 ROI 只在城寨页读出「等级：N」。若两页都读得出，加一道守卫（见 §10）。**这是本设计唯一的实质性未知** |
| 等级回读偶发读不出 | OCR 抖动 | D3 退回盲降，最坏与现状逐字相同 |
| `rapid` 参数漏实现 | 某个 `HandleSource` 实现没收下关键字 → `TypeError` | 5 个实现类逐一改；可选加一条扫描测试（同 `tests/unit/infra/test_subproc.py` 的做法） |
| 删除 `_LEVEL_CACHE` 影响既有单测 | 有测试直接引用它 | 随改动一并更新；这是刻意的简化，不是回归 |
| `text_fields` 新键被 manifest 校验拒绝 | — | `load` 是 `raw.get(...)` 裸字典读取，未知键本就忽略；**实现时先确认** |
| 连点下限过低丢点击 | 游戏丢点击 | 默认 `rapid_click_min=0.35` 有实测支撑；且回读校验会补 |

**回滚杠杆**（互相独立，可单独退）：

- 删掉 manifest 的 `text_fields` 一节 → 等级链路回到纯盲降，其余不受影响。
- `rapid_click_min/max` 设回 `action_delay` 同值 → 连点段节奏回到全局延迟。
- 预检的失败重试次数设 1 且不判定分辨率 → 回到「一次尝试即失败」。

---

## 10. 未决 / 范围外

1. **`max_rounds` 无限档**：现为 `ge=1`，无「一直跑到体力耗尽」档。目标描述里写的是
   「循环往复直至体力耗尽**或**完成一定次数」。本轮**不加**（YAGNI，且体力耗尽已由
   连续失败计数兜住停机）；若需要，改为 `int | None`、`None` = 无限即可。
2. **野蛮人页守卫**：取决于 §9 那条实机验证的结果。若两页同 ROI 都能读出，候选守卫：
   - 在 ROI 内同时要求城寨页特有的第二文本块（需先确认真机上有稳定的这样一块）；
   - 或给 `tab_fortress` 补一个「已选中」模板，切换后先确认再读。
   **先量再定，不预先设计。**
3. **`is_alive()` 的语义**：它只查 `adb devices`，与 `capture()` 的实际可用性可能
   不一致（`runner.py:148` 用它判暂停）。本设计不动它，仅记录。
4. **`tools/annotate_live.py` 等 `build_recognizers` 的其它调用方**：新增 `text_fields`
   装配后需确认它们不需要（也不需要拒绝）新识别器。实现时逐一过。
