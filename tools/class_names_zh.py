# -*- coding: utf-8 -*-
"""训练类英文名 → 中文名对照（dataset/dataset.yaml 方案 B，64 类）。

语义来源 templates/manifest.yaml 注释与 src/rok_assistant/workers 用法。
CLASS_ZH 缺项时 zh() 原样返回英文名，新增类漏配不会报错。
"""
from __future__ import annotations

CLASS_ZH: dict[str, str] = {
    # 搜索页
    "search_icon": "搜索图标",
    "alliance_btn": "联盟按钮",
    "level_minus": "等级减号",
    "level_plus": "等级加号",
    "search_btn": "搜索按钮",
    "search_back": "搜索返回键",
    "tab_fortress": "野人城寨页签",
    "toast_no_fortress": "无城寨提示框",
    "barb_search_tab": "野蛮人搜索页签",
    "zhaizi_level_text": "寨子等级文本",
    "troop_check": "部队类型勾选",
    # 集结 / 战争
    "red_rally": "红色集结旗",
    "blue_rally": "蓝色集结旗",
    "rally_attack_popup": "集结进攻弹窗",
    "time_5min": "5分钟倒计时",
    "join_btn": "加入按钮",
    "join_create_btn": "加入/创建部队按钮",
    "war_title": "战争面板标题",
    "sort_selector": "排序选择器",
    "sort_opt_latest": "排序-最新发起",
    "sort_opt_nearest": "排序-距离最近",
    "sort_opt_shortest": "排序-准备倒计时最短",
    # 设置 / 角色
    "settings_btn": "设置按钮",
    "settings_title": "设置面板标题",
    "profile_title": "角色面板标题",
    "char_mgmt_btn": "角色管理按钮",
    "char_mgmt_title": "角色管理标题",
    "char_avatar_lszz": "角色头像-阑珊寨子号",
    "char_avatar_lswk": "角色头像-lswk",
    "switch_confirm_yes": "切换确认-是",
    "click_to_enter": "点击进入",
    # 队列 / 行军
    "march_btn": "行军按钮",
    "queue_panel": "队列栏",
    "queue_badge": "队列徽标",
    "queue_gather_icon": "队列采集图标",
    "queue_march_icon": "队列行军图标",
    "queue_flag_icon": "队列集结旗图标",
    "queue_battle_icon": "队列战斗图标",
    "queue_return_icon": "队列返回图标",
    "queue_fight_icon": "队列交战图标",
    # 编队预设
    "preset_1": "预设编队1",
    "preset_2": "预设编队2",
    "preset_3": "预设编队3",
    "preset_4": "预设编队4",
    "preset_5": "预设编队5",
    "preset_6": "预设编队6",
    "selected_preset_1": "选中预设1",
    "selected_preset_2": "选中预设2",
    "selected_preset_3": "选中预设3",
    "selected_preset_4": "选中预设4",
    "selected_preset_5": "选中预设5",
    "selected_preset_6": "选中预设6",
    # 兵种
    "troop_infantry": "步兵图标",
    "troop_cavalry": "骑兵图标",
    "troop_archer": "弓兵图标",
    "troop_siege": "攻城武器图标",
    # 地图 / 弹窗 / 杂项
    "map_btn": "地图按钮",
    # 地图视图左下角**下面**那个槽位：城市视图显示「地图」图标（= map_btn），
    # 地图视图显示「城堡」。同一个槽位两态，图标完全不同 → 必须分开两类，
    # 混进 map_btn 就是 zhaizi_level_text 那种「同类两种形态」污染。
    "city_btn": "城堡按钮",
    "swap_btn": "替换按钮",
    "ap_refill": "行动力补充入口",
    "form_title": "创建部队弹窗标题",
    "replace_popup": "部队替换确认弹窗",
    "menu_expanded": "菜单展开态",
    "warning_panel": "预警面板标题",
}


def zh(name: str) -> str:
    """英文名 → 中文名；未登记的类原样返回。"""
    return CLASS_ZH.get(name, name)
