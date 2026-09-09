# 配置重构设计：多实例管理 + 弹性角色 + GUI 可视化配置

> 日期：2026-09-09
> 状态：已与用户逐节确认
> 前置：v1 设计（docs/superpowers/specs/2026-07-15-rok-assistant-design.md）、实机验收进行中（docs/ACCEPTANCE.md）

## 1. 背景与目标

实机验收阶段确认了三个需求：

1. **角色分工可配置**：账号下多个角色，需为每个参与角色指定 车头 / 成员 / 车头或成员（低战力角色不能当车头）。成员**必须显式配置向谁填兵**。
2. **多模拟器实例管理**：一个模拟器实例 = 一个账号；MuMu 实例通过 MuMuManager 自动发现 adb 地址，用户只需填实例号。同实例多账号切换暂不做（后续版本）。
3. **GUI 可视化配置**：面向非编程用户，配置不要求手改 yaml；布局采用「左树右表单」。

非目标（本次不做）：同实例账号切换、状态机实机修正（ACCEPTANCE §1.5 六项）、模板补采、PC 客户端。

## 2. 配置 Schema（`infra/config.py`）

```yaml
app:
  mumu_manager_path: "C:\\模拟器\\MuMuPlayer\\nx_main\\MuMuManager.exe"  # 全局
  adb_path: "C:\\模拟器\\MuMuPlayer\\nx_main\\adb.exe"                   # 全局
  screen_width: 1920            # 其余 app 字段不变
  anti_detection: { ... }       # 不变

instances:                      # 原 accounts 改名；1 实例 = 1 账号 = 1 组角色
  - id: mumu0                   # 内部标识，GUI 自动生成（mumu<index> 去重）
    name: "阑珊号"               # 显示名
    mumu_index: 0               # MuMu 模式：仅填实例号，adb 地址自动发现
    # adb_address: "127.0.0.1:16384"   # 手动模式：mumu_index 为空时必填（其他模拟器备用）
    characters:
      - name: "阑珊寨子号"
        role: leader            # leader | member | either
        target_level: 7
        march_preset: 1
        march_troop_types: [infantry]

      - name: "阑珊挖矿"
        role: member
        target_level: 7
        march_preset: 1
        march_troop_types: [infantry]
        fill_target_leaders:                 # member/either 必填，仅显式列表
          - { instance: mumu0, name: "阑珊寨子号" }
```

### 2.1 模型变更

| 项 | 旧 | 新 |
|---|---|---|
| 顶层键 | `accounts` | `instances`（`InstanceConfig`，原 `AccountConfig`） |
| 实例字段 | `window_title_pattern`（必填）、`adb_address` | `name`（显示名，可空）、`mumu_index`、`adb_address`；`window_title_pattern` 保留为可选（Win32 备用） |
| 全局字段 | — | `app.mumu_manager_path`、`app.adb_path`（从实例级上移） |
| 角色 | `RoleEnum{leader, member}` | 增加 `either` |
| 填兵目标 | `"nearest"` 或列表，默认 nearest | **仅列表**，类型 `list[FillLeader]`；`FillLeader{instance, name}`（原 `account` 字段改名 `instance`） |

### 2.2 校验规则

实例级（InstanceConfig）：
- `mumu_index` 与 `adb_address` 二选一：都空或都填 → 报错
- 实例内角色 `name` 不重复
- 至少 1 个 `role in {leader, either}` 的角色

全局（RootConfig，跨实例交叉校验）：
- 实例 `id` 全局唯一
- `member`/`either` 角色的 `fill_target_leaders` 必填非空；`leader` 角色不允许配置（配了报错）
- 每个填兵目标 `(instance, name)` 必须指向真实存在的角色，且目标角色 `role in {leader, either}`
- 允许跨实例引用（实例 A 的成员填实例 B 车头的集结）

迁移：用户尚未写实际 config.yaml，无旧格式迁移负担；`config.example.yaml` 同步重写。

## 3. MuMu 自动发现（新模块 `infra/mumu.py`）

- `MumuLocator(mumu_manager_path, adb_path, _runner=None)`：
  - `resolve_adb_address(index: int) -> str`：调用 MuMuManager 查询实例 adb 端口，返回 `127.0.0.1:<port>`
  - `is_running(index: int) -> bool`：连接测试用
  - 失败（实例不存在/未启动/输出不可解析）抛出带明确提示的异常
- 具体的 MuMuManager 子命令与输出格式实现时实测确定（本机已知 MuMuManager.exe 位于 `C:\模拟器\MuMuPlayer\nx_main\`）；解析层与命令层隔离，命令输出用 fake runner 单测
- `create_handle_source` 改造：接收实例配置 + 全局 app 配置；`mumu_index` 模式先经 MumuLocator 解析地址再构造 `AdbHandleSource`；`adb_address` 手动模式直接构造；均不可用时回退 Win32（行为与现状一致）
- adb_path 从实例级改为全局级传入

## 4. 运行时：`either` 角色

- Worker 工厂按 role 分派：`leader`→LeaderWorker，`member`→MemberWorker，`either`→EitherWorker（新增）
- **EitherWorker 单次上场流程：搜寨 → 开集结 → 不停留，立即转 MemberWorker 流程去填配置指定的车头集结**。自己的集结由成员填，满员或倒计时结束自动发车，无需 either 角色守候
- 填兵逻辑复用 MemberWorker 现有流程（联盟战争页排序加入），目标列表可跨实例
- 状态机实机修正（切角色 5 步、视角归一化、无结果 toast 等）不在本次范围（ACCEPTANCE §1.5 待办）

## 5. GUI 配置界面（新文件 `gui/config_dialog.py`）

主窗口加「⚙ 配置」按钮 → 配置对话框，左树右表单（布局方案 A）：

**左树**：`全局设置`、每个实例节点（显示 `name`）、`＋ 添加实例`

**右侧 - 全局设置页**：
- MuMuManager 路径、adb 路径（带文件选择器）
- 防检测参数（折叠面板）
- 「检测全部实例」按钮：列出 MuMu 各实例在线状态（填实例号时参考）

**右侧 - 实例页**：
- 实例表单：显示名、MuMu 实例号（数字框）或手动 adb 地址（二选一，切模式）
- 连接状态 ●在线/○离线 + **[测试连接]**：查实例在线 → adb 截一帧显示缩略图，确认连的是这台
- 角色表格：名字 | 分工 | 目标等级 | 预设 | 兵种 | 填兵目标；支持添加/删除，双击进入角色编辑

**角色编辑表单**：
- 名字（文本）、分工（下拉：车头/成员/车头或成员）
- 目标等级（1-10）、预设（1-5）、兵种（三个勾选框，至少一个）
- 填兵目标：双列表选择器；候选 = 所有实例的 leader/either 角色；分工为 member/either 时显示且必选
- 生成唯一 `id`（用户不可见，仅在 yaml 中）

**保存与校验**：
- [保存] → pydantic 校验 → 写 config.yaml；失败时错误定位到具体控件并标红，禁止保存
- 「YAML 源码」页签：只读预览最终生成的 yaml（进阶用户对照）
- 主窗口现有的 YAML 文本编辑器（`gui/config_editor.py`）移除，编辑一律走本对话框，避免两处编辑互相覆盖

## 6. 测试策略

- **schema 单测**：role=either 合法性、fill_target_leaders 交叉引用（存在性/角色类型/跨实例）、mumu_index 与 adb_address 二选一、全局 id 唯一
- **MumuLocator 单测**：fake runner 模拟 MuMuManager 输出（正常/实例不存在/输出畸形）
- **GUI 测试**（Qt offscreen）：表单编辑 → config 对象双向往返；校验错误标红定位；树节点增删
- 存量 91 测试中 config、handle_source factory 相关用例同步更新

## 7. 交付物

1. `infra/config.py`：InstanceConfig / RoleEnum.either / 全局 mumu 字段 / 交叉校验
2. `infra/mumu.py`：MumuLocator
3. `core/handle_source.py`：工厂支持 mumu_index 解析
4. `core` worker 工厂 + EitherWorker（复用现有状态机组合）
5. `gui/config_dialog.py`：左树右表单配置对话框 + 测试连接
6. `config.example.yaml` 重写；`docs/ACCEPTANCE.md` §2 配置示例更新
