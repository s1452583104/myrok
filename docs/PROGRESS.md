# 实施进度与待办（截至 2026-09-13 晚）

> 配套文档：`docs/ACCEPTANCE.md`（验收手册）、`docs/superpowers/specs/2026-07-15-rok-assistant-design.md`（设计）
> 本文档记录目标闭环验收的实现状态，接续上次更新。

## 目标（/goal，2026-09-11 设定）

> 通过辅助工具程序控制两个模拟器账号能正常的完成集结寨子、向配置中的车头填兵。
> 检测集结车头是否回城，回城后继续开寨子。循环往复直至体力耗尽或者完成一定的
> 次数（先默认十次）。

- 配置：mumu0「阑珊寨子号」(either, 7级) ⇄ mumu1「Jy丶阑珊」(either, 8级) 互相填兵，骑兵、预设槽 1
- 运行方式：无头驱动 `_run_goal.py`（`nohup .venv/Scripts/python.exe -X utf8 _run_goal.py > _driver.log 2>&1 &`），banner `max_rounds=10 max_consecutive_failures=3`

## 已实现（全部提交在 main，最新 f891eef，212 测试绿）

### 核心闭环链路（实机验证过）
| 环节 | 实现 | 实机证据 |
|---|---|---|
| 车头开集结 | 归一化→搜寨→设等级（缓存差量）→搜索→详情→红集结→集结弹窗→蓝集结→预设1+骑兵→行军 | 多轮成功（22:08、22:17、23:21 等） |
| 成员填兵 | 点「+」→ **「创建部队」蓝色气泡按钮 (1515,212)** → 表单 → 行军（默认兵队，不点预设/兵种） | 01:12 端到端实锤（09-12） |
| 按名字填指定车头 | `fill_<车头名>` 名字模板匹配目标行，固定几何 x=1335 点「+」，他人集结一律不填 | §3.7 已过 |
| 等待返城 | member END 后轮询派遣队列徽标（30s 间隔 / 25min 上限） | 22:15 完整闭环一次 |
| 下一轮循环 | 回城→终态→runner 冷却 30s→重建 SM→下一轮 | mumu0 rounds=1→2（09-13） |
| 停止条件 | 跑满 10 轮 / 连续 3 轮失败（疑似体力耗尽）/ 6 连 step 异常断路器 | 设计内路径 |

### 2026-09-12/13 修复清单（全部来自实机发现）
| 问题 | 修复 | commit |
|---|---|---|
| 点「+」后表单出不来 | `join_create_btn` 模板：先点派遣队列侧栏的「创建部队」气泡 | 6c51c35 |
| queue_panel 阈值 0.9 漏检（0.893 卡死帧） | 阈值降到 0.8 | — |
| 连续 9 搜无结果停机（等级缓存失步） | no_result 清缓存，重试前全量重同步 | a7a8177 |
| 两台同秒误判城寨「锁定」（弹窗慢加载） | 锁定判定 5s→10s | bbd0bcf |
| 成员 50s 轮询窗口 < 集结准备窗（solo 发车） | 10→60 次（~5-6 分钟） | a122c50 |
| 行动力不足弹窗死堵 | `ap_refill` 模板 + 关闭分支；耗尽走 3 轮失败自然停机 | aa52841 |
| WAIT_RETURN 行军后 2s 误判「已回城」 | 先关战争面板再读徽标 + 延迟一拍下结论 | aa52841 |
| 创建部队表单/搜索面板/集结弹窗残留 6 连异常 | 各自 normalize 恢复分支 + 回归测试 | 8579330 |
| **仅采集队在外空等 25 分钟**（用户反馈） | `queue_gather_icon`（绿色锄头）识别，仅采集不阻塞 | fa7fec7 |
| **上轮集结未回城就开下一轮搜寨**（用户要求 09-13） | **战斗队列门槛**：`queue_march_icon`（绿色脚印=行军）/`queue_flag_icon`（蓝色旗帜=驻扎/集结等待）在轮次入口（IDLE/NORMALIZE）拦截等待；无徽标或仅采集在外放行。WAIT_RETURN 同一判据重写 | f891eef |
| 部队已在集结中点「+」弹「部队替换」卡死（mumu0） | 不替换（白回城+多烧行动力），关弹窗走 VERIFY_JOINED 回读橙「替换」；两 SM normalize 加残留分支 | f891eef |

### 阈值参考（manifest.yaml，正/负分数实测）
`queue_gather_icon` 1.000/≤0.366 (0.8) · `queue_march_icon` 1.000/≤0.666 (0.85) · `queue_flag_icon` 1.000,0.996/≤0.473 (0.85) · `replace_popup` 1.000/≤0.277 (0.9) · `join_create_btn`/`ap_refill`/`form_title` 均 1.000 正、≤0.42 负 (0.9)

## 已知问题（v1 接受）

1. **战斗队列图标单匹配限制**：采集+行军混合在外时，单点模板匹配可能漏检行军图标误放行（注释已记录，v2 可做多目标计数）
2. **驱动重启 mid-march 会双集结**：重启后轮次计数清零、SM 重建
3. **adb 断连**：模拟器重启后报「模拟器窗口失联」paused——需 `adb connect 127.0.0.1:16384` / `:16416`，重连后自动恢复（无需重启驱动）
4. mumu1 曾 6 连 normalize 异常停机（09-13 22:48，疑网络延迟风暴，截图坏数据/丢点击），退避机制覆盖但不彻底
5. 体力耗尽无自动用道具功能（未要求；mumu0 曾 77/140，走 3 轮失败停机）
6. leader 冷却重建窗口内 rally 事件会丢；config 路径锚定（GUI 需 repo 根 CWD）；错误截图无限速

## 接下来需要做的

### 验收剩余项
- [ ] **完整闭环观察**：干净地跑一轮「开集结→互填→等回城→下一轮」多圈连续循环（目标 10 轮），确认无停机干预
- [ ] C（§3.5 关模拟器→paused→重开恢复；注意 adb connect）
- [ ] D（§3.4 集结 5 分钟无人填超时→自动下一轮）
- [ ] E（§3.3 锁定城寨→跳过重搜）——09-13 23:42 mumu1 连续 4 次锁定后路径已部分验证
- [ ] 体力耗尽路径实机确认（mumu0 用完行动力跑一次）

### 收尾清理（验收通过后）
- [ ] 删根目录临时文件：`_*.png`（_b*/_f*/_live_*/_m*/_q*/_s*/_war_*/_z*/_icon*/_rp*/_cb*/_chat_*/_city_*/_q1_badge 等全部 `_` 前缀 png）、`_driver.log`
- [ ] 删临时脚本：`_run_goal.py`（或转正为 tools/）、`_capture_driver.py`、`_watch_join.py`、`_recapture_templates.py`、`_name_templates.py`
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

# 杀驱动（bash 内联 PowerShell 会坏，用文件）
powershell -ExecutionPolicy Bypass -File "$(cygpath -w /tmp/kill_driver.ps1)"

# adb 重连（模拟器重启后）
C:/模拟器/MuMuPlayer/nx_main/adb.exe connect 127.0.0.1:16384   # mumu0
C:/模拟器/MuMuPlayer/nx_main/adb.exe connect 127.0.0.1:16416   # mumu1

# 回归测试（期望全部通过，以实际输出为准）
.venv/Scripts/python.exe -m pytest tests/ -q

# 监控日志
grep -E "发起|填兵|锁定|已回城|集结门槛|失败结束|异常" _driver.log | tail
```
