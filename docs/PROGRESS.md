# 当前状态与待办

> **历史流水已拆出**：各会话的实现记录、根因链、修复清单在
> docs/HISTORY.md（append-only，平时不用读）。
> 本文件只放**当前状态 / 待办 / 速查**，请保持短——新记录写进 HISTORY.md。
>
> 配套文档：docs/ACCEPTANCE.md（验收手册）、docs/session-2026-09-16-误开车根因修复.md、
> docs/session-2026-09-20-方案B标注与v7训练.md、docs/superpowers/specs/2026-07-15-rok-assistant-design.md（设计）

## 目标（/goal，2026-09-11 设定）

> 通过辅助工具程序控制两个模拟器账号能正常的完成集结寨子、向配置中的车头填兵。
> 检测集结车头是否回城，回城后继续开寨子。循环往复直至体力耗尽或者完成一定的
> 次数（先默认十次）。

- 配置（2026-10-03 实读 `config.yaml`，用户已改过一轮）：mumu0「阑珊寨子号」(either, **7 级**) ⇄ mumu1「**阑珊填1**」(either, **8 级**) 互相填兵，骑兵、预设槽 1。
  ⚠️ **8 级待确认**：09-18 曾实测「8 级寨搜不到」（run2 mumu1 六搜全空）才降的 7 级；现 mumu1 又被设回 8 级，跑之前先确认 8 级寨刷得出来，否则 mumu1 会连续搜空计失败。
- 运行方式：无头驱动 `_run_goal.py`（`nohup .venv/Scripts/python.exe -X utf8 _run_goal.py > _driver.log 2>&1 &`），banner `max_rounds=10 max_consecutive_failures=3`


## 当前状态（2026-10-01）

- **测试 478 绿**（423 → 478）。`config.yaml app.yolo_model` 指向 **gpu_1080_v9**（切它是为功能不是指标，回滚换成 `runs/gpu_1080_v8/weights/best.pt`）。
- **10-01：计划 A「判据层」已落地**（spec `2026-09-30-健壮状态判断与任务队列-design.md` 前半；12 commits `0cfd458..2f3a5c7`，细节见 HISTORY 的 10-01 一节）：
  - **集结门槛改为「投票 + 账本」**（`coordination/action_ledger.py` + `workers/queue_gate.py`）。判据分层 **账本 > 消息 > 画面**；**多帧投票只能延迟、永不翻转**（不得把 unknown 变成放行）。
  - **账本写入点**：车头发车确认后 / 成员填兵确认后 / 返城时；**未确认不写**。`runtime` 给三个 SM 下发**同一个** `ActionLedger` 实例（按对象同一性测试钉住）。
  - **视图归因**：`recognizers/view_probe.py` 一次截屏判 7 视图 + 未知；归一化失败改报 `归一化失败：卡在[创建部队]视图`。
  - **两号不同等级**：`infra/config.py find_level_collisions` 在「同等级且至少一方填对方」时启动告警。当前配置是 **7 级 ⇄ 8 级，不会命中告警**（`find_level_collisions` 返回空）；这正是计划 B 删 `_FOREIGN_RALLY_WINDOW` 让车门槛的前提条件。
  - **实机验证未跑**（Task 8 Step 2/3 推迟）：模拟器没起（`adb devices` 空，`:16384`/`:16416` 报 10061 拒绝）。**跑法见下面「关键操作速查 → 实机运行手册」**。
  - **收尾（2026-10-03）**：15 commits `0cfd458..72466e3`；全套 **481 passed**；最终评审 0 Critical / 2 Important（一修一 park）/ 5 Minor 全 park；定向复评「all findings addressed, no new breakage」。SDD 工作区已删。
  - **28 条裁定（含「错了会怎样」）存档在 `docs/HISTORY.md` 的「计划 A 裁定存档」**——回头先读 #18、#26（带触发条件）与 #4/#7/#8/#12（将来改动会撞到）。
- **09-29：选中态/排序态改由像素判据接管**（`recognizers/pixel_stat.py` + manifest 顶层 `pixel_stats:`）。细节见 HISTORY 的 09-29 一节。6 个 commit，**未 push**。
- **实机验证已过**：
  - 预设槽：`[车头] 预设槽 1 已确认（模板点击，第 1 轮）`——真机真弹窗一次点击确认，没走几何兜底、没抛异常（20:31:40）。
  - 排序条：战争列表帧上预览画出 `排序选择器 0.04 ◇像素`，框套在「最新发起」上，YOLO 那类的输出被正确滤掉。
- **当前阻塞（挡住干净闭环，非计划 A 改动引入）**：`queue_flag_icon` 在队列栏上**稳定读 0.758 < 阈值 0.8**（连抓 6 帧方差 0；位置对、其它队列模板全 ≤0.45）→ `_queue_verdict` 落到 `unknown`。
  **计划 A 只挡住了一半，没消除**：账本现在能在「本轮自己发起过」时直接判 WAIT，不再靠宽限放行；
  但**跨轮 / 驱动重启后的第一个 unknown 仍会落到 900s 宽限放行**。而且**多帧投票对这个漏检
  完全无效**——读数方差为 0，投票只是把同一个错答案数三遍（这正是计划 A 把投票限制为
  「只能延迟、不能翻转」的原因）。**真正的修法仍是重采模板**（HSV 纯圆重裁 + 重测正负样本），需要实机截图。
  **因果链（09-29 20:40~20:46 实机）**：unknown 是 fail-closed「按在外处理」→ 门槛拦住搜索并等 900s 宽限 → 宽限到点告警放行 → 车头此时部队其实在外，**开集结被游戏静默拒绝** → `rally_rejected` 计入连续失败 → mumu0 连吃 2 次（2/3，再 1 次整轮停机）。
  注意方向性：蓝旗语义是「驻扎/集结等待」=**阻塞**态。**读对了反而会拦住这次注定被拒的开车**。所以 0.758 漏检不是「多等一会」，是**把安全的拦截变成了有害的放行**。
  若重采后负样本仍 ≤0.5，把该模板阈值降到 ~0.65 是次选（假阳只多等 15 分钟，假阴是整轮停机）——但这是拿假阳换假阴，不如重采。
- **驱动已自行退出**（10-01 核对：无 `python` 进程，`_driver.log` 末次写入 09-30 18:49，末行 `mumu0 … 已完成 10 轮，达到轮数上限 | mumu1 … state=paused rounds=2`）。**别再跑 `_kill_driver.ps1`**。
- 未跟踪的大件：`rok_assistant/datasets/`（5.2 GB 误落地 COCO，只加了 .gitignore、**没删**）。

### 核心闭环链路（实机验证过）
| 环节 | 实现 | 实机证据 |
|---|---|---|
| 车头开集结 | 归一化→搜寨→设等级（缓存差量）→搜索→详情→红集结→集结弹窗→蓝集结→预设1+骑兵→行军 | 多轮成功（22:08、22:17、23:21 等） |
| 成员填兵 | 点「+」→ **「创建部队」蓝色气泡按钮 (1515,212)** → 表单 → 行军（默认兵队，不点预设/兵种） | 01:12 端到端实锤（09-12） |
| 按名字填指定车头 | `fill_<车头名>` 名字模板匹配目标行，固定几何 x=1335 点「+」，他人集结一律不填 | §3.7 已过 |
| 等待返城 | member END 后轮询派遣队列徽标（30s 间隔 / 25min 上限） | 22:15 完整闭环一次 |
| 下一轮循环 | 回城→终态→runner 冷却 30s→重建 SM→下一轮 | mumu0 rounds=1→2（09-13） |
| 停止条件 | 跑满 10 轮 / 连续 3 轮失败（疑似体力耗尽）/ 6 连 step 异常断路器 | 设计内路径 |

### 阈值参考（manifest.yaml，正/负分数实测，均为 2026-09-16 纯圆重采后）
`queue_gather_icon` 1.00/0.99/0.84 跨头像、负 ≤0.49 (0.75) · `queue_march_icon` 1.000/负 ≤0.47 (0.85) · `queue_flag_icon` 1.000/负 ≤0.49 (0.8) · `queue_battle_icon` 正 7 帧 0.534-1.0、非红盘负 ≤0.466 (0.5) · `queue_return_icon` 正 5 帧 0.619-1.0、非橙盘负 ≤0.509 (0.55) · `queue_recall_icon` 正 1.0/0.719、负 ≤0.506 (0.65) · `queue_fight_icon` 正 0.644-1.0（逐帧动画变体间仅 0.62-0.90）、真负 ≤0.441 (0.6) · `queue_recall_icon`（战斗动画「伪上箭头」帧，非召回态）正 1.0/0.719、负 ≤0.506 (0.65) · `queue_badge` 正 1.000/0.907、负 ≤0.710 (0.85) · `replace_popup` 1.000/≤0.277 (0.9) · `join_create_btn`/`ap_refill`/`form_title` 均 1.000 正、≤0.42 负 (0.9)。红盘系（battle/return/recall/fight）互有串扰但同判 battle 无害

## 已知问题（v1 接受）

1. **战斗队列图标单匹配限制**：采集+行军混合在外时，单点模板匹配可能漏检行军图标误放行（注释已记录，v2 可做多目标计数）
2. **未知新图标变体仍可能现**：09-14/16 已把五态补齐模板（战斗为动态多形态：交叉 X/平行双剑/伪上箭头挥舞帧，共 7 个模板；09-16 二次误开车根因即「返程/战斗态无模板被采集锄头掩盖」），但游戏图标可能还有未见的动画帧/新状态 → verdict=unknown，fail-closed 下行为安全（入口拦截等 15 分钟宽限）；`_qsamples/` 采样器持续在跑，可按 unknown 窗口截帧补采模板
3. **驱动重启 mid-march 会双集结**：重启后轮次计数清零、SM 重建（09-14 起新门槛会在入口拦截城外部队，风险已大幅降低）
4. **adb 断连**：模拟器重启后报「模拟器窗口失联」paused——需 `adb connect 127.0.0.1:16384` / `:16416`，重连后自动恢复（无需重启驱动）。注意：断连重连后游戏可能瞬时不响应点击（09-14 22:18 mumu1 六连 normalize 异常停机），必要时重启驱动
5. 体力耗尽无自动用道具功能（未要求；mumu0 曾 77/140，走 3 轮失败停机）
6. leader 冷却重建窗口内 rally 事件会丢；config 路径锚定（GUI 需 repo 根 CWD）；错误截图无限速

## 接下来需要做的

### 计划 A 已知缺口（最终评审确认，已裁定为后续项，不是遗漏）
- [ ] **填兵方的账本 `troops_out` 永不清零**——`mark_troops_home` 只在 `either_sm.py:355`（`WAIT_RETURN` 判空）调用，而 `_enter_wait_return`（`:214`）要求 `leader.last_rally_event`。**只填兵不开车的轮次**（对方先开车 → 让车门槛让自己转填兵，约每两轮一次）不进 `WAIT_RETURN`，于是该号账本一直停在「部队在外」。
  **影响**：下一个 `unknown` 上账本说「在外」→ 仍走 900s 宽限 → 计划 A 的头号收益（消掉 `未知队列图标已持续 900.0s，放行搜索`）**对这一号没兑现**。
  **但方向安全**：账本只会产出 WAIT，永远不会错误放行；且行为与计划 A 之前逐字相同，**不是回归**。
  **为什么没当场修**：spec 的写入点表（`specs/2026-09-30-...-design.md:148-153`）本来就把清零只挂在 `WAIT_RETURN` 上——这是 spec 自身的缺口，不是实现偏离。正确修法是给填兵方一条「自己的部队回城」确认路径，属计划 B 的 FillTask/续跑语义；在计划 A 里改等于重写 `_enter_wait_return` 的入场条件（事故编码逻辑），且现在没有实机可验证。
  **触发条件**：计划 B 落地 FillTask 时一并修；或实机日志里再次出现填兵方的 `未知队列图标已持续 900.0s` 时提前修。

### 验收剩余项
- [ ] **计划 A 的实机验证（Task 8 Step 2/3，因模拟器未启动而推迟）**：启 MuMu → `adb connect` 两号 → 跑 `_run_goal.py` 2~3 轮 → `grep -E "集结门槛" _driver.log` 期望出现 `放行（判据来源 ledger）` / `grace` 且**不再有** `未知队列图标已持续 900.0s，放行搜索`；再 `grep -E "卡在\[" _driver.log` 看归一化失败是否可读
- [ ] **完整闭环观察**：干净地跑一轮「开集结→互填→等回城→下一轮」多圈连续循环（目标 10 轮），确认无停机干预——09-18 幽灵集结四重防护落地后 run12 观察中（`_goal_run12.log`；预期节奏：每轮 ~20 分钟，一号车头另一号填兵，输家轮空转填兵）
- [ ] C（§3.5 关模拟器→paused→重开恢复；注意 adb connect）
- [ ] D（§3.4 集结 5 分钟无人填超时→自动下一轮）
- [ ] E（§3.3 锁定城寨→跳过重搜）——09-13 23:42 mumu1 连续 4 次锁定后路径已部分验证
- [ ] 体力耗尽路径实机确认（mumu0 用完行动力跑一次）

### 数据集补图（v10 前置）
> **09-29 起降级**：`selected_preset_*` 与 `sort_*` 的**运行时识别已改由像素判据接管**（见上节），
> 不再需要靠补样本让 YOLO 学会。这两个类作为**数据集类**继续存在（预览的 YOLO 腿仍会输出，
> 但已被 `annotate_live` 滤掉），所以补图只是「让 val 指标好看」，**不是功能前置**。
- [ ] ~~**选中态 `selected_preset_2/3/5/6`** 各补 10+ 帧~~ → **已由像素判据解决，不再是前置**
- [ ] ~~**战争列表收起态**：`sort_selector` 补 10+ 帧~~ → **同上**（激活项仍无判据，那是另一件事）
- [ ] **`city_btn` 进 val**：27 条全在 train，val 零实例 → 指标测不了
- [ ] `queue_gather_icon`：v8/v9 在全部 5 个 val 帧上都零检出（YOLO 兜底本就死的，靠模板主判）。要让它进兜底得先补 val 帧

### 收尾清理（验收通过后）
- [x] 删根目录 `_*.png` 散落临时截图、`_cap8/`、`_qsamples/`、`logs/annotate/*`（2026-09-21，共 ~784 MB）。**保留** `_run_goal.py` / `_kill_driver.ps1`（速查表里的启停入口）与 `_goal_run*.log`（验收证据）、`_train_v*.log`
- [x] 删 09-21/27 标注期的临时探针与渲染图（2026-09-27）：`tools/_probe_{home,preset,sort,newframes,v9,v9b,gather}.py`、`tools/_view.py`、`logs/_*.png`、`logs/_*.txt`。**保留** `logs/_cmp_v8_v9.txt`（v8/v9 同 val 对比证据）、`logs/review/_relabel_*.png`（三遍补标的叠框复核图）、`logs/_boxcheck/`（用户指认污染源的原始证据）。v9 训练日志按惯例挪到根目录 `_train_v9.log`
- [ ] 删临时脚本：`_capture_driver.py`、`_watch_join.py`、`_recapture_templates.py`、`_name_templates.py`、`_collect_queues.py`
- [ ] 删 `/tmp/kill_driver.ps1`（杀驱动用的 PowerShell 脚本；bash 内联 `$_` 会被转义破坏，必须走 .ps1 文件）
- [ ] `recordings/failure_*.png` 酌情清理
- [ ] 更新 `docs/ACCEPTANCE.md`（仍停留在 185 测试/「验收未开始」状态）

### v2 候选（未排期）
- 同实例多账号切换（switcher 已有，每实例单角色限制在 either_sm）
- 采集宝石 / 自动用体力道具
- PC 客户端支持、行为仿真（鼠标轨迹）
- 采集+行军混合队列的多目标图标计数（消除已知问题 1）

## 关键操作速查

```bash
# 启动驱动（repo 根目录）
nohup .venv/Scripts/python.exe -X utf8 _run_goal.py > _driver.log 2>&1 &

# 杀驱动（bash 内联 PowerShell 会坏，用 repo 根的脚本文件）
powershell -NoProfile -ExecutionPolicy Bypass -File _kill_driver.ps1

# adb 重连（模拟器重启后）
C:/模拟器/MuMuPlayer/nx_main/adb.exe connect 127.0.0.1:16384   # mumu0
C:/模拟器/MuMuPlayer/nx_main/adb.exe connect 127.0.0.1:16416   # mumu1

# 回归测试（期望全部通过，以实际输出为准）
.venv/Scripts/python.exe -m pytest tests/ -q

# 监控日志
grep -E "发起|填兵|锁定|已回城|集结门槛|失败结束|异常" _driver.log | tail
```

### 实机运行手册（跑一轮完整验收）

**Step 0 — 起模拟器并确认实例真的起来了。** 只有 MuMu 启动器窗口 ≠ 实例在跑；
`adb connect` 报 `10061 目标计算机积极拒绝` 通常是 **adb server 没起**，不是模拟器没起：

```bash
# 先看实例真实状态（is_android_started / player_state 必须是 true / start_finished）
"C:/模拟器/MuMuPlayer/nx_main/MuMuManager.exe" info -v all

# 重起 adb server 再连（连不上先做这一步，多半就好了）
ADB=C:/模拟器/MuMuPlayer/nx_main/adb.exe
"$ADB" kill-server; "$ADB" start-server
"$ADB" connect 127.0.0.1:16384   # mumu0（config.yaml mumu_index: 0）
"$ADB" connect 127.0.0.1:16416   # mumu1（config.yaml mumu_index: 1）
"$ADB" devices                    # 两个都要是 device，不是 offline
```

**Step 1 — 两号都登录并停在地图视图。** 这是唯一必须手工做的：
车头的归一化要靠 `search_icon`/`alliance_btn` 认地图。任一账号停在登录页/活动弹窗，
门槛会在 unknown 上白等 900s 宽限。截图确认 1920×1080（不是 1080×1920）：

```bash
"$ADB" -s 127.0.0.1:16384 exec-out screencap -p > _probe0.png
"$ADB" -s 127.0.0.1:16416 exec-out screencap -p > _probe1.png
# 看两张图：应都是地图界面（右下有队列栏、左下放大镜）
```

**Step 2 — 核对配置。** 当前 `config.yaml`：mumu0「阑珊寨子号」7 级 ⇄ mumu1「阑珊填1」8 级。
⚠️ **8 级是 09-18 实测「搜不到寨子」才降下来的**，先确认 8 级寨刷得出来，否则 mumu1 连续搜空计失败。

**Step 3 — 启动驱动**（必须 `nohup` 脱离式；harness 的 run_in_background 会被看门狗杀）：

```bash
nohup .venv/Scripts/python.exe -X utf8 _run_goal.py > _driver.log 2>&1 &
```

**Step 4 — 观察（跑 2~3 轮，每轮约 20 分钟）。** 本次要验的就是这几条：

```bash
grep -E "集结门槛" _driver.log | sort | uniq -c | sort -rn
#   期望：出现「放行（判据来源 ledger）」或「grace」并带原因
#   期望：不再出现「未知队列图标已持续 900.0s，放行搜索」
#   期望：「队列图标不可辨」条数大幅下降（原本 166 次）
#   已知例外：填兵方那一号仍会走 900s 宽限（见「计划 A 已知缺口」）

grep -E "卡在\[" _driver.log | tail
#   期望：形如「归一化失败：卡在[创建部队]视图」；一轮跑完都没出现也算通过
#   注意 Ruling 18 的触发条件：若「卡在[」明显变多，恢复 _search_fortress 的 3 次重试

grep -E "预设槽" _driver.log | tail          # 期望「已确认（模板点击，第 1 轮）」
grep -cE "异常|Traceback" _driver.log        # 期望 0
```

**Step 5 — 停止**（驱动跑满 10 轮或连续 3 轮失败会自己收工；手动停用脚本）：

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File _kill_driver.ps1
```
