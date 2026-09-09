# 万国觉醒游戏助手 · 验收手册

> 状态：实机验收进行中（2026-09-07 起，ADB 路线）  
> 日期：2026-07-19 · 更新：2026-09-07

## 当前状态

| 项 | 状态 | 备注 |
|---|---|---|
| 自动化测试 | ✅ 91/91 通过 | `pytest tests/` |
| 采集路线 | ✅ **改为 ADB** | `AdbHandleSource`：截图/点击都走 MuMu adb（127.0.0.1:16384），原生 1920×1080，与窗口/DPI 无关 |
| 真实模板 | 🟡 20/约26 已采 | 见下表，验证方式=跨帧+跨角色 TemplateMatch |
| 用户 config | ❌ 待写 | 阵容待用户确认；schema 已升级为 instances（GUI「⚙ 配置」可直接编辑） |
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

**未采**（需要真实发起集结才能看到「组建部队」弹窗，等用户确认后采）：
`march_btn`、`preset_1`~`preset_5`、`troop_infantry`/`troop_cavalry`/`troop_archer`

## §1.5 实测发现的设计修正（重要）

1. **切换角色是 5 步不是 4 步**：头像 → 设置 → 角色管理 → 点目标角色头像 → **「角色登入」确认框点「是」** → 完整重登（登录页「点击进入游戏」→ 加载约 20-25s）。`switcher_sm` 需要加确认步骤和重登处理。
2. **视角归一化**：重登后城市视角是放大的，搜索放大镜/底部菜单栏不可见。状态机在打寨子流程前需要先把视角恢复到已知状态（缩小视角或进地图视角）。
3. **主界面左上角没有角色名**（只有头像+战力+时代）——切角色后的 OCR 名字校验不能按原设计读左上角，需改为匹配头像模板或开资料页 OCR。
4. **搜索无结果有 toast**：「您的城市附近暂未找到符合条件的野蛮人城寨」——已是模板 `toast_no_fortress`，leader_sm 应处理（换等级/稍后重试）。实测 1-6 级城寨均不在附近，7 级有。
5. **Win32 采集路线放弃**：2560×1600@150% DPI 下 PrintWindow 裁剪且无法保证 1920×1080；ADB 路线已完全替代（点击、截图实测可用）。
6. 搜索结果详情弹窗有 ⭐ 书签（与锁定无关，WIP 推测正确）；消失倒计时如 19:59:51 在弹窗左下。

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
- `preset_1` ~ `preset_5` — 5 个部队预设
- `troop_infantry` / `troop_cavalry` / `troop_archer` — 3 个兵种

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

**推荐方式：** 启动 GUI（`python -m rok_assistant.gui.main_window`，从项目根目录），点「⚙ 配置」，在左树右表单界面里配置全局路径、实例（MuMu 实例号）与角色阵容（分工/等级/预设/兵种/填兵目标），保存时自动校验。配置前先用实例页「测试连接」确认连对了模拟器。

**手动方式：** 复制 `config.example.yaml` 为 `config.yaml` 修改。要点：
- `instances` 取代旧 `accounts`；1 实例 = 1 账号；`mumu_index` 与 `adb_address` 二选一
- `role`: `leader`（车头，自己开寨）/ `member`（成员，只填兵）/ `either`（先开寨再填兵）
- `member`/`either` 必填 `fill_target_leaders`（显式列表，可跨实例）；`leader` 不能配
- `target_level` / `march_preset` / `march_troop_types` 对每个角色必填
- 校验命令见 `config.example.yaml` 头部注释

---

## §3 跑 8 项手动验收

```bash
python tools/verify.py
```

输出 8 项 checklist。逐项跑：

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

### 3.3 [x] Locked fortress -> skip + next

1. 选一个已被别人集结的寨子（搜结果里看到 ⭐ 或 锁图标）
2. 点红集结，等 5 秒应**不出现**"集结进攻"弹窗
3. 状态机应走到 `next_fortress` 状态，自动选下一只
4. 看 log 应有 `fortress_locked` 记录

### 3.4 [x] Rally times out empty -> leader relaunches

1. leader 开战
2. 没有 member 加
3. 5 分钟倒计时结束，rally 自动解散
4. leader 状态机应重新进入 `SEARCH_FORTRESS` 找下一只

### 3.5 [x] Close emulator window -> assistant pauses

1. 跑到一半关掉 MuMu 窗口
2. 所有 worker 应检测到 `is_alive() == False` → 暂停
3. GUI 不应崩溃，log 应有 `window_disappeared` + `PAUSE_ALL`
4. 重开 MuMu 窗口 → 可手动 resume

### 3.6 [x] Invalid config (level=11) -> refused at startup

1. config.yaml 改一个角色 `target_level: 11`
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

期望 **81 passed**。

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
