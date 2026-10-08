# 当前状态与待办

> **历史流水已拆出**：实现记录、根因链、修复清单在 docs/HISTORY.md（append-only，平时不用读）。
> 本文件只放**当前状态 / 待办 / 速查**，请保持短——新记录写进 HISTORY.md。
>
> **配置只记作用、不记取值**：文档写「字段管什么」，**不写**「哪个角色配了几级 / 什么预设 / 什么兵种」
> ——那些值会变，写进文档只会过期误导。要核对就直接读 `config.yaml`。
>
> 配套：docs/ACCEPTANCE.md（验收手册）、docs/PACKAGING.md（打包成绿色 zip）、
> docs/配置说明.md（**面向非程序员的逐步配置说明，随绿色包分发**）、
> docs/superpowers/specs/2026-07-15-rok-assistant-design.md（设计）

## 目标（/goal，2026-09-11）

> 程序控制两个模拟器账号完成集结寨子、向配置中的车头填兵。检测车头是否回城，回城后继续开寨子。
> 循环往复直至体力耗尽或完成一定次数（默认十次）。

- 配置 `config.yaml` 描述「谁开车 / 谁填兵 / 搜几级寨 / 用什么预设和兵种 / 填给谁」。
  字段语义与约束见 `docs/ACCEPTANCE.md`，`role` 定义见 `infra/config.py` 的 `RoleEnum`。
- 运行：无头驱动 `_run_goal.py`，banner `max_rounds=10 max_consecutive_failures=3`。

## 当前状态（2026-10-07）

- **全量回归已全绿（2026-10-07）**：`pytest tests/ -q` → **751 passed / 0 failed / 0 error**（6m08s）。
  防检测加固分支（任务 1–6）新增单测后总条数由 711 增至 **751**；此前 10-06 的 711 那次、
  以及更早在 60% 被 OOM 杀掉、无结论的跑批，都已被本次取代。
- **已落地**（实现细节全在 HISTORY 同名一节，这里只留索引）：

  | 日期 | 改动 | 一句话 | 实机 |
  |---|---|---|---|
  | 10-07 | **等级回读 + 连点节奏 + 轮数界面 + 启动预检** | 等级设置改读面板「等级：N」→ 点差量 → 回读校验（点击次数随等级变化）；连点段独立节奏 rapid_click_min/max；max_rounds/失败上限进配置界面 + 跑完自动复位；Start 前自动预检（capture + 1920×1080 + 最多 3 次） | 待实机 |
  | 10-06 | **每实例日志区 + 人性化层** | 卡片内嵌日志（按线程名归属）；HumanProfile 分布化延迟/高斯散布/节奏去规律化/两号解耦 | 待实机 |
  | 10-05 | **启动失败点名 + 文案去噪** | 某台模拟器连不上时，报错写成「模拟器「阑珊填1」（mumu1，MuMu 编号 1）连不上：…」，不再是一句泛泛的「启动失败」；`MumuNotRunningError` 的原始 JSON 移进日志，不进用户可见文本。**语义不变**（仍是一台连不上就都不跑） | ✅ 冻结 |
  | 10-05 | **外部程序统一封装 `infra/subproc.py`** | 剥 `QT_*` + `CREATE_NO_WINDOW`；修掉「点 Start 后黑窗一闪一闪」（见已知问题 11）。所有 fork 外部程序的地方都走它，扫描测试盯着不许再有裸 `subprocess` | ✅ 冻结 |
  | 10-05 | **连接模拟器修好 + 配置说明** | `AdbHandleSource` 自动 `adb connect`（断线自动重连）；配置界面「扫描模拟器」按 MuMu 里的**名字**选（不再猜编号）；界面术语「实例」→「模拟器」，分工/状态/校验错误全中文；新增 `docs/配置说明.md`（随包分发） | ✅ |
  | 10-05 | **绿色 zip 发行包** | 推理后端换 onnxruntime（不带 torch，包 326MB / zip 150MB）；冻结路径走 `resource_dir()`/`user_dir()`；首启自动生成 `config.yaml` + 探测 MuMu 路径；`exe --selftest` 自检 | 冻结冒烟 ✅ |
  | 10-04 | 城寨等级多选 `target_levels` | 有序列表（≤3、**顺序自由**）；每级连搜 5 次无结果换下一级，绕完一圈放弃；GUI 改 1–10 复选框 | ✅ |
  | 10-04 | 纯车头补挂集结前置门槛 | 门槛原先只接在 either 上，纯 leader 拿到的是裸状态机；补挂 + 放行时补写账本回城 | ✅ |
  | 10-04 | YOLO 先行 | 识别链 `[模板, YOLO]` → `[YOLO, 模板]`；`yolo_threshold` 与模板阈值解耦（缺省 0.5） | ✅ |
  | 10-03 | 预设列上移 42px | `selected_preset_*` 取样写死 `cy=474+82*(N-1)`，实机是 `432+…` → 改运行时自校准 | ✅ |
  | 10-01 | 计划 A「判据层」 | 集结门槛 = 多帧投票（**只延迟不翻转**）+ 进程级 `ActionLedger`（账本 > 消息 > 画面） | ✅ |
  | 09-29 | 选中态/排序态改像素判据 | `pixel_stat.py` + manifest 顶层 `pixel_stats:`，不再指望 YOLO 学会 | ✅ |

- **`queue_flag_icon` 漏检已被计划 A 兜住（不再是阻塞）**：该模板仍稳定读 **0.758 < 阈值 0.8**
  （连抓 6 帧方差 0）→ `_queue_verdict` 落 `unknown`。**10-04 实机 10 轮证明**：此时**账本判据接管**
  （17 次 `队列图标不可辨，账本显示部队在外 Xs，继续等待`，source=ledger，WAIT），
  **0 次**走 900s 宽限放行 → 干净闭环不再被挡（详见 HISTORY 同日实机记录）。
  **仍建议重采模板**（HSV 纯圆重裁）以恢复该图标主判，但优先级从「阻塞」降为「清理项」；
  降阈值到 ~0.65 不再是必需。

### 核心闭环链路（实机验证过）

| 环节 | 实现 | 证据 |
|---|---|---|
| 车头开集结 | 归一化→搜寨→设等级（回读差量 + 回读校验，读不出退回盲降）→搜索→详情→红集结→集结弹窗→蓝集结→预设+兵种→行军 | 多轮成功（回读段待实机） |
| 成员填兵 | 点「+」→「创建部队」蓝色气泡 (1515,212) → 表单 → 行军（不点预设/兵种） | 09-12 端到端 |
| 按名字填指定车头 | `fill_<车头名>`：模板匹配（manifest 有条目时）+ OCR 兜底；**配置点名的车头若 manifest 里没有条目，runtime 按名字就地生成 OCR 判据**（`build_recognizers(fill_names=...)`）。固定几何 x=1335 点「+」，他人集结一律不填 | §3.7 已过；10-06 换车头免改 manifest |
| 等待返城 | member END 后轮询队列徽标（30s 间隔 / 25min 上限） | 10-04 十轮闭环 |
| 下一轮循环 | 回城→终态→runner 冷却 30s→重建 SM→下一轮 | 10-04 rounds=1→10 |
| 停止条件 | 跑满 10 轮 / 连续 3 轮失败 / 6 连 step 异常断路器 | 设计内路径 |

### 阈值参考（manifest.yaml，2026-09-16 纯圆重采后实测）

- 队列图标（正 / 负 → 阈值）：`queue_gather_icon` 1.00/≤0.49 (0.75) · `queue_march_icon` 1.000/≤0.47 (0.85)
  · `queue_flag_icon` 1.000/≤0.49 (0.8) · `queue_battle_icon` 0.534-1.0/≤0.466 (0.5)
  · `queue_return_icon` 0.619-1.0/≤0.509 (0.55) · `queue_recall_icon` 1.0,0.719/≤0.506 (0.65)
  · `queue_fight_icon` 0.644-1.0/≤0.441 (0.6) · `queue_badge` 1.000,0.907/≤0.710 (0.85)
- 其它：`replace_popup` 1.000/≤0.277 (0.9) · `join_create_btn`/`ap_refill`/`form_title` 均 1.000/≤0.42 (0.9)
- 红盘系（battle/return/recall/fight）互有串扰，但同判 `battle`，无害。
- **YOLO 腿阈值是另一把尺子**（`TM_CCOEFF_NORMED` vs YOLO conf）：缺省 `DEFAULT_YOLO_THRESHOLD = 0.5`，
  manifest 条目可用 `yolo_threshold:` 覆盖。现役 3 处：`preset_1..6` / `alliance_btn` = `1.01`（关腿）、
  `queue_march_icon` = `0.85`。**换权重后必须重跑 `tools/calibrate_yolo_threshold.py`**。
- **2026-10-07 防检测加固未改模板图、未换 YOLO 权重**（只新增了无图的 `text_fields.fortress_level`
  文本判据，见 HISTORY 2026-10-07），所以本分支**不需要**重跑 `calibrate_yolo_threshold`——上一条的「换权重后必须重跑」
  是通用规则，不是对本次的提醒。

### 授权与发码（2026-10-08）

离线授权已实现：默认 30 天试用，到期后 Start 置灰、可进界面不能跑任务；
激活码用 Ed25519 签名（122 字符），绑主板 UUID + CPU ID。

- 模块：`src/rok_assistant/infra/licensing/`（`codec` / `verify` / `pubkey` /
  `fingerprint` / `store` / `state` / `guard`）。**`guard` 是唯一门面**，
  界面与 worker 只认它。
- 存储三处冗余（注册表 + `C:\ProgramData` + `<user_dir>\.roklicense`），
  **重新解压只清得掉第三处**——这就是防「解压刷新试用期」的全部机制。
- 到期日**不落盘**，每次启动从记录里的签名码现算，所以伪造它需要私钥。
- 设计文档：`docs/superpowers/specs/2026-10-08-授权与发码平台-design.md`
  （§12 列了 6 条**已知局限**，别当成没实现）

## 已知问题（v1 接受）

1. **战斗队列图标单匹配限制**：采集+行军混合在外时可能漏检行军图标误放行（v2 可做多目标计数）。
2. **未知新图标变体仍可能现** → `unknown`；fail-closed 下行为安全（入口拦截等 15 分钟宽限）。
   可按 unknown 窗口截帧补采模板（`_qsamples/` 采样器）。
3. **驱动重启 mid-march 会双集结**：重启后轮次计数清零、SM 重建（09-14 起门槛会在入口拦截，风险已降低）。
4. ~~**adb 断连要手动重连**~~ **10-05 已修**：`AdbHandleSource` 首次使用前自动
   `adb connect`，失败自动重连一次再重试（`_ensure_connected` / `_run_checked`）。
   成功路径零额外调用（`_connected` 只置一次）。实机验证：`adb kill-server` 后
   `adb devices` 为空，`capture()` 仍直接成功。注意重连后游戏可能瞬时不响应点击，
   必要时重启驱动。
5. 体力耗尽无自动用道具功能（未要求）。
6. leader 冷却重建窗口内 rally 事件会丢；错误截图无限速。
   ~~GUI 需 repo 根 CWD~~ **10-05 已修**：路径统一走 `infra/app_paths.py`
   （`resource_dir()` 只读资源 / `user_dir()` 可写数据），冻结后从任意目录启动都行。
7. **`.pytest_tmp` 是 repo 内的固定 basetemp，被杀掉的 pytest 会毒化后续运行**：`test_logger.py` 调的
   `setup_logging` 建的 `FileHandler` **从不关闭**，会一直持有 `.pytest_tmp/**/rok_assistant_*.log`；
   pytest 进程被强杀后文件被占住，之后每次 pytest 都在 setup 阶段抛 `PermissionError [WinError 32]`，
   表现为一大片与被测代码无关的 `E`（integration 52 条能红 37 条），极易误判成回归。
   **修法**：杀光孤儿 `python.exe` → `rm -rf .pytest_tmp` → 重跑。**看到批量 setup 阶段 `E` 先查这个。**
8. **车头 `_launch` 行动力临界**（10-04 实机复现 3 次，均靠 runner 退避自恢复；**同日已修**）：
   `行动力补充后 march_btn 点击失败，集结未发起`。成因：`_refill_ap()` 返回 True 只表示弹窗已关，
   **不表示 AP 已够**；补体力后点行军再次触发 AP 不足弹窗时，旧实现直接抛错，不做二次补体力
   （全靠 runner 退避重试把 `_launch` 重跑一遍才恢复）。
   **修法**：`_launch` 改成「补体力 → 点行军」**有界循环**（`_AP_REFILL_MAX = 3`）：行军点击后
   `ap_refill` 仍复现就再补再点；补满上限仍点不出去才抛错放弃本轮，交 runner 的连续失败计数停机。
   **实机确认待补**（要真跑到体力耗尽）；单测已覆盖两条路径。
9. **`QT_*` 环境变量会传给外部 Qt 程序并让它当场崩**（10-05 定位，**已修**）。
   症状：无头跑 GUI（`QT_QPA_PLATFORM=offscreen`）时 `MuMuManager.exe info -v all`
   要么卡到超时、要么 `returncode=3221226505`（0xC0000409）。**MuMuManager 自己
   就是 Qt 程序**，会去加载父进程指定的平台插件，而它目录里没有 `offscreen` 插件。
   A/B 三连：不设 → rc=0；设 offscreen → rc=3221226505；设了但剥掉 → rc=0。
   **修法**：`infra/mumu.py:child_env()` 剥掉所有 `QT_*`，`MumuLocator._subprocess_run`
   与 `_default_run` 都传它；`AdbHandleSource._subprocess_run` 同样处理。
   **凡是 fork 外部程序的地方都该过一遍 `child_env()`**——别再把它当成
   「MuMuManager 偶发不稳」，那是我当时的误判。
10. **冻结包跑 MuMuManager 比开发机慢 4~6 倍**（10-05 实测，n=30）：
    开发机 `info -v 0` **0.12~0.23s**，打包后的 exe **0.67~1.11s**。
    **别拿开发机的耗时去定超时**——我一度据此把超时从 10s 收到 6s，
    结果有用户启动时撞上假超时（`启动失败：无法运行 MuMuManager…timed out
    after 6.0 seconds`），已改回 10s。
    **排查这类问题先跑 `rok-assistant.exe --selftest`**：其中「MuMu 连接诊断」
    一行会打印 `frozen` / `cwd` / 环境里的 `QT_*` / `_MEIPASS` 是否混进 `PATH`
    / 实际耗时与返回码。它**故意用 20s 超时**（不是正式的 10s），这样超时了
    才说明是真卡死，否则只会复现同一个超时问不出新东西。
    **已排除、别再走一遍**：无控制台（0.6s 正常）、`_internal` 混进 `PATH`
    导致 DLL 抢占（带不带都是 0.13s）、查询未启动/不存在的模拟器（0.14~0.16s）。
    **超时的文案不能说「请检查安装路径」**——超时说明路径是对的、程序也起来了，
    说成路径问题会把人带偏（用户实际就是这么被误导去反复改路径的）。
    **10-05 补**：`--selftest` 加了一项「各模拟器连接（只诊断，不判定）」——
    照 `config.yaml` 逐台 `create_handle_source` + 真截一帧，把每台的结果
    （成功/异常全文/耗时）打进自检日志。失败发生在 `create_handle_source`
    阶段时 **worker 还没起来，运行日志里一个字都没有**，只有这一项看得见。

11. **点 Start 后黑窗一闪一闪、持续不断**（10-05 定位，**已修**）。
    成因：绿色包是 `console=False` 的 GUI 程序，**自身没有控制台**；而 `adb.exe`
    与 `MuMuManager.exe` 都是**控制台子系统**程序（PE Subsystem=3）。父进程没有
    控制台时，Windows 会给每个这样的子进程**新开一个控制台窗口**。
    **adb 每截一帧、每点一下都起一次**，所以是连成串地闪。
    无控制台父进程里的 A/B 实测：裸 `subprocess.run` → `['PseudoConsoleWindow']`
    可见窗口 1 个；走 `infra/subproc.run` → 0 个。
    **修法**：新增 `infra/subproc.py`（`child_env()` 剥 `QT_*` + `CREATE_NO_WINDOW`），
    **所有** fork 外部程序的地方改走它（`handle_source` / `mumu` 两条 runner / `selftest`）。
    `tests/unit/infra/test_subproc.py` 有一条扫描测试盯着 `src/` 里不许再出现裸
    `subprocess.run|Popen`。**这两个标志只在打包后才看得出问题**——从终端跑源码时
    父进程有控制台、环境也干净，怎么试都是好的。

12. **「点 Start 后只连上一台，另一台报错」——未能复现，未确认根因**（10-05）。
    用户的运行日志里**两个 worker 都跑到待机、零 ERROR**；没有 `recordings/`
    目录（runner 的 `error` 状态从未触发）；同机同配置下源码与冻结**两台都连得上**。
    已按**最可能的情况**修掉「说不清是哪一台」这个真问题（见「已落地」表里的「启动失败点名 + 文案去噪」一行），
    **但那不是已确认的根因**。用户记不清报错原文了。
    **下次再遇到先看这两处**：`logs/selftest.log` 的「各模拟器连接」一行
    （`create_handle_source` 阶段的失败**只有这里看得见**，worker 没起来时运行日志
    一个字都没有），以及报错弹窗的原文。

- **授权是离线方案，有硬上限**：三处存储全删干净仍可重置试用（旧延长码还能
  再吃一次）；改 exe 跳过校验可行；记录里的 HMAC 密钥可由主指纹推出来。
  完整清单见 `docs/superpowers/specs/2026-10-08-授权与发码平台-design.md` §12。

## 接下来需要做的

### 待办
- [ ] **等级回读的野蛮人页守卫（spec §9）**：面板记住上次 Tab，而野蛮人页也有
      等级。若 `tab_fortress` 那次点击失败、且野蛮人页的等级行落在同一 ROI
      （100,470,1040,620），回读会读出一个**看似合法**的数字，且因为回读自洽
      而不会被自纠机制发现。**实机在城寨页与野蛮人页各截一帧**，确认该 ROI
      只在城寨页读出「等级：N」。两页都读得出才需要加守卫。
- [ ] **等级回读在快速连点后是否读到已刷新的帧**：`JitteringHandleSource.click` 是**先 sleep 再点**，
      所以连点段（`_set_level` 的差量点击）走完后**没有**落定延迟，`_verify_level` 的校验 capture
      紧跟最后一次点击，可能读到点击尚未生效的旧帧 → 回读仍 ≠ 目标 → 多补一轮差量。
      **实机确认**快速连点后是否需要一次 settle（评审 Task 4 时标出）。
- [ ] **连点节奏 0.35s 下限实机确认不丢点击**：2026-09-11 实测的安全值是 **0.4s**
      （0.4s 间隔连点 19 次零丢失），而常量 `_LEVEL_CLICK_PACE` 当时就取 0.35s，
      **低于实测安全值**；现在间隔由 `anti_detection.rapid_click_min`（0.35）持有，
      动作延迟组合也变了。故须实机确认真机不丢点击。
- [ ] **人性化层实机观察（仍未跑）**：跑 2~3 轮确认无卡顿。
      **重点盯「点击落空」**：坐标散布从硬编码 **±8px** 改成了高斯裁剪到 **±3σ**，
      σ 默认 8 时最远能甩到 **±24px**（旧值的三倍），**小目标最可能被甩出去**——
      等级 **+/- 按钮**、小号**确认按钮**这类。命中问题表现为「点了没反应 / 卡在[某视图]」，
      按 `grep -E "卡在\[" _driver.log` 看。
      **2026-10-06 用户裁定跳过该闸门先合并**——人性化层已随本分支进 main，
      但**仍属未经真机验证**。实机一旦出现「点了没反应 / 卡在[某视图]」，
      优先怀疑坐标散布（散布参数在 config.yaml，可回滚到硬编码抖动）。
- [x] **绿色包冻结冒烟**（10-05）：`dist/rok-assistant/rok-assistant.exe --selftest` **9/9 通过**
      （cv2 解码往返、ONNX 单帧 30ms、59 个识别器、OCR 模型就位、config.yaml 生成并校验）；
      GUI 启动存活 12s、无 `startup_crash.log`。**首启自动探测到 MuMu 路径**
      （`C:\模拟器\MuMuPlayer\nx_main\`）。
- [ ] **干净机测试**：把 zip 拷到没装 Python 的机器/虚拟机解压 → 跑 `--selftest` → 实机跑一轮。
      **本机不算数**（开发机有 venv，掩盖打包遗漏）。
- [ ] **实机跑一轮**（冻结包连真模拟器）：`--selftest` 只证明识别链路通，不证明点击链路通。
- [x] **`target_levels` 多选的实机验证**：10-04 实机触发 2 次
      `[车头] 6 级连续 5 次搜不到，改搜 5 级（列表第 2/3 个）`，随后设 5 级并成功发起集结。
- [x] **计划 A 的实机验证**：10-04 实机 **0 次** 900s 宽限放行、**17 次** `账本显示部队在外…继续等待`
      （source=ledger），干净跑满 10 轮。
- [x] **完整闭环观察**：10-04 实机两号各 `10/10 轮完成`、驱动自行 `全部 worker 已收工`，无停机干预。
- [x] **体力耗尽补充路径修复**（10-04）：`_launch` 的「补体力→点行军」改为有界循环
      （`_AP_REFILL_MAX = 3`），补一次不够会自动再补再点，不再直接抛错。单测两条：
      `test_launch_refills_ap_repeatedly_until_march_goes_out`（补两轮后发出）/
      `test_launch_gives_up_after_ap_refill_cap`（补到上限放弃，不死循环）。见已知问题 8。
- [ ] 体力耗尽路径**实机**确认（真跑到用完行动力）——代码已改，等一次自然耗尽或手动压体力。
- ~~验收剩余 3 项（§3.3/§3.4/§3.5）~~ **已删除**：用户 2026-10-04 裁定这三项不再要求单独验收，
  对应小节已从 `ACCEPTANCE.md` 移除（编号保留跳跃，代码注释仍引用 §3.3/§3.5）。

### 计划 A 已知缺口（评审裁定为后续项，非遗漏）
- [ ] **填兵方账本 `troops_out` 永不清零**（约每两轮一次）：要么在计划 B 落地 FillTask 时一并修，
      要么等实机再次出现填兵方的 `未知队列图标已持续 900.0s` 再修。
      **纯 leader 一侧已随 10-04 改动关闭**；**方向安全**（账本只产出 WAIT，永不错误放行，
      行为与计划 A 之前逐字相同，**不是回归**）。原因与完整推导见 HISTORY 计划 A 一节。

### 数据集补图（v10 前置）
> **09-29 起降级**：`selected_preset_*` 与 `sort_*` 的**运行时识别已由像素判据接管**，补图只是「让 val 指标
> 好看」，**不是功能前置**（两类作为数据集类继续存在，预览的 YOLO 腿仍输出，但已被 `annotate_live` 滤掉）。
- [ ] **撤掉 0 框帧污染**（`tools/audit_empty_frames.py`）：777 帧里 31 张空标签，其中 24 张是模板素材裁剪图。
      预期 777→752 帧、train 708→684、val 69→67——**val 组成会变，指标不能与上一版直接比**。
      **写盘那步被权限分类器拦下，需手动跑**（命令见 HISTORY 的 10-03 一节）。
- [ ] **`city_btn` 进 val**：27 条全在 train，val 零实例 → 指标测不了。
- [ ] `queue_gather_icon`：v8/v9 在全部 5 个 val 帧上零检出（YOLO 兜底本就是死的，靠模板主判）。

### 收尾清理（验收通过后）
- [x] 删根目录 `_*.png` 散落截图、`_cap8/`、`_qsamples/`、`logs/annotate/*`（09-21，~784 MB）。
      **保留** `_run_goal.py` / `_kill_driver.ps1`（启停入口）、`_goal_run*.log`（验收证据）、`_train_v*.log`。
- [x] 删 09-21/27 标注期的临时探针与渲染图（09-27）。**保留** `logs/_cmp_v8_v9.txt`（v8/v9 同 val 对比）、
      `logs/review/_relabel_*.png`（三遍补标叠框复核）、`logs/_boxcheck/`（污染源原始证据）。
- [ ] 删临时脚本：`_capture_driver.py`、`_watch_join.py`、`_recapture_templates.py`、`_name_templates.py`、
      `_collect_queues.py`、`_probe_queue.py`（10-04 验集结门槛用，只读打印队列各模板分数）。
- [ ] 删 `/tmp/kill_driver.ps1`；`recordings/failure_*.png` 酌情清理。
- [ ] 未跟踪大件：`rok_assistant/datasets/`（5.2 GB 误落地 COCO，只加了 .gitignore、**没删**）。

### v2 候选（未排期）
同实例多账号切换（switcher 已有，每实例单角色限制在 either_sm）· 采集宝石 / 自动用体力道具 ·
PC 客户端支持 / 行为仿真（鼠标轨迹）· 采集+行军混合队列的多目标图标计数（消除已知问题 1）

## 关键操作速查

```bash
# 启动驱动（repo 根；必须 nohup 脱离式，harness 的 run_in_background 会被看门狗杀）
nohup .venv/Scripts/python.exe -X utf8 _run_goal.py > _driver.log 2>&1 &

# 杀驱动（bash 内联 PowerShell 的 $_ 会被转义破坏，必须用 repo 根的脚本文件）
powershell -NoProfile -ExecutionPolicy Bypass -File _kill_driver.ps1

# adb 重连（模拟器重启后）—— 程序自己会连，一般不需要手动跑；
# 手动排查连接问题时才用：
C:/模拟器/MuMuPlayer/nx_main/adb.exe connect 127.0.0.1:16384   # mumu0
C:/模拟器/MuMuPlayer/nx_main/adb.exe connect 127.0.0.1:16416   # mumu1

# 列出 MuMu 里所有模拟器（名字 / 是否运行 / adb 地址）—— 配置界面的「扫描模拟器」同源
.venv/Scripts/python.exe -X utf8 -c "from rok_assistant.infra.mumu import list_instances as L; print(*L(r'C:/模拟器/MuMuPlayer/nx_main/MuMuManager.exe'), sep='\n')"

# 打绿色 zip 包（含前置检查 / 产物断言；详见 docs/PACKAGING.md）
.venv/Scripts/python.exe -X utf8 tools/build_package.py

# 验证打出来的包能不能用（不开窗口，跑真实识别链路）
./dist/rok-assistant/rok-assistant.exe --selftest

# 导出 ONNX 权重（换权重后必跑；导出后还要重跑 calibrate_yolo_threshold）
.venv/Scripts/python.exe -X utf8 tools/export_onnx.py

# 回归测试（期望全部通过，以实际输出为准）
.venv/Scripts/python.exe -m pytest tests/ -q

# 监控日志
grep -E "发起|填兵|锁定|已回城|集结门槛|失败结束|异常" _driver.log | tail

# 发码（作者本机；首次运行会生成密钥对并把公钥写进 pubkey.py——记得提交）
.venv/Scripts/python.exe -X utf8 tools/license_tool.py

# 只重新生成/恢复 pubkey.py（私钥还在时复用它，不换密钥对）
.venv/Scripts/python.exe -X utf8 tools/gen_license_keypair.py

# 看本机机器码（报障时让用户抄这一行）
.venv/Scripts/python.exe -X utf8 -m rok_assistant.infra.selftest
```

### 实机运行手册

**Step 0 — 起模拟器并确认实例真的起来了。** 只有 MuMu 启动器窗口 ≠ 实例在跑：

```bash
# is_android_started / player_state 必须是 true / start_finished
"C:/模拟器/MuMuPlayer/nx_main/MuMuManager.exe" info -v all
```

**adb 连接不用手工做了**（10-05 起 `AdbHandleSource` 自动 connect）。下面只在
排查连接问题时跑；`adb connect` 报 `10061 目标计算机积极拒绝` 通常是
**adb server 没起**，不是模拟器没起：

```bash
ADB=C:/模拟器/MuMuPlayer/nx_main/adb.exe
"$ADB" kill-server; "$ADB" start-server
"$ADB" devices                    # 手动排查时才需要 connect
```

**Step 1 — 两号都登录并停在地图视图。** 这是唯一必须手工做的：归一化靠 `search_icon`/`alliance_btn`
认地图，停在登录页/活动弹窗会让门槛在 unknown 上白等 900s。截图确认是 1920×1080（不是竖屏）：

```bash
"$ADB" -s 127.0.0.1:16384 exec-out screencap -p > _probe0.png
"$ADB" -s 127.0.0.1:16416 exec-out screencap -p > _probe1.png
# 看两张图：应都是地图界面（右下有队列栏、左下放大镜）
```

**Step 2 — 核对配置。** 读 `config.yaml` 确认：各号 `target_levels` 的寨子搜得出来（搜空会连续计失败）、
`fill_target_leaders` 互相指向、`role` 取值合法。**文档不记具体配置值，以 `config.yaml` 为准。**

**Step 3 — 启动驱动**：见上面速查（必须 `nohup` 脱离式）。点 Start 会先自动预检每台模拟器
（建句柄 + 真截一帧 + 校验 1920×1080），失败会点名是哪一台、并说明实际截到的尺寸；
预检通过时状态栏会写「预检通过：N 台模拟器」。

**Step 4 — 观察（跑 2~3 轮，每轮约 20 分钟）**：

```bash
grep -E "集结门槛" _driver.log | sort | uniq -c | sort -rn
#   期望「放行（判据来源 ledger）」/「grace」并带原因；不再有「未知队列图标已持续 900.0s，放行搜索」
#   已知例外：填兵方那一号仍走 900s 宽限（见「计划 A 已知缺口」）

grep -E "卡在\[" _driver.log | tail
#   形如「归一化失败：卡在[创建部队]视图」；一轮跑完没出现也算通过
#   若「卡在[」明显变多 → 恢复 _search_fortress 的 3 次重试（Ruling 18）

grep -E "预设槽|预设列基准" _driver.log | tail
#   期望「预设槽 N 已确认（模板点击，第 1 轮）」；不再有「高亮未确认（3 轮），拒绝派错兵」
#   面板若又整体移位，会先「预设列基准自校准 -> 槽 1 cy=…」再确认（修好的路径，不是异常）

grep -E "改搜|已试等级" _driver.log    # target_levels 降级路径（10-04 新增）
grep -cE "异常|Traceback" _driver.log  # 期望 0
```

**Step 5 — 停止**：驱动跑满 10 轮或连续 3 轮失败会自己收工；手动停用 `_kill_driver.ps1`。
