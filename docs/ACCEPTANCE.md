# 万国觉醒游戏助手 · 验收手册

> 状态：v1 实施完成（31 个 task + 3 个工具），等用户实机验收  
> 日期：2026-07-19

## 当前状态

| 项 | 状态 | 备注 |
|---|---|---|
| 自动化测试 | ✅ 81/81 通过 | `pytest tests/` |
| 核心代码 | ✅ 完整 | 5 层架构全部就位 |
| 工具脚本 | ✅ 3 个 | `record.py` / `crop_template.py` / `verify.py` |
| 真实模板 | ❌ 待采集 | 下面 §1 步骤 |
| 用户 config | ❌ 待写 | 下面 §2 步骤 |
| 实机验收 | ⏳ 待跑 | 下面 §3 步骤 |

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

参考 spec section 6 写你的实际配置。基于你 482A 账号：

```yaml
# config.yaml

app:
  screen_width: 1920
  screen_height: 1080
  locale: zh-CN
  anti_detection:
    click_offset_px: 8
    action_delay_min: 0.1
    action_delay_max: 0.5
    state_delay_min: 0.3
    state_delay_max: 1.2
    jitter_ratio: 0.3
    debug_no_jitter: false  # 调试时改 true 看真实坐标

accounts:
  - id: account_482A
    window_title_pattern: "MuMuPlayer"  # 改成你模拟器窗口实际标题
    characters:
      - id: char_leader
        name: "阐珊爱拉野"   # 必须和游戏内一致（OCR 验证用）
        role: leader
        target_level: 8
        march_preset: 1
        march_troop_types: [infantry]

      - id: char_jy
        name: "Jy、阐珊"     # OCR 验证会读这个名字，注意游戏内写法
        role: member
        target_level: 8      # 必填（1-10）；member 也参与打这个等级
        march_preset: 1
        march_troop_types: [infantry]
        fill_target_leaders: nearest

      - id: char_tian1
        name: "阐珊填1"
        role: member
        target_level: 8
        march_preset: 1
        march_troop_types: [infantry]
        fill_target_leaders:
          - { account: account_482A, name: "阐珊爱拉野" }

      - id: char_tian2
        name: "阐珊填2"
        role: member
        target_level: 8
        march_preset: 1
        march_troop_types: [infantry]
        fill_target_leaders: nearest
```

> 注意：`target_level` / `march_preset` / `march_troop_types` 对**每个角色都是必填**（schema 无默认值），漏写会在启动时被 pydantic 拒绝。

### 校验

```bash
# 用 load_config 验 schema
python -c "from rok_assistant.infra.config import load_config; from pathlib import Path; print(load_config(Path('config.yaml')))"
```

报错 = config 写错（看错误信息修正）。

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
