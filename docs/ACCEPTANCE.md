# 万国觉醒游戏助手 · 验收手册

> 状态：实机验收进行中（2026-09-07 起，ADB 路线）  
> 日期：2026-07-19 · 更新：2026-09-07

## 当前状态

| 项 | 状态 | 备注 |
|---|---|---|
| 自动化测试 | ✅ 554/554 通过（2026-10-04） | `pytest tests/ -q`，278.20s（含端到端 leader→member→冷却重建集成测试） |
| 运行时接线 | ✅（2026-09-10） | WorkerRunner/RuntimeCoordinator/GuiController 已接线，GUI Start/Stop 可用；member 填兵不点预设；leader 流程含 red_rally/归一化/toast/被锁恢复 |
| 采集路线 | ✅ **改为 ADB** | `AdbHandleSource`：截图/点击都走 MuMu adb（127.0.0.1:16384），原生 1920×1080，与窗口/DPI 无关 |
| 真实模板 | ✅ 31/31 已采 | 见下表，验证方式=跨帧+跨角色 TemplateMatch |
| 用户 config | ✅ 已写（2026-09-09） | 2 实例、每实例 1 角色；角色分工 / 目标等级列表 / 预设槽 / 兵种 / 填兵目标齐全。**具体取值以 `config.yaml` 为准，本文档不记录** |
| 实机验收 8 项 | ⏳ 未开始 | §3 |

## §1.4 模板采集进度（2026-09-07）

已采并验证（templates/ + manifest.yaml）：

| 模板 | 验证 |
|---|---|
| search_icon, alliance_btn | 跨帧 0.99+；跨角色场景缺失时按预期不匹配（视角问题，见下） |
| level_plus, level_minus | 5 连点无丢失，等级 1→6 实测 |
| search_btn, search_back, tab_fortress | 实测点击生效（Tab 切换、搜索触发） |
| toast_no_fortress | 无结果 toast 实测两场景，conf 0.95+（无 toast 时 0.09） |
| red_rally, rally_attack_popup, blue_rally, time_5min | 7 级城寨详情+集结进攻弹窗实测，跨帧 1.0 |
| war_title, sort_dropdown, sort_nearest, war_empty, join_btn | 战争页实测：排序切到「距离最近」成功；空列表文案已采 |
| profile_title, settings_btn, settings_title | 跨角色 1.0 |
| char_mgmt_btn, char_mgmt_title, char_avatar_lszz, char_avatar_lswk | 角色管理页 1.0 |
| switch_confirm_yes, click_to_enter | 切换确认框 + 重登入口实测 |
| march_btn, preset_1~6, troop_infantry/cavalry/archer/siege | 「创建部队」弹窗实测（2026-09-09）：march_btn/preset_2~6/troop_* 跨帧 1.0；见下方注意事项 |

**「创建部队」弹窗补充（2026-09-09 实测）：**

1. 弹窗标题实际是「**创建部队**」（非设计稿的「组建部队」）；右侧预设槽实际有 **6 个**（蓝色1~6号存档），比 spec 的 5 个多一个，已加采 `preset_6`。
2. 兵种图标实为 4 个红菱形（步/骑/弓/**车**），已加采 `troop_siege`。
3. `march_btn`（橙色行军按钮）下方的 00:00:XX 是**行军时长估计**，不是倒计时，不会自动出发；模板只裁了「行军」文字区，跨帧稳定 1.0。
4. `preset_1` 模板是**未选中态**：弹窗打开时无预设选中，匹配正确；载入预设后槽位高亮（变白）则不匹配（conf 0.38，符合预期）。
5. 采集方式：点红集结 → 集结进攻弹窗（5分钟默认勾选）→ 蓝集结 → 创建部队弹窗截图后 BACK 关闭，**未点行军**（无出征；集结无人填兵 5 分钟后自动解散）。

## §1.5 实测发现的设计修正（重要）

1. **切换角色是 5 步不是 4 步**：头像 → 设置 → 角色管理 → 点目标角色头像 → **「角色登入」确认框点「是」** → 完整重登（登录页「点击进入游戏」→ 加载约 20-25s）。`switcher_sm` 需要加确认步骤和重登处理。✅ 已实现（`switcher_sm`：settings_btn → char_mgmt_btn → 点选头像 → `switch_confirm_yes` → `click_to_enter` 重登）
2. **视角归一化**：重登后城市视角是放大的，搜索放大镜/底部菜单栏不可见。状态机在打寨子流程前需要先把视角恢复到已知状态（缩小视角或进地图视角）。✅ 已实现（leader_sm / member_sm 的 `_normalize_view`：先查 `search_icon`，不可见则点 `map_btn` 进地图视角）
3. **主界面左上角没有角色名**（只有头像+战力+时代）——切角色后的 OCR 名字校验不能按原设计读左上角，需改为匹配头像模板或开资料页 OCR。✅ 已实现（`switcher_sm` 用头像模板 `_verify` 校验，无模板时跳过并记 `verify_skipped`）
4. **搜索无结果有 toast**：「您的城市附近暂未找到符合条件的野蛮人城寨」——已是模板 `toast_no_fortress`，leader_sm 应处理（换等级/稍后重试）。实测 1-6 级城寨均不在附近，7 级有。✅ 已实现（leader_sm `_check_result`：toast 可见即确证无结果，计数 ≤3 次重搜后放弃）
5. **Win32 采集路线放弃**：2560×1600@150% DPI 下 PrintWindow 裁剪且无法保证 1920×1080；ADB 路线已完全替代（点击、截图实测可用）。✅ 已实现（`AdbHandleSource` 为默认路线）
6. 搜索结果详情弹窗有 ⭐ 书签（与锁定无关，WIP 推测正确）；消失倒计时如 19:59:51 在弹窗左下。✅ 已证实（leader_sm `_verify_unlocked` 锁定判定只看 `rally_attack_popup`，与书签无关）
7. **识别链顺序：YOLO 先行**（2026-10-04，用户要求）。`template_match` 条目装配成 `[YOLO, 模板]`，两条腿各有自己的阈值（YOLO 用 `yolo_threshold`，缺省 0.5；模板用 `threshold`）。`fill_*` 的兜底腿是 OCR，仍**模板先行**。`preset_1..6` 与 `alliance_btn` 显式关掉 YOLO 腿（定标实测漏检/误报）。细节见 `docs/PROGRESS.md` 阈值参考与 `docs/HISTORY.md` 10-04 一节。
8. **车头判据由配置驱动**（2026-10-06）。`app.ocr_name_fallback` 是**独立开关**，不再被「配没配 yolo_model」二次门控；`fill_target_leaders` 点名的车头若 manifest 里没有 `fill_<名字>` 条目，runtime 会按名字就地生成 OCR 判据（ROI 取名字列实测基准），**换车头不需要改 manifest**。细节见 `docs/HISTORY.md` 10-06 一节。

---

## §1 采集真实模板

v1 需要采集 **15+ 张** UI 元素模板（参考 `docs/superpowers/specs/2026-07-15-rok-assistant-design.md` 第 5 节）。

### 1.1 准备 MuMu 模拟器

1. 启动 MuMu 模拟器
2. 登录 RoK 到你的主城界面
3. 把模拟器窗口调整成 1920×1080 全屏（或最大化）
4. 确认窗口标题含有可识别的字符串（看任务栏或 `tools/record.py --pattern` 用的 pattern）

### 1.2 录制关键场景

用 `tools/record.py` 录几个关键画面（每个场景录 5-10 帧，够你后面挑一帧来裁模板）：

```bash
cd C:\coding\workspace\git\myrok

# 场景 1：主城（用于采集 search_icon, march_preset 等）
python tools/record.py --account 482A --pattern "MuMuPlayer" --interval 1.0 --max-frames 10 --out recordings/main_city

# 场景 2：搜索面板 + 等级选择
python tools/record.py --account 482A --pattern "MuMuPlayer" --interval 1.0 --max-frames 10 --out recordings/search_panel

# 场景 3：搜索结果 + 锁定提示
python tools/record.py --account 482A --pattern "MuMuPlayer" --interval 1.0 --max-frames 10 --out recordings/search_result

# 场景 4：发起集结弹窗
python tools/record.py --account 482A --pattern "MuMuPlayer" --interval 1.0 --max-frames 10 --out recordings/rally_popup

# 场景 5：组建部队（march 弹窗 + preset + 兵种）
python tools/record.py --account 482A --pattern "MuMuPlayer" --interval 1.0 --max-frames 10 --out recordings/march_popup

# 场景 6：个人资料 + 设置
python tools/record.py --account 482A --pattern "MuMuPlayer" --interval 1.0 --max-frames 10 --out recordings/profile

# 场景 7：设置 + 角色管理
python tools/record.py --account 482A --pattern "MuMuPlayer" --interval 1.0 --max-frames 10 --out recordings/char_mgmt

# 场景 8：联盟 + 战争 + rally 列表
python tools/record.py --account 482A --pattern "MuMuPlayer" --interval 1.0 --max-frames 10 --out recordings/war
```

### 1.3 裁剪模板

每个场景挑一帧最好的，用 `tools/crop_template.py` 裁出小图：

```bash
# 打开主城画面
python tools/crop_template.py --input recordings/main_city/session_*/frame_00003.png
```

**操作流程**：
1. 弹出 OpenCV 窗口显示截图
2. **鼠标拖框** 选中要作为模板的 UI 元素
3. **ENTER** 保存（如果 `--id` 没传，会在终端问你 `Template id:`）
4. 提示 `Saved xxx.png and updated templates/manifest.yaml`
5. 拖下一个元素...

### 1.4 完整模板清单

按 spec 5 节 + 状态机代码，需要这些模板（命名要和状态机一致）：

**车头（leader_sm）用**：
- `search_icon` — 主城左下角搜索图标
- `level_plus` / `level_minus` — 等级加减按钮
- `search_btn` — 搜索按钮
- `rally_attack_popup` — 点红集结后等 5 秒看是否弹出"集结进攻"
- `red_rally` — 红色集结按钮
- `blue_rally` — 蓝色集结按钮（确认用）
- `march_btn` — 行军按钮
- `preset_1` ~ `preset_6` — 6 个部队预设（实测为 6 个，非设计稿的 5 个）
- `troop_infantry` / `troop_cavalry` / `troop_archer` / `troop_siege` — 4 个兵种

**成员（member_sm）用**：
- `alliance_btn` — 底部联盟按钮
- `war_btn` — 联盟界面左上"战争"
- `sort_nearest` — 把"最新发起"改"距离最近"
- `join_btn` — rally 卡片上的 "+" 加入按钮
- (march preset/march btn 同上)

**切角色（switcher_sm）用**：
- `avatar` — 主界面左上头像
- `settings_btn` — 设置按钮
- `char_mgmt_btn` — 设置里"角色管理"
- `char_avatar` — 角色管理里的角色头像（用于点击目标）

采集完毕后 `templates/manifest.yaml` 应包含 15-20 个 entry。`templates/` 目录结构：
```
templates/
├── manifest.yaml
├── search_icon.png
├── red_rally.png
├── march_btn.png
├── ...
```

---

## §2 写你的 config.yaml

**推荐方式：** 启动 GUI（`python -m rok_assistant.gui.main_window`，从项目根目录），点「⚙ 配置」，在左树右表单界面里配置全局路径、模拟器（点「扫描模拟器」按 MuMu 里的名字选）与角色阵容（分工/等级/预设/兵种/填兵目标），保存时自动校验。配置前先用模拟器页「测试连接」确认连对了模拟器。

> 面向非程序员的逐步说明见 [`配置说明.md`](配置说明.md)（会随绿色包一起分发）。

**手动方式：** 复制 `config.example.yaml` 为 `config.yaml` 修改。要点：
- `instances` 取代旧 `accounts`；1 实例 = 1 账号；`mumu_index` 与 `adb_address` 二选一
- `role`: `leader`（车头，自己开寨）/ `member`（成员，只填兵）/ `either`（先开寨再填兵）
- `member`/`either` 必填 `fill_target_leaders`（显式列表，可跨实例）；`leader` 不能配
- `target_levels`（有序搜索列表，1–3 个、1–10、不重复；顺序完全自由）/ `march_preset` / `march_troop_types` 对每个角色必填
- 校验命令见 `config.example.yaml` 头部注释

---

## §3 跑 5 项手动验收

运行时已接线（2026-09-10）：启动 GUI（`python -m rok_assistant.gui.main_window`）→ Start，验收现在可以真跑（v1：每实例第一个角色一个 worker 线程，rally 事件由 RuntimeCoordinator 路由给成员）。

```bash
python tools/verify.py
```

输出 checklist。逐项跑：

> **编号 3.3–3.5 已删除（2026-10-04，用户裁定不再要求单独验收）**：锁定城寨→跳过重搜 /
> 集结超时→自动下一轮 / 关模拟器→paused→重开恢复。编号**保留跳跃**不重排——`leader_sm.py`
> 与 `runner.py` 的注释里引用了 §3.3/§3.5。

### 3.1 [x] Start 1 emulator + 1 character, run 1 rally

1. 启动 MuMu，确保 RoK 在主城
2. 启动 GUI：`python -m rok_assistant.gui.main_window`
3. 配置文件选择 `config.yaml`
4. Start → 观察 `logs/rok_assistant_*.log` 看状态机走到 `END`
5. GUI 上的 leader character card 应显示状态变化（`searching` → `forming` → `waiting` → `done`）

### 3.2 [x] Add 1 member, verify auto-switch + join

1. config.yaml 至少 1 leader + 1 member
2. 启动时两个 emulator 窗口（同一个 MuMu 多开 482A 账号两个角色，或开两个 MuMu）
3. GUI 显示多张 card
4. leader 开战后，member card 应自动从 `idle` → `switching` → `joining` → `done`

### 3.6 [x] Invalid config (level=11) -> refused at startup

1. config.yaml 改一个角色 `target_levels: [11]`
2. 启动 GUI 应弹错误对话框，明确指出哪个字段错了
3. 拒绝启动，进程退出

### 3.7 [x] Wrong char name -> OCR verify fails + retry

1. config 写错角色名字（比如 `阐珊爱拉野x`）
2. Switcher 切到那个角色后，OCR 读左上角名字 → 不匹配
3. 自动重试 ≤2 次，仍不匹配则报错到 GUI 红色高亮

### 3.8 [x] Log records all steps + screenshot on failure

1. 跑任意流程，看 `logs/rok_assistant_*.log` 有每步状态转移记录
2. 故意制造一次失败（比如关窗口）→ 应有截图保存到 `recordings/`
3. 文件名带时间戳

### 3.9 [ ] 多目标填兵 · 多预设回退 · 断网归一化

- 多预设回退：配置两个预设、把第一个预设的主将留在城外（返程中），
  车头应改用第二个预设发车，日志出现「预设槽 N 高亮确认不了，改用下一个」。
- 成员波次填兵：两个车头同时发起集结，成员应依次把两个都填上，
  而不是只填第一个（旧行为的现象是第二个车头空等）。
- 断网弹框：断网时归一化日志出现「检测到断网弹框，点击「确定」重连」，
  且随后能回到地图视图继续原流程。

---

## §4 常见问题

### 模板识别不上

- 截图分辨率要和模板一致（1920×1080）
- 调整 `threshold`（`templates/manifest.yaml` 改小，比如 0.85）
- 用 `debug_no_jitter: true` 验证坐标是否正确

### OCR 验证失败

- 切换角色后等动画结束再 OCR
- 检查角色名字（注意中文标点）

### 模拟器窗口找不到

- 调整 `window_title_pattern`（用部分匹配）
- 用 `python -c "import win32gui; win32gui.EnumWindows(...)"` 看实际窗口标题

### 启动崩溃

- 看 `logs/rok_assistant_*.log` 最后几行
- 大概率是 pydantic validation error（config 写错）或 template 文件缺失

---

## §5 跑回归测试

任何时候改完代码：

```bash
cd C:\coding\workspace\git\myrok
python -m pytest tests/ -v
```

期望**全部测试通过**（以 pytest 实际输出为准，勿依赖本文档写的数字）。

---

## §6 接下来做什么

v1 实施已经完成。**你跑完 8 项验收后**，可以：

- **修模板** — 大概率第 1 次跑识别率低，需要反复 `crop_template.py` 重采或调 threshold
- **调 anti_detection** — 如果被检测到，调整 `config.anti_detection.*` 加大随机化
- **加 v2 功能**（spec 11 节）:
  - 采集宝石
  - PC 客户端支持
  - 跨机器协调
  - 行为仿真（鼠标轨迹）
