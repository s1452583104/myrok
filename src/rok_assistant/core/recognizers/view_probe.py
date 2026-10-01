from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class View(str, Enum):
    MODAL = "弹窗遮罩"
    TROOP_FORM = "创建部队"
    RALLY_POPUP = "集结弹窗"
    WAR_LIST = "战争列表"
    SEARCH = "搜索面板"
    CITY = "城市"
    MAP = "地图"
    UNKNOWN = "未知"


# 锚点：id 全部取自 templates/manifest.yaml，改这里前先确认 manifest 里存在
VIEW_ANCHORS: dict[View, tuple[str, ...]] = {
    View.MODAL: ("replace_popup", "ap_refill", "warning_panel", "menu_expanded"),
    View.TROOP_FORM: ("form_title", "march_btn"),
    View.RALLY_POPUP: ("rally_attack_popup",),
    View.WAR_LIST: ("war_title",),
    View.SEARCH: ("search_back", "search_btn"),
    View.CITY: ("map_btn",),
    View.MAP: ("search_icon", "alliance_btn"),
}

# 判定优先级：全屏模态在最前（它盖住一切，同时命中时必须判它），
# 地图在最后（它是「什么都没盖住」的兜底，不是默认值）
VIEW_PRIORITY: list[View] = [
    View.MODAL, View.TROOP_FORM, View.RALLY_POPUP,
    View.WAR_LIST, View.SEARCH, View.CITY, View.MAP,
]


@dataclass(frozen=True)
class ViewVerdict:
    view: View
    confidence: float
    hits: tuple[str, ...]        # 命中的锚点 id
    scores: dict[str, float]     # 每个锚点的置信度，供排查


class ViewProbe:
    """一次截屏判定「我现在在哪个视图」。

    为什么需要它：日志里 26 次 step 异常（search_icon 不可见 / 联盟旗帜
    不可见 / march_btn 不可见）都是同一个病——不知道自己在哪，只能靠
    「点一下再看某个模板在不在」盲试，失败信息也就只能说「某模板不可见」。

    注意它**不取代** `_normalize_view` 里既有的残留面板清理清单：那些
    `if self._find(...)` 的坐标与顺序各对应一次实机事故（战争面板淡出、
    创建部队模态、行动力弹窗、快捷菜单、预警面板），是清理清单不是探测
    循环。本探针只做两件事：作为**额外的成功信号**（放大镜模板失配但
    探针确认在地图时不该判失败），以及**失败归因**（说清卡在哪个视图）。

    未配置的锚点识别器直接跳过（真实配置里 replace_popup 等并非总是存在），
    不报错——判据少一个锚点只是弱一点，不该让归一化整个挂掉。
    """

    def __init__(self, recognizers: dict):
        self._rec = recognizers

    def probe(self, img) -> ViewVerdict:
        scores: dict[str, float] = {}
        hits_by_view: dict[View, list[str]] = {}
        conf_by_view: dict[View, float] = {}
        # 先把每个锚点都跑一遍、再按优先级挑视图：scores 要覆盖「每个锚点」
        # 供排查（提前 return 会让低优先级锚点的分数缺失）；且每个识别器
        # 每拍只跑一次——不能每试一个候选视图就把锚点重跑一遍。
        for view in VIEW_PRIORITY:
            hits: list[str] = []
            best_conf = 0.0
            for rid in VIEW_ANCHORS[view]:
                rec = self._rec.get(rid)
                if rec is None:
                    continue
                r = rec.recognize(img)
                conf = float(getattr(r, "confidence", 0.0) or 0.0)
                scores[rid] = conf
                if r.matched:
                    hits.append(rid)
                    best_conf = max(best_conf, conf)
            hits_by_view[view] = hits
            conf_by_view[view] = best_conf
        for view in VIEW_PRIORITY:
            if hits_by_view[view]:
                return ViewVerdict(view, conf_by_view[view],
                                   tuple(hits_by_view[view]), scores)
        return ViewVerdict(View.UNKNOWN, 0.0, (), scores)
