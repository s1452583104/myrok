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

- 配置：mumu0「阑珊寨子号」(either, 7级) ⇄ mumu1「Jy丶阑珊」(either, 7级) 互相填兵，骑兵、预设槽 1（两号 8 级寨 09-18 夜间实测刷不出，均降 7 级）
- 运行方式：无头驱动 `_run_goal.py`（`nohup .venv/Scripts/python.exe -X utf8 _run_goal.py > _driver.log 2>&1 &`），banner `max_rounds=10 max_consecutive_failures=3`


## 当前状态（2026-09-29 晚）

- **测试 423 绿**。`config.yaml app.yolo_model` 指向 **gpu_1080_v9**（切它是为功能不是指标，回滚换成 `runs/gpu_1080_v8/weights/best.pt`）。
- **09-29：选中态/排序态改由像素判据接管**（`recognizers/pixel_stat.py` + manifest 顶层 `pixel_stats:`）。细节见 HISTORY 的 09-29 一节。6 个 commit，**未 push**。
- **实机验证已过**：
  - 预设槽：`[车头] 预设槽 1 已确认（模板点击，第 1 轮）`——真机真弹窗一次点击确认，没走几何兜底、没抛异常（20:31:40）。
  - 排序条：战争列表帧上预览画出 `排序选择器 0.04 ◇像素`，框套在「最新发起」上，YOLO 那类的输出被正确滤掉。
- **当前阻塞（挡住干净闭环，非本次改动引入）**：`queue_flag_icon` 在队列栏上**稳定读 0.758 < 阈值 0.8**（连抓 6 帧方差 0；位置对、其它队列模板全 ≤0.45）→ `_queue_verdict` 落到 `unknown`。
  **因果链（09-29 20:40~20:46 实机）**：unknown 是 fail-closed「按在外处理」→ 门槛拦住搜索并等 900s 宽限 → 宽限到点告警放行 → 车头此时部队其实在外，**开集结被游戏静默拒绝** → `rally_rejected` 计入连续失败 → mumu0 连吃 2 次（2/3，再 1 次整轮停机）。
  注意方向性：蓝旗语义是「驻扎/集结等待」=**阻塞**态。**读对了反而会拦住这次注定被拒的开车**。所以 0.758 漏检不是「多等一会」，是**把安全的拦截变成了有害的放行**。
  **修法**：优先重采模板（HSV 纯圆重裁 + 重测正负样本）；若负样本仍 ≤0.5，把该模板阈值降到 ~0.65 也是低风险方向（假阳的代价只是多等 15 分钟，假阴的代价是整轮停机）。
- **驱动在跑**：`_driver.log`（写本文件时 mumu0 已 rounds=2，mumu1 宽限放行后正在搜寨）。
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

### 验收剩余项
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
