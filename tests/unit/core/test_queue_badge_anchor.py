"""queue_badge（右侧队列蓝色扩展按钮）的模板锚点：正负分离必须留出余量。

## 这次修的是什么（2026-10-16 实机）

车头点完行军，队列徽标**真的出现了**，但 `leader_sm._launch` 的发射验证
`_wait_for("queue_badge", timeout=10.0)` 十秒没等到 → 判 `rally_rejected`
（日志写作「集结被游戏静默拒绝（同目标已有集结）」），整轮白白作废、计入
连续失败，且 `mark_troops_out` / `mark_rally_launched` 没写进账本。

根因不在状态机，在**模板本身**：`queue_badge.png` 是 46x46 的紧裁剪，按钮体
只占 x 4..44 / y 5..45，四个角是**地图背景**（草/山，实测 BGR
[94,114,50] [74,84,94] [114,106,54] [51,51,30]）。`TM_CCOEFF_NORMED` 是
整窗归一化相关、**没有掩膜**（`recognizers/template_match.py`），于是按钮背后
站什么景物就决定这一帧打多少分——同一块按钮，实测 0.786 / 0.883 / 0.883 /
0.977 随背景摆动，而阈值 0.85 正好卡在摆幅中间：真发了却判没发。

修法与另外几个队列图标同源（manifest 里 `queue_gather_icon` 等的注释
「纯圆重裁（去头像背景角落）」）：模板重裁到按钮体内，去掉背景环。

| 量 | 旧模板 46x46 | 新模板 30x30（内缩 8px） |
|---|---|---|
| 徽标可见帧 | 0.786 / 0.883 / 0.958 | 1.000 / 1.000 / 1.000 |
| 徽标不可见帧（494 张 recordings + 实机帧） | <= 0.358 | <= 0.489 |

阈值 0.85 **有意不动**：去掉背景后它在两边都留了 0.36 的余量，本次只改模板
这一个变量。注意「0.85 也合规」是旧注释的说法——旧注释只量了 4 个点、没量
背景摆幅，正样本能掉到 0.786 这件事它没看见。

## fixture 怎么来的

`tests/fixtures/queue_col_badge_*.png` 是从真实帧裁下的**队列列 ROI**
（manifest 里 queue_badge 的 roi = 1700,150,1920,300 → 220x150，约 40KB/张；
整帧 2MB 不进 git）。测试把它贴回 1920x1080 画布的 ROI 原点再喂识别器——
识别器只读 ROI，与喂整帧等价。裁片脚本：`_probe_mkfix.py`。

**改 ROI 就得重导 fixture**：`test_fixture_is_cut_from_the_manifest_roi` 先拦。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rok_assistant.core.template_registry import TemplateRegistry, imread_unicode

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "tests" / "fixtures"

# 与 manifest 的 queue_badge.roi 逐字一致；改它要重导 fixture（见 docstring）
ROI = (1700, 150, 1920, 300)
FRAME_SHAPE = (1080, 1920, 3)

# --- 实测锚点（改这两个数之前先读模块 docstring 的表）----------------------
POSITIVE_FLOOR = 1.000     # 徽标可见帧的最低分
NEGATIVE_CEILING = 0.489   # 徽标不可见帧的最高分

VISIBLE = ["queue_col_badge_visible_a.png",     # 旧模板 0.786 —— 就是漏检那帧
           "queue_col_badge_visible_b.png",
           "queue_col_badge_visible_c.png"]
ABSENT = ["queue_col_badge_absent_a.png",
          "queue_col_badge_absent_b.png",       # 494 帧里分最高的一帧
          "queue_col_badge_absent_c.png"]


@pytest.fixture(scope="module")
def spec():
    reg = TemplateRegistry.load(ROOT / "templates" / "manifest.yaml")
    return reg.get("queue_badge")


@pytest.fixture(scope="module")
def recognizer():
    """生产装配方式（`build_recognizers`），但不挂 YOLO 腿。

    这里锚的是**模板腿**：链是 [YOLO, 模板]，YOLO 腿阈值 0.5 与本次修复无关，
    而实测漏检那帧两条腿都没中，决定性的就是模板腿。
    """
    reg = TemplateRegistry.load(ROOT / "templates" / "manifest.yaml")
    return reg.build_recognizers(yolo_model=None, ocr_fallback=False)["queue_badge"]


def frame(name: str) -> np.ndarray:
    """把 ROI 裁片贴回整帧画布（识别器按绝对坐标裁 ROI）。"""
    crop = imread_unicode(FIX / name)
    assert crop is not None, f"读不到 fixture：{FIX / name}"
    assert crop.shape == (ROI[3] - ROI[1], ROI[2] - ROI[0], 3), \
        f"{name} 尺寸 {crop.shape} 与 ROI {ROI} 不符——fixture 是照 ROI 裁的"
    img = np.zeros(FRAME_SHAPE, dtype=np.uint8)
    img[ROI[1]:ROI[3], ROI[0]:ROI[2]] = crop
    return img


def test_fixture_is_cut_from_the_manifest_roi(spec):
    """fixture 与 manifest 的 ROI 必须还是同一块地方。

    ROI 一动，裁片贴回画布的位置就错位，后两条用例会在**读不到徽标**的假象下
    报红。这条先失败，失败信息才是「重导 fixture」而不是「模板坏了」。
    """
    assert (spec.roi.x1, spec.roi.y1, spec.roi.x2, spec.roi.y2) == ROI, \
        f"manifest 的 queue_badge.roi 变了：{spec.roi} != {ROI}；" \
        f"请用 _probe_mkfix.py 重导 tests/fixtures/queue_col_badge_*.png"


def test_threshold_sits_between_measured_ceiling_and_floor(spec):
    """阈值必须卡在「不可见上限」与「可见下限」之间。"""
    assert spec.threshold > NEGATIVE_CEILING, (
        f"阈值 {spec.threshold} <= 不可见帧上限 {NEGATIVE_CEILING}："
        f"队列空着也会判成「有队列在外」")
    assert spec.threshold < POSITIVE_FLOOR, (
        f"阈值 {spec.threshold} >= 可见帧下限 {POSITIVE_FLOOR}："
        f"真发出去了也认不到，_launch 会判 rally_rejected（2026-10-16 实机那轮）")


@pytest.mark.parametrize("name", VISIBLE)
def test_badge_is_found_when_the_badge_is_on_screen(recognizer, name):
    """徽标真在屏幕上时必须认到——这是 2026-10-16 那轮漏检的直接复现。"""
    r = recognizer.recognize(frame(name))
    assert r.matched, (
        f"{name} 上徽标可见却未命中（分 {r.confidence:.3f}）："
        f"_launch 的发射验证会误判 rally_rejected，真实发起的集结被当成被拒")


@pytest.mark.parametrize("name", ABSENT)
def test_badge_is_not_found_when_the_badge_is_absent(recognizer, name):
    """徽标不在时必须不认——误报会让集结门槛一直不放行。"""
    r = recognizer.recognize(frame(name))
    assert not r.matched, (
        f"{name} 上没有徽标却命中（分 {r.confidence:.3f}）："
        f"模板里混进了固定景物，或阈值被降到误报区")
