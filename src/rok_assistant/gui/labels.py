"""界面文案映射：内部英文值 → 用户看得懂的中文。

收在一处的原因：同一个概念会在多个界面出现（配置对话框的分工下拉、主窗口
角色卡片、校验失败弹窗），散着写必然出现「配置页叫车头、主界面叫 leader」
这种自相矛盾（2026-10-05 用户反馈）。

**全部映射都带原样回落**：内部值新增/改名时界面显示英文原文而不是空白或
KeyError——看不懂总比看不到强，且能直接截图给开发者。
"""
from __future__ import annotations

# ---- 分工 ----
ROLE_LABELS = {"leader": "车头", "member": "成员", "either": "车头或成员"}
LABEL_ROLES = {v: k for k, v in ROLE_LABELS.items()}

# ---- 兵种 ----
TROOP_LABELS = {"infantry": "步兵", "cavalry": "骑兵", "archer": "弓兵"}

# ---- 运行状态 ----
# 键来自两处：WorkerRunner._set_status 的固定值（idle/paused/cooldown/error/
# done）和状态机自己的 current（IDLE / NORMALIZE / WAIT_MEMBERS ...）。
# 同一概念在多处出现（IDLE 与 LEADER:IDLE）就都列上，不做前缀推导——
# 状态名是各状态机自己起的，硬套规则迟早出错。
STATE_LABELS = {
    # 线程级
    "idle": "待机",
    "paused": "已暂停（模拟器窗口不见了）",
    "cooldown": "本轮结束，等待下一轮",
    "error": "出错，重试中",
    "done": "本轮完成",
    # 车头
    "IDLE": "准备中",
    "LEADER:IDLE": "准备中",
    "OPEN_SETTINGS": "打开设置",
    "OPEN_CHAR_MGMT": "打开角色管理",
    "PICK_CHAR": "选择角色",
    "SWITCH_TO_SELF": "切换到本人",
    "VERIFY_UNLOCKED": "确认角色已解锁",
    "WAIT_LOAD": "等待界面加载",
    "NORMALIZE": "回到地图界面",
    "SEARCH_FORTRESS": "搜索城寨",
    "SELECT_LEVEL": "选择城寨等级",
    "CONFIRM_SEARCH": "确认搜索",
    "SELECT_RALLY_TIME": "选择集结时间",
    "LAUNCH": "发起集结",
    "CONFIRM_SWITCH": "确认切换角色",
    "WAIT_MEMBERS": "等待成员填兵",
    "RELOGIN": "重新登录",
    "CLICK_RED_RALLY": "点击红色集结",
    "LEADER:END": "车头任务完成",
    # 成员
    "WAIT_LAUNCH_EVENT": "等待车头发车",
    "OPEN_WAR": "打开战争列表",
    "FIND_JOIN": "寻找可加入的集结",
    "CLICK_JOIN": "点击加入",
    "FORM_TROOP": "创建部队",
    "VERIFY_JOINED": "确认已加入",
    "JOIN_CHECKED": "已加入",
    "CHECK_RESULT": "检查结果",
    "MEMBER:END": "成员任务完成",
    # 车头或成员
    "WAIT_RETURN": "等待部队回城",
    # 通用终态
    "END": "本轮完成",
    "DONE": "本轮完成",
}


def state_label(value: str | None) -> str:
    """运行状态 → 中文；未知状态原样返回（不隐藏信息）。"""
    if not value:
        return ""
    return STATE_LABELS.get(value, value)


def role_label(value: str | None) -> str:
    if not value:
        return ""
    return ROLE_LABELS.get(value, value)


# ---- 校验错误里的字段路径 ----
# pydantic 的 loc 是英文键（instances / 0 / characters / 1 / target_levels），
# 直接摊给用户看等于什么都没说。
LOC_LABELS = {
    "app": "全局设置",
    "instances": "模拟器",
    "characters": "角色",
    "id": "ID",
    "name": "名字",
    "role": "分工",
    "target_levels": "目标城寨等级",
    "march_preset": "行军预设",
    "march_troop_types": "兵种",
    "fill_target_leaders": "填兵目标",
    "mumu_index": "模拟器编号",
    "adb_address": "adb 地址",
    "window_title_pattern": "窗口标题",
    "mumu_manager_path": "MuMuManager 路径",
    "adb_path": "adb 路径",
    "anti_detection": "防检测参数",
    "click_offset_px": "点击偏移",
    "action_delay_min": "动作延迟下限",
    "action_delay_max": "动作延迟上限",
    "state_delay_min": "状态延迟下限",
    "state_delay_max": "状态延迟上限",
    "jitter_ratio": "抖动比例",
    "debug_no_jitter": "调试模式",
    "delay_shape": "延迟分布形状",
    "burst_prob": "连点概率",
    "burst_scale": "连点间隔比例",
    "anchor_sigma": "按目标散布",
    "member_response_delay_min": "成员响应延迟下限",
    "member_response_delay_max": "成员响应延迟上限",
    "screen_height": "截图高度",
    "locale": "界面语言",
    "max_rounds": "最大轮数",
    "max_consecutive_failures": "连续失败上限",
}


def humanize_loc(loc) -> str:
    """把 pydantic 的 loc 元组翻成人话，如 `模拟器 1 / 角色 2 / 目标城寨等级`。

    下标转 1 起（用户数是「第几个」，不是「第零个」）；未知的键原样保留，
    免得新字段一出错就显示空白。
    """
    parts = []
    for seg in loc:
        if isinstance(seg, int):
            parts.append(f"第{seg + 1}个")
        else:
            parts.append(LOC_LABELS.get(str(seg), str(seg)))
    return " / ".join(parts)
