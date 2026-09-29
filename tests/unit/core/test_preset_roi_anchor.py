"""preset_1..6 的 ROI/阈值校准锚点（2026-09-24 标定，2026-09-27 更正理由）。

这是全库唯一读**真实** `templates/manifest.yaml` 的测试，因为它锚的不是代码
行为而是一次标定。这六个 44x44 图标只差中间一个小数字，**位置区分不了槽位**：
它们像素级同构，唯一的判别信息是字形。所以六槽共用一条覆盖整列的 ROI + 阈值
高到卡住串位。

> **2026-09-27 更正**：这里原来写的「面板会整体上下移约 80px」是**错的**——那是
> 标注被顶部菱形污染后反推出来的假象（菱形恒亮 frac 0.80，正好在槽 1 上方一个
> 槽距，见 `recognizers/pixel_stat.py`）。逐像素实测 44 帧：槽位钉死在
> `cy 474+82*(N-1)`，`march_btn` cy=925 / `form_title` cy=69 逐字节不变。
> 宽 ROI **有意保留**（它对「槽位固定」同样够用，且不宜在同一次改动里动两个
> 变量），但理由不再是「面板会移动」。运行时点预设的串位防护自 2026-09-29 起
> 还多了一层像素判据确认（`leader_sm._select_preset`）。

数值来自 780 帧实测（推导过程见 manifest 里 preset_1 上方的注释）：

| 量 | 实测 |
|---|---|
| 最优匹配落在正确槽位时的分数 | 最低 0.9935（p1 0.9939） |
| 串到邻槽的最高分数 | 0.9616 |
| 无标注帧上的最高分数（误报上限） | 0.9616 |

旧配置（每槽 100px 窗 + 阈值 0.9）实测：25 条被窗裁掉（面板偏高的帧上模板腿
与 YOLO 兜底腿一起静默失效）、串位全放行。串位不是小事——`leader_sm._form_troop`
是 `self._click(f"preset_{N}")` 直接点匹配位置，点错槽 = 派错兵。

**如果你有意重标定**（游戏改版换了面板位置/美术）：改 manifest 的数值要连这份
文件一起改，并重跑实测脚本重新导出上表的四个数，别只改一边。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rok_assistant.core.template_registry import TemplateRegistry

ROOT = Path(__file__).resolve().parents[3]

# --- 实测锚点（改这两个数之前先读上面的表）--------------------------------
CORRECT_SLOT_FLOOR = 0.9935    # 正确槽位的最低分：阈值不能高过它，否则漏检
CROSS_SLOT_CEILING = 0.9616    # 串到邻槽的最高分：阈值必须高过它，否则点错槽

# ROI 覆盖要求（09-24 视图）：六个槽的 cx 恒为 1656；cy 三簇 390/440/470（槽1）
# … 800/860/890（槽6）。图标 44x44，所以半宽半高 22。
# 这三簇是**保守要求**、不是「面板会移动」的断言（那个说法 09-27 已更正，见模块
# docstring）：ROI 只要装得下这个范围就一定装得下真实槽位 474+82*(N-1)。
# 改这两个常量前先想清楚——放宽会同时放宽 ROI 的下界要求。
PANEL_CX = 1656
SLOT1_CY_RANGE = (390, 470)
SLOT6_CY_RANGE = (800, 890)
HALF = 22

# 编队界面的预设条：同一个控件、另一个界面，cx≈1486。运行时只在创建部队面板
# 点预设（leader_sm._form_troop），所以有意**不**把它圈进 ROI。
FORMATION_CX = 1486

PRESETS = [f"preset_{i}" for i in range(1, 7)]


@pytest.fixture(scope="module")
def specs():
    reg = TemplateRegistry.load(ROOT / "templates" / "manifest.yaml")
    return {tid: reg.get(tid) for tid in PRESETS}


def test_presets_share_one_roi(specs):
    """六槽必须共用同一条 ROI。

    六个图标只差中间那个数字，**位置本身不携带判别信息**，所以不能靠「每个槽
    一个窄窗」来分槽——窄窗切出来的图还得靠字形比，那不如直接让整列共用一条
    ROI、统一交给 minMaxLoc 取最优匹配，再用 0.97 的阈值卡住串到邻槽的解。
    （曾把理由写成「面板会上下移动 ~80px」，2026-09-27 已更正，见模块 docstring。）
    """
    rois = {(s.roi.x1, s.roi.y1, s.roi.x2, s.roi.y2) for s in specs.values()}
    assert len(rois) == 1, f"preset_1..6 的 ROI 不一致：{rois}"


def test_shared_roi_covers_the_panels_whole_travel(specs):
    """ROI 必须装得下每个槽的全部实测位置（模板要完整落在窗内才能匹配）。"""
    roi = specs["preset_1"].roi
    assert roi.x1 <= PANEL_CX - HALF, "ROI 左边界切掉了图标的左侧"
    assert roi.x2 >= PANEL_CX + HALF, "ROI 右边界切掉了图标的右侧"
    assert roi.y1 <= SLOT1_CY_RANGE[0] - HALF, "ROI 上边界裁掉了槽 1 的最高位置"
    assert roi.y2 >= SLOT6_CY_RANGE[1] + HALF, "ROI 下边界裁掉了槽 6 的最低位置"


def test_threshold_clears_the_cross_slot_ceiling(specs):
    """阈值必须卡在「串位上限」与「正确下限」之间。"""
    for tid, s in specs.items():
        assert s.threshold > CROSS_SLOT_CEILING, (
            f"{tid} 阈值 {s.threshold} 低于串位上限 {CROSS_SLOT_CEILING}："
            f"会把邻槽的匹配当成本槽，_form_troop 会点错预设 = 派错兵")
        assert s.threshold < CORRECT_SLOT_FLOOR, (
            f"{tid} 阈值 {s.threshold} 高过正确下限 {CORRECT_SLOT_FLOOR}："
            f"真实帧会被漏检")


def test_roi_excludes_the_formation_screen_strip(specs):
    """有意不覆盖编队界面那条预设条（同一个控件的另一个界面）。

    圈进来的话，编队界面上模板也会命中——虽然运行时不会在那时查询预设，
    但那是在教模型/匹配器一个用不到的位置，而且会让 ROI 白白横跨 170px。
    """
    roi = specs["preset_1"].roi
    assert roi.x1 > FORMATION_CX + HALF, (
        "ROI 左边界已伸到编队界面的预设条上；创建部队面板的预设条在 cx≈1656")


def test_threshold_is_not_the_old_default(specs):
    """0.9 是全局默认阈值，实测在这个类上放行 53 条误报。"""
    for tid, s in specs.items():
        assert s.threshold != 0.9, f"{tid} 退回默认阈值 0.9 会重新放行串位"
