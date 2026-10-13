# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# myrok（RoK 助手）——本仓库工作约定

## 省 token 优先（本仓库会话烧得快，先看这节）

- **先问 CodeGraph**：`.codegraph/` 索引已建好。定位符号 / 调用关系用 `codegraph_explore`，
  别 grep + 逐个 Read——一次调用返回源码 + 调用路径 + 影响面。
- **看图前先想办法不读图**：截图 1920×1080，按面积计价，是单次读入里最贵的。
  判断画面内容优先用脚本打印数值/判据（几十 token）；必须看画面时先裁 ROI 并缩放。
  只有「必须看整屏布局」才读全帧。
- **测试默认只跑相关子集**（`pytest tests/unit/xxx.py -q`）；全套近千条 5 分钟，收尾跑一次。
- **长跑不轮询**：驱动要跑几小时。后台跑、把关心的行写进文件，只在关键节点读末尾几行；
  别 `sleep` + `tail` 反复拉。

## 文档导航

- `docs/PROGRESS.md` —— **当前状态 / 待办 / 速查**（短，常读）
- `docs/HISTORY.md` —— 历史会话流水（append-only，**回溯根因时才读**）。新记录写这里。
- `docs/ACCEPTANCE.md` —— 验收手册；`docs/配置说明.md` —— 面向非程序员的配置说明（随绿色包分发）
- `docs/superpowers/specs/*.md` —— 各功能的设计文档（**设计意图的源头**，改动前先看对应那篇）
- `docs/PACKAGING.md` —— 打绿色 zip 包

## 常用命令

**一律用 `.venv/Scripts/python.exe`**（见「环境与坑」），下面记作 `$PY`。

```bash
# --- 测试 ---
$PY -m pytest tests/ -q                          # 全量（~5 min，收尾跑）
$PY -m pytest tests/unit/workers/test_leader_sm.py -q   # 单文件
$PY -m pytest tests/unit/workers -q                      # 单目录
$PY -m pytest tests/ -q -k "gate"                        # 按名字筛
# integration 标记的用例要 recordings/ 里的截图；没截图时会红，不是回归
$PY -m pytest tests/unit -q

# --- 运行 ---
$PY -m rok_assistant.gui.main_window                     # GUI（或装好后 rok-assistant）
# 无头驱动：必须 nohup 脱离式（harness 的 run_in_background 会被看门狗杀）
nohup $PY -X utf8 _run_goal.py > _driver.log 2>&1 &
powershell -NoProfile -ExecutionPolicy Bypass -File _kill_driver.ps1   # 停驱动

# --- 权重（换检测模型后这两步都要跑，缺一不可）---
$PY -X utf8 tools/export_onnx.py                 # 导出 ONNX
$PY -X utf8 tools/calibrate_yolo_threshold.py    # 重定标 YOLO 腿阈值

# --- 打包 / 自检 ---
$PY -X utf8 tools/build_package.py [--trial-days N]      # -> dist/rok-assistant-*.zip
./dist/rok-assistant/rok-assistant.exe --selftest        # 不开窗口跑真实识别链路

# --- 发码（作者本机）---
$PY -X utf8 tools/license_tool.py                # 首次运行生成密钥对，记得提交 pubkey.py
```

**本仓库没有配置 linter / formatter**（无 ruff / flake8 / mypy 配置），别去找 lint 命令。
代码里出现 `# noqa: BLE001` 是历史习惯，不是某套工具在跑。

## 架构

**分层**：`infra/`（配置、路径、子进程、MuMu、日志、授权）→ `core/`（识别器 + 模板注册表）
→ `workers/`（状态机）→ `coordination/`（协调器、事件总线、账本、门槛）→ `gui/`。
依赖只向下，GUI 与 driver 都只是 `coordination` 的两个入口。

### 配置驱动的一切

`config.yaml` → `RootConfig`（pydantic，`infra/config.py`）。`instances[].characters[]`
每个角色带 `role ∈ leader / member / either`：

- **leader** —— 开车头：归一化 → 搜城寨 → 设等级 → 红集结 → 蓝集结 → 预设+兵种 → 行军
- **member** —— 填兵：收到 `rally_launched` 事件后去战争列表找点名车头、点「+」→ 创建部队 → 行军
- **either** —— 两种都干（`either_sm.py` 组合 leader + member 两个 SM）

`config.py` 的 `_cross_checks` 保证至少一个 leader/either、`fill_target_leaders` 互相指向等。
**文档只记字段作用，不记取值**——要核对直接读 `config.yaml`。

### 运行时骨架（`coordination/`）

- `RuntimeCoordinator` 建一次识别器，为每个 `"实例id:角色id"` 起一个 `WorkerRunner`
  线程（`workers/runner.py`），每线程驱一个状态机。
- **事件流**：车头 SM 产出 `rally_launched` → `EventBus` → router → 成员 SM 的
  `on_rally_launched`。`EventBus.publish` 是**同步**的，所以成员把响应延迟放在
  自己线程里 sleep，绝不在 router 里睡（会阻塞车头线程）。
- **跨 SM 重建存活的东西挂在 coordinator 上，不在 SM 里**：`ActionLedger`（进程级动作账本）
  与 `RallyEventTracker`。SM 每轮重建，账本和事件登记簿不重建。
- **判据优先级：账本 > 消息 > 画面**（计划 A，2026-10-01）。`queue_gate.py` 的集结前置门槛
  按这个顺序裁决，画面（模板/YOLO 投票）只是最弱的一层，且**只延迟不翻转**。
  放行时若判据来源不是投票，必须打日志留痕。

### 状态机（`workers/`）

`StateMachine` 基类，`_setup()` 里用 `add_transition(状态, 动作, handler, guard=...)` 声明式建图；
`runner` 反复 `sm.step()` 直到终态。两个关键生命周期事实：

- **正常跑完一轮** → runner 冷却 30s → **重建 SM** 进下一轮。
- **抛异常** → runner **不重建 SM**，在同一状态退避重放，攒满 6 次异常直接停机。

所以「卡住了」必须写成**干净中止本轮**（设 `sm.fail_reason` + 走到 END 边），
不能靠抛异常——抛异常会把一次卡顿升级成停机。环境类原因（`no_action_points` /
`ap_dialog_stuck` / `stale_fortress_target`）不计入连续失败数。

### 识别链（`core/`）

`templates/manifest.yaml` 声明模板条目（`type: template_match` 或 `yolo_detect`、ROI、
阈值、可选 `yolo_threshold`），`TemplateRegistry.build_recognizers()` 装配成
`{template_id: Recognizer}`。要点：

- `type: template_match` 且配了 YOLO 模型时，装配成 `RecognizerChain`：**YOLO 腿在前、
  模板腿在后**，两腿各有独立阈值（模板用 `spec.threshold`，YOLO 用 `yolo_threshold`）。
- `fill_<车头名>` 是例外：**模板在前、OCR 在后**（OCR 慢，不该抢主判据）。配置里点名的
  车头若 manifest 里没条目，runtime 会**就地生成 OCR 判据**（`fill_names`），不用改 manifest。
- 类不在 YOLO 模型里的模板不挂第二条腿。
- `pixel_stats:` 是 manifest 顶层**独立于 `templates:` 的**像素判据段——刻意不进
  `templates:`（会被四个工具 `cv2.imread` 注入垃圾框）。

### 路径与子进程（两个最容易踩的横切面）

- **`infra/app_paths.py`**：`resource_dir()` = 只读资源（冻结后是 `_internal`），
  `user_dir()` = 可写数据（exe 同级）。**任何路径都不许用 CWD 相对**——绿色包双击时
  CWD 可能是 `C:\Windows\System32`。配置里的相对路径用 `resolve_asset()` 解开。
- **`infra/subproc.py`**：fork 外部程序**一律走它**——剥 `QT_*`（否则 MuMuManager 这个
  Qt 程序当场崩）+ `CREATE_NO_WINDOW`（否则 adb 每次调用闪一个黑窗）+ 中性 CWD
  （否则 adb 守护进程钉住解压目录，用户删不掉文件夹）。`tests/unit/infra/test_subproc.py`
  有扫描测试盯着 `src/` 里不许出现裸 `subprocess.run|Popen`。

### 授权（`infra/licensing/`）

`guard.py` 是**唯一门面**，闸门在 `GuiController.start()` 与 `MainWindow._on_start()`。
worker 完全不碰授权——它们是被闸门放行之后才起来的。到期日不落盘，每次从记录里的
Ed25519 签名现算。设计见 `docs/superpowers/specs/2026-10-08-授权与发码平台-design.md`（§12 列了 8 条已知局限，别当成没实现）。

### GUI（`gui/`）

`GuiController` 是 GUI 与运行时的桥：worker 线程经 `EventBus` 发状态，controller 转成
Qt 信号（Qt 自动排队到主线程，跨线程安全）。`MainWindow` + 每角色一张 `CharacterCard`
（内嵌日志，按线程名归属）。

## 环境与坑

- 用 `.venv/Scripts/python.exe`，**别用系统 `python`**（那是 torch+cpu，会静默降级跑 CPU）。
- `tools/*.py` 的中文输出要配 `-X utf8`（控制台是 GBK，含 `✓` 会 UnicodeEncodeError）。
- **bash 双引号里不要出现反引号**——会被当命令替换执行。写文件用 `<<'EOF'` 单引号定界符。
- 删任何图片 / 模板 / 标注前，先确认没有引用（用户明确要求过：**千万不要把在用的清理掉**）。
- **`.pytest_tmp` 是 repo 内的固定 basetemp**：被强杀的 pytest 会留下占住日志文件的
  孤儿进程，之后每次 pytest 都在 setup 阶段抛 `PermissionError [WinError 32]`，
  表现为一大片与被测代码无关的 `E`（integration 52 条能红 37 条）——**极易误判成回归**。
  修法：杀光孤儿 `python.exe` → `rm -rf .pytest_tmp` → 重跑。
- **根目录 `_*.py` / `_*.log` 是探针与验收证据**，`.gitignore` 外但有用；
  `rok_assistant/datasets/` 是 5.2 GB 误落地目录（已 ignore、未删）。
- 真机运行前必须手工做的一步：**两个模拟器都登录并停在地图视图**（归一化靠
  `search_icon`/`alliance_btn` 认地图，停在登录页会白等 900s）。截图确认是 1920×1080。
- 排查启动/连接类问题的第一步永远是 `rok-assistant.exe --selftest`。
