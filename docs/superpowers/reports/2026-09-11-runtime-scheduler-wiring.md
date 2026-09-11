# 运行时接线里程碑 · 会话纪要

> 日期：2026-09-11
> 执行方式：Subagent-Driven Development（每 task 独立实现子代理 + spec 合规审查 + 代码质量审查，问题回炉复审）
> 范围：`0b06751..24ddb1f`，共 22 个提交
> 结果：**9/9 任务完成，终审 Approved，190/190 测试全绿**

---

## 1. 里程碑目标

承接配置重构里程碑（2026-09-09，142 测试），本次完成「运行时调度器接线」——让 GUI 的 Start/Stop 真正驱动状态机跑通 真实流程：

1. member_sm **填兵去预设**（用户硬性要求：填兵不点预设槽/兵种图标，用默认部队）
2. §1.5 实测修正落代码（切角色 5 步、视角归一化、toast 处理、锁定恢复等）
3. 调度器/入口接线（WorkerRunner、RuntimeCoordinator、GUI 控制器）

计划文档：`docs/superpowers/plans/2026-09-10-runtime-scheduler-wiring.md`（9 task，含完整代码）

## 2. 交付内容（按 task）

| # | Task | 关键提交 | 说明 |
|---|---|---|---|
| 1 | TemplateRegistry.build_recognizers() | 7746e92, 2c953d7 | manifest → 识别器字典；非 template_match 类型抛 ValueError（避免误导性 FileNotFoundError） |
| 2 | JitteringHandleSource | 9811168, cef531c | 反检测包装：随机延迟 → 坐标抖动 → 内层点击；capture/swipe/is_alive 透传 |
| 3 | StateMachine 基类 helper | 3676cd8, ba2ceef | _find/_click_retry/_wait_for_result 等 6 个 helper；`_rec.get(rec_id)` 未知 id 静默 miss；_wait_click 竞态修复（复用已确认的匹配结果） |
| 4 | member 填兵去预设 | ff29032, 7044aad | 全程不点 preset_*/troop_*；NORMALIZE 视角归一化；FILTER 穷尽（>10 次）终态边**先于**重试边注册（注册顺序即优先级，否则无限循环） |
| 5 | leader_sm 真实流程重写 | 4fe5026, 330761e | 归一化→搜城寨（level_minus×12 到 1 级 + level_plus×(target−1)）→CONFIRM→red_rally 8s 等待→toast 无结果（上限 3）→被锁 tap 空地（上限 5）→preset_{n}+troop_{types}+march_btn→验证点击后**才**发布 rally_launched→WAIT_MEMBERS(330s)→END |
| 6 | switcher_sm 重写 | 29bc3e0, 80c87be | 5 步切换+「角色登入」确认框+完整重登+头像模板校验；动作挂在**进入边**（重试重入会重点头像）；v2 接线，暂无调用方 |
| 7 | WorkerRunner | 801e5b0, 395d5de | 每角色一个守护线程；is_alive→paused、终态→cooldown+重建、否则 step+发布；status_update 变更才发布；异常→imencode 截图+error+退避（Windows 非 ASCII 路径 cv2.imwrite 静默 False，必须 write_bytes） |
| 8 | RuntimeCoordinator + GUI 接线 | 28d9e10, c068d2f, a66649d | 协调器（每实例第 1 个角色一个 runner；rally_launched 路由仅 member 角色、门控 IDLE/WAIT_LAUNCH_EVENT）+ GuiController(QObject 信号跨线程) + MainWindow Start/Stop/卡片 |
| 9 | 端到端测试 + 文档 | 438ef6d, 9e996a1 | E2E：leader 发布→路由→member 填到 END→leader 冷却重建回 IDLE；ACCEPTANCE.md 收尾 |

**终审后补丁**（24ddb1f）：见 §4。

## 3. 审查发现并修复的真实缺陷（按 task）

每个 task 至少一轮修复，审查员抓到的代表性问题：

- **Task 4（Critical）**：FILTER→OPEN_WAR 重试边先注册，war_attempts>10 后无限循环 → 穷尽终态边必须最先注册
- **Task 6**：动作挂在离开边 → 重试重入时跳过头像点击 → 重构为进入边动作；`_pick_char` 丢弃 `_click_retry` 结果造成静默假成功
- **Task 7**：cv2.imwrite 在 Windows 非 ASCII 路径静默返回 False → imencode + Path.write_bytes
- **Task 8（首轮 3 个 Important）**：
  1. 部分启动失败留孤儿 runner，重试双份打同一模拟器 → `_running` 前置 + try/except 回滚
  2. stop() 每 runner 10s 阻塞 Qt 主线程且忽略结果，卡住的 worker 继续点模拟器 → 2s 超时 + `is_alive` 检查告警 + 未终止 runner 保留引用
  3. 「刷新配置」从不重读盘（characters() 只在 config 为 None 时加载）→ `reload_config()` 强制读盘
- **Task 8（复审追加）**：router 订阅泄漏（stop 不退订）→ `_routes` 记录并退订
- **Task 9**：计划代码两个过时点——`is_terminal_once` 已改名 `reached_terminal`（且实为方法）；「轮询等 leader 回 IDLE」窗口仅微秒级（重建后立即 continue→step）→ 改用 status_update 序列 END→cooldown→IDLE + `len(leader_sms)>=2` 单调信号；身份断言 `is leader_sms[-1]` 有微秒竞态 → `is not leader_sms[0]`

**审查方法亮点**：Task 9 spec 审查员做变异测试（删路由/删事件投递→测试确实失败，证明非空转）。

## 4. 终审（跨任务整体审查）

终审判定 Ready，但发现 2 个 Important 恰好同时命中用户真实配置（**两个 either 角色**是唯一同时踩中的阵容）：

| 问题 | 修法（24ddb1f） |
|---|---|
| EitherStateMachine 无 `last_image` 委托 → 失败截图和 GUI 缩略图对 either 角色全哑 | 加 `last_image` 属性委托活动阶段 SM（member 未截图时回退 leader 的帧） |
| either 车头放弃 → step() 抛 RuntimeError 但 is_terminal() 恒 False → runner 永不重建，无限「报错→截图→10s」，磁盘无限增长 | leader 终态且 `last_rally_event is None` → 置 `_failed`，呈现终态 `LEADER:END` → runner 正常冷却重建重试（与纯 leader/member 语义对齐）。成功 run 不会误判：`last_rally_event` 在发布前置位，唯一置 None 的路径就是放弃 |
| ctx["failed"]/fail_reason 无人消费，文档字符串承诺的「调度器检查」不存在 | StateMachine 基类 + either 加 `fail_reason` 属性；status_update payload 附带 fail_reason；修正误导文档 |

**终审确认的结论**：跨组件契约全部对齐（工厂签名、事件 API、模板 id 与 manifest 一一对应）；member_sm 全文零预设点击且 E2E MEMBER_IDS 独立兜底；所有放弃路径均终止；线程模型成立（EventBus 快照迭代+订阅者异常隔离、TemplateMatch 无状态可跨线程共享、Qt 信号正确跨线程排队）。

## 5. 最终状态

- **测试**：190 passed（142 基线 → +48），全套 ~11s
- **HEAD**：24ddb1f（main 分支直接提交，项目惯例）
- **ACCEPTANCE.md**：已更新运行时接线状态行、§3 说明 8 项验收可真实执行、§1.5 六项修正标注已实现/已证实

## 6. 已知 v1 局限（有意延后，勿当 bug 报）

1. member 加入战争列表**第 1 个**集结——可能搜到自己 either 角色开的集结；按名字匹配（§3.7）是下一里程碑
2. 每实例只跑第 1 个角色；switcher 已具备但无调用方（v2）
3. 无 rally_completed 事件——WAIT_MEMBERS 用固定等待（330s）代替
4. leader 冷却重建窗口内的 rally 事件会丢（router 门控已收窄窗口）
5. 持续性点击失败时错误截图循环（~1 PNG/12s）待限速
6. GUI 细节：Start 失败按钮不复位、LogPanel 未接线、卡住 runner 引用随 coordinator 被 GC

## 7. 下一步：实机 8 项验收（需用户）

```bash
python -m rok_assistant.gui.main_window   # → Start
```

- ⚠️ 首次真实跑模板阈值/等待时长大概率要现场微调（预期内）
- `_capture_driver.py`（repo 根，untracked）留着调试，验收完删
- 逐项 checklist 见 `docs/ACCEPTANCE.md` §3（tools/verify.py 可出清单）
