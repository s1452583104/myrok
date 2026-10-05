# -*- coding: utf-8 -*-
"""像素统计判据：YOLO 学不动的**状态**类，改由整帧像素测量判定。

为什么不用 YOLO：`selected_preset_N`（预设槽选中态）与 `preset_N`（未选中）是
**同一图标、同一位置、只有填充亮度不同**。数据集里 `preset_N` 有 57~73 个实例、
`selected_preset_N` 只有 3~17 个，同一像素位置差 13~20 倍 —— 模型永远选多数类
（v9 实测：在标注为 `selected_preset_3` 的槽上给出 `preset_4@0.06`，连类别都错）。
2026-09-27 决定把这两个状态从 YOLO 类里摘出来，改成这里的像素判据。

## 几何是**实测钉死**的，绝不从标注/模板/扫描反推

本游戏 UI 像素级固定：`march_btn` cy=925、`form_title` cy=69、`troop_infantry`
cy=163 在 44 帧上逐字节相同。预设列实测：`cx=1655`，槽 N 中心 `cy = 474+82*(N-1)`，
44 帧全列亮度扫描精确落在这 6 个位置。

> **2026-10-03 实机**：这条基准会过期。同一次集结流程里量到的槽心是
> `432+82*(N-1)`（白框高 42px，槽 1/2 中心 432/514，9 帧一致）——`march_btn`
> 仍是 925、`form_title` 仍是 69，**只有预设列整体上移了 42px**，所以拿
> 面板框当锚点也救不了。结论：基准不能只写死，运行时要能从帧里校准。
> `PresetSlotJudge.calibrate(top)` 提供这个口子，`leader_sm._select_preset`
> 用 `preset_N` 模板命中的位置反推 `top = y_hit - 82*(N-1)`。
> `PRESET_TOP` 仍是默认值与标定锚点（`tests/unit/core/test_pixel_stat.py`
> 断言它等于 474），**不是**运行时唯一真相。

**反过来做的代价**（`tools/relabel_extra_classes.py` 的旧 `plan_preset` 就是这么错的）：
用 `fit_slots` 从**被校验的标注本身**反推列基准，标注错→几何错→自洽地错，闭环。
实测 `top` 在 391~475 间漂移（双峰平均），并且已经把污染写进了数据集。

## 两个实测陷阱（都锚了回归测试）

1. **顶部菱形 `cy≈389`**：恒定亮块（55x54，mean BGR `[231,175,8]`），
   `frac 0.80` —— **比任何真选中槽都亮**，且正好在槽 1 上方**一个槽距**。
   从 y=391 起扫 6 格就会把它当成槽 1。它 44/44 帧都在，是永久构件，不是脏数据。
   `slot_centers()` 从 474 起，**永不取样它**。
2. **第 7 个槽 `cy=966`**：真实存在（实测 6 帧选中它）。所以扫描 `PRESET_SCAN_N=7`，
   让「没有选中态」和「选中的是第 7 槽」在日志里能区分开；但只给 1..6 装识别器
   （`config.yaml` 的 `march_preset` 取值域）。槽 7 缺席时该位置读 0.0~0.06，不会误报。

## 判据与实测余量

`frac = mean(patch.max(axis=2) > 200)`，patch 为槽心 ±22px 的 44x44：
选中槽 **0.72~0.75**，未选中 **0.07~0.09**，**8~10 倍余量**；44 帧 argmax 41/44
（3 帧失手全是**标注本身错**，不是判据错，见 `docs/PROGRESS.md`）。

## fail-closed

`matched=True` 仅在「过闸 **且** 赢家就是自己」时。过不了闸（无选中态 / 面板不在 /
界面不符）一律 `matched=False`。最坏失败是「没点预设」，**永远不会是「点错槽」**。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..recognizer import BBox, RecognizeResult

# --- 预设列几何（实测，见模块 docstring）------------------------------------
PRESET_CX = 1655.0        # 列中心（44 帧零方差）
PRESET_TOP = 474.0        # 槽 1 中心（**默认值**，运行时可按帧自校准，见下）
PRESET_PITCH = 82.0       # 槽距
# 列 ROI 半宽：manifest 里 preset_1..6 的 roi 是 x 1600..1712，中心 1656。
# 自校准只认「落在这条列里」的模板命中（模板命中即槽心，见
# PresetSlotJudge.calibrate）。
PRESET_COL_HALF_X = 56.0
PRESET_HALF = 22          # 取样半径（槽约 44x44）
PRESET_SCAN_N = 7         # 扫 7 格：第 7 槽真实存在（cy=966）
PRESET_CLICKABLE_N = 6    # 但只给 1..6 装识别器（march_preset 取值域）
# 顶部菱形：44/44 帧恒亮、frac 0.80 > 任何选中槽。**绝不能被取样**。
PRESET_DISTRACTOR_CY = 389.0

PRESET_BRIGHT_V = 200     # patch.max(axis=2) > 200 记为「亮」
PRESET_MIN_FRAC = 0.40    # 最高槽必须过的占比（选中 0.72~0.75 / 未选中 0.07~0.09）
PRESET_MIN_RATIO = 3.0    # 且须为次高者的 3 倍（实测间距 8~10x）

# --- 战争列表排序 UI --------------------------------------------------------
# 与 tools/relabel_extra_classes.py 的既有常量同源（该工具已改为从这里 import）。
SORT_SELECTOR = (0.242958, 0.148818, 0.206573, 0.041725)   # cx, cy, w, h（归一化）
SORT_YELLOW_MIN = 0.010   # 条内那行黄字占比（实测：有条 0.0375~0.0623，无条恒 0.0000）
SORT_DARK_ROI = (300, 210, 640, 350)
SORT_DARK_MAX = 90.0      # 展开 ⟺ 这块近黑（实测展开 30~90，收起 118~187）
SORT_OPT_X = (272, 465)
SORT_OPT_H = 45
SORT_OPT_YS = {
    "sort_opt_latest": 223.5,
    "sort_opt_nearest": 277.0,
    "sort_opt_shortest": 331.5,
}
SORT_SELECTOR_PX = (
    int((SORT_SELECTOR[0] - SORT_SELECTOR[2] / 2) * 1920),
    int((SORT_SELECTOR[1] - SORT_SELECTOR[3] / 2) * 1080),
    int((SORT_SELECTOR[0] + SORT_SELECTOR[2] / 2) * 1920),
    int((SORT_SELECTOR[1] + SORT_SELECTOR[3] / 2) * 1080),
)

# 排序激活项**没有**判据：三行的填充/亮度一致，只有文字不同。预览只画条和下拉，
# 不声称哪一行是当前项（见 docs/PROGRESS.md）。


# --- 基础测量 --------------------------------------------------------------

def bright_frac(img: np.ndarray, cx: float, cy: float,
                half: int = PRESET_HALF, v: int = PRESET_BRIGHT_V) -> float:
    """槽心 ±half 的方块里「亮」像素占比。越界/空块返回 0.0（不抛）。"""
    patch = img[int(cy) - half:int(cy) + half, int(cx) - half:int(cx) + half]
    if patch.size == 0:
        return 0.0
    return float((patch.max(axis=2) > v).mean())


def yellow_frac(img: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> float:
    """这块里「黄色」像素的占比——排序条上那行当前排序名是黄的。

    按 BGR 直接判（R、G 都亮且都明显高于 B），不走 cv2.cvtColor：HSV 的 H 是
    角度量，0/180 处绕回，判据读起来比 BGR 绕，而这里只需要一个「是不是黄」。
    """
    patch = img[y1:y2, x1:x2].astype(int)
    if patch.size == 0:
        return 0.0
    b, g, r = patch[..., 0], patch[..., 1], patch[..., 2]
    yellow = (r >= 150) & (g >= 120) & (r - b >= 60) & (g - b >= 40)
    return float(yellow.mean())


def mean_v(img: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> float:
    patch = img[y1:y2, x1:x2]
    return float(patch.max(axis=2).mean()) if patch.size else 0.0


def sort_bar_present(img: np.ndarray) -> bool:
    """这条上有没有排序条。战争详情页那个位置是列表行，没有条。"""
    return yellow_frac(img, *SORT_SELECTOR_PX) >= SORT_YELLOW_MIN


def sort_dropdown_open(img: np.ndarray) -> bool:
    """排序下拉展开没展开——与「有没有条」是两个独立判据。"""
    return mean_v(img, *SORT_DARK_ROI) < SORT_DARK_MAX


# --- 预设选中态 -------------------------------------------------------------

def slot_center(slot: int, top: float = PRESET_TOP) -> tuple[float, float]:
    """槽 N（1 起）的取样中心。`top` 是槽 1 中心。

    默认取实测钉死的 `PRESET_TOP`；运行时可用模板命中位置校准它
    （`PresetSlotJudge.calibrate`，2026-10-03 实机面板整体上移 42px 那次）。
    校准来源是**模板命中**而不是扫描，所以不会落到顶部菱形上。
    """
    return PRESET_CX, top + (slot - 1) * PRESET_PITCH


def slot_centers(n: int = PRESET_SCAN_N,
                 top: float = PRESET_TOP) -> list[tuple[float, float]]:
    return [slot_center(i + 1, top) for i in range(n)]


@dataclass(frozen=True)
class PresetVerdict:
    """整列一次测量的结果。`slot=None` = 这帧没有可信的选中态。"""
    slot: int | None
    fracs: list[float] = field(default_factory=list)
    best: int | None = None          # argmax 下标 0..6
    second: float = 0.0              # 次高占比（过闸判据用）

    @property
    def top_frac(self) -> float:
        return self.fracs[self.best] if self.best is not None else 0.0


def panel_verdict(img: np.ndarray, top: float = PRESET_TOP) -> PresetVerdict:
    """整列扫 7 格，返回选中槽号（1..7）或 None。纯函数，无缓存。"""
    fracs = [bright_frac(img, cx, cy) for cx, cy in slot_centers(top=top)]
    order = sorted(range(len(fracs)), key=lambda i: -fracs[i])
    best, second = order[0], fracs[order[1]]
    if fracs[best] < PRESET_MIN_FRAC or fracs[best] < PRESET_MIN_RATIO * second:
        # 无选中态：所有槽都暗，或有两个亮槽（不该出现）——宁可判「没有」
        return PresetVerdict(slot=None, fracs=fracs, best=None, second=second)
    return PresetVerdict(slot=best + 1, fracs=fracs, best=best, second=second)


class PresetSlotJudge:
    """跨所有 `selected_preset_*` 识别器共享的**单帧缓存**。

    一个状态机每步会对同一帧查多个 id（`_wait_for` 轮询也是每拍一次）。
    没有缓存就每查一次重算 7 个 patch。键与 `SharedYoloDetector` 同构：
    `(id(screenshot), shape)`，并且**持强引用** `_last` —— 否则帧被回收后
    地址可能被复用，`id()` 撞上就是读到上一帧的结论。
    """

    def __init__(self, top: float = PRESET_TOP):
        self._top = float(top)
        self._key = None
        self._val: PresetVerdict | None = None
        self._last: np.ndarray | None = None

    @property
    def top(self) -> float:
        """当前整列基准（槽 1 中心）。"""
        return self._top

    def calibrate(self, top: float) -> None:
        """把整列基准挪到运行时实测位置，并作废本帧缓存。

        2026-10-03 实机：面板整体上移 42px（槽心 474 → 432），写死的基准让
        `selected_preset_*` 永远不 matched，集结卡在创建部队面板。调用方
        （`leader_sm._select_preset`）用 `preset_N` 模板命中的位置反推基准。
        """
        if top == self._top:
            return
        self._top = float(top)
        self._key = None

    def verdict(self, screenshot: np.ndarray) -> PresetVerdict:
        key = (id(screenshot), screenshot.shape, self._top)
        if key == self._key:
            return self._val
        val = panel_verdict(screenshot, self._top)
        self._key, self._val, self._last = key, val, screenshot
        return val


def parse_slot(tid: str) -> int:
    """`selected_preset_3` -> 3。与 `_ocr_fallback_for` 同思路：参数取自 id 本身。"""
    try:
        slot = int(tid.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        raise ValueError(f"cannot parse preset slot from id: {tid!r}") from None
    if not 1 <= slot <= PRESET_CLICKABLE_N:
        raise ValueError(f"preset slot out of range 1..{PRESET_CLICKABLE_N}: {tid!r}")
    return slot


class PixelStatRecognizer:
    """「我这一槽是不是选中的」——按 id 切分的整列判据视图。

    `bbox` **恒定**返回本槽的 44x44 全屏框（即使 `matched=False`）：它是实测
    钉死的正确位置，供 `_click_result` 点击与预览绘制。`matched` 才是判据，
    而 `_find` 只在 `matched=True` 时才把它交给 `_click_result`，所以恒返回
    bbox 不会导致误点。
    """

    def __init__(self, judge: PresetSlotJudge, slot: int, name: str = ""):
        self._judge = judge
        self._slot = slot
        self._name = name or f"selected_preset_{slot}"

    @property
    def slot(self) -> int:
        return self._slot

    def calibrate(self, top: float) -> None:
        """转发给共享 judge——同一列的六个槽共用一份基准，调一次就够。"""
        self._judge.calibrate(top)

    def recognize(self, screenshot: np.ndarray) -> RecognizeResult:
        v = self._judge.verdict(screenshot)
        cx, cy = slot_center(self._slot, self._judge.top)
        bbox = BBox(int(cx) - PRESET_HALF, int(cy) - PRESET_HALF,
                    int(cx) + PRESET_HALF, int(cy) + PRESET_HALF)
        return RecognizeResult(
            matched=v.slot == self._slot,
            bbox=bbox,
            confidence=v.fracs[self._slot - 1],
            data={"slot": v.slot, "second": v.second, "fracs": list(v.fracs)},
            recognizer_id=self._name,
        )


def build_preset_recognizers(ids, judge: PresetSlotJudge | None = None) -> dict:
    """`selected_preset_1..6` -> 识别器。共用**一个** judge（单帧只算一次）。"""
    judge = judge if judge is not None else PresetSlotJudge()
    return {tid: PixelStatRecognizer(judge, parse_slot(tid), tid) for tid in ids}
