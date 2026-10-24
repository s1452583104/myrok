"""宝石模式 manifest 条目：文件在、ROI 合法**且放得下模板**、能装配。

## 为什么单列一条「模板放得下 ROI」（2026-10-17）

`TemplateMatch.recognize` 先把截图裁到 ROI 再 `cv2.matchTemplate`，而 OpenCV
断言模板必须装得进被搜图：

    cv2.error: (-215:Assertion failed) _img.size().height <= _templ.size().height

这个异常从 `recognize()` 冒到状态机的 action，而 `WorkerRunner` 对 step 异常
**不重建 SM**、原地退避重放，攒满 6 次直接停机（见 CLAUDE.md「状态机」一节）。
所以 ROI 比模板小不是「少认一个模板」，是把一次识别失败升级成整进程停机——
正是项目「绝不抛异常」约束要挡的那类故障。

`test_gem_template_rois_are_in_screen` 只查 ROI 落在 1920x1080 内，**抓不到它**：
brief 的 `collect_dialog` ROI 是 720x480，屏幕内放得下，却装不下 700x520 的模板。

模板尺寸一律从 PNG 现读、不写死：Stage 5 会重裁模板，写死的数字会过期。
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from rok_assistant.core.template_registry import imread_unicode

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "templates" / "manifest.yaml"

# 6 条，**不是 7 条**：`back_from_detail` 在全 11 帧里都不存在（brief 给的
# (1850,530) 实测是个地图资源点标记，不是返回箭头，见 tools/crop_gem_templates.py
# 的 CROPS 尾注），磁盘上没有 PNG。给它写 manifest 条目会让 `build_recognizers`
# 在 template_registry.py:142 抛 FileNotFoundError——那是**装配期**异常，会让
# 每一个识别器都装不出来，不只是这一条。控制器裁定：留到 Stage 0 真机探针。
GEM_TEMPLATE_IDS = ("gem_icon", "gem_mine_zoom", "view_radial_menu",
                    "view_btn_resource", "collect_dialog", "collect_btn")


@pytest.fixture(scope="module")
def raw():
    import yaml
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_gem_template_entries_exist(raw):
    ids = {e["id"] for e in raw["templates"]}
    missing = [t for t in GEM_TEMPLATE_IDS if t not in ids]
    assert not missing, f"manifest 缺条目：{missing}"


def test_gem_template_files_exist(raw):
    by_id = {e["id"]: e for e in raw["templates"]}
    for tid in GEM_TEMPLATE_IDS:
        f = MANIFEST.parent / by_id[tid]["file"]
        assert f.is_file(), f"{tid} 的模板文件不存在：{f}"


def test_gem_template_rois_are_in_screen(raw):
    by_id = {e["id"]: e for e in raw["templates"]}
    for tid in GEM_TEMPLATE_IDS:
        roi = by_id[tid].get("roi", "full")
        if roi in (None, "full"):
            continue
        x1, y1, x2, y2 = roi
        assert 0 <= x1 < x2 <= 1920, f"{tid} ROI x 越界：{roi}"
        assert 0 <= y1 < y2 <= 1080, f"{tid} ROI y 越界：{roi}"


def test_gem_template_fits_inside_its_roi(raw):
    """模板必须能整个落进 ROI——否则 `cv2.matchTemplate` 断言失败 → 停机。

    尺寸现读 PNG（不写死）：Stage 5 重裁后这条自动跟着变。
    """
    by_id = {e["id"]: e for e in raw["templates"]}
    for tid in GEM_TEMPLATE_IDS:
        entry = by_id[tid]
        tpl = imread_unicode(MANIFEST.parent / entry["file"])
        assert tpl is not None, f"{tid} 的模板读不出来：{entry['file']}"
        th, tw = tpl.shape[:2]
        x1, y1, x2, y2 = entry["roi"]
        assert x2 - x1 >= tw and y2 - y1 >= th, (
            f"{tid} 的 ROI {x2 - x1}x{y2 - y1} 装不下模板 {tw}x{th}："
            f"cv2.matchTemplate 会断言失败并抛 cv2.error，"
            f"runner 攒满 6 次异常就停机（不是「少认一个」）")


def test_gem_dialog_title_text_field_exists(raw):
    ids = {e["id"] for e in (raw.get("text_fields") or [])}
    assert "gem_dialog_title" in ids


def test_gem_dialog_title_pattern_has_exactly_one_capture_group(raw):
    """`TextFieldRecognizer` 取 `m.group(1)` 当 value——没捕获组就 IndexError。

    无捕获组的 pattern 一旦真的匹配上，`m.group(1)` 抛 IndexError，与 ROI 越界
    同类：异常冒到 action → runner 退避重放 → 6 次停机。
    """
    entry = next(e for e in raw["text_fields"] if e["id"] == "gem_dialog_title")
    n = re.compile(entry["pattern"]).groups
    assert n == 1, (
        f"gem_dialog_title 的 pattern {entry['pattern']!r} 有 {n} 个捕获组，"
        f"必须是 1 个（TextFieldRecognizer 用它当 value）")


def test_gem_dialog_title_pattern_matches_the_ocr_title_block(raw):
    """pattern 要能整块匹配 OCR 在真帧上读出的标题块。

    `TextFieldRecognizer` 是 `pattern.fullmatch(块)`，**不是子串查找**——写成
    子串式的 `宝石` 会对不上 OCR 的整块「宝石矿床」，判据永远 miss（双确认的
    第二腿失效，采集框出来也会被当成别的资源关掉）。这里用桩引擎喂 142743
    采集框 ROI 上实测到的块（`等级3` + `宝石矿床`），不拉 OCR 模型。
    """
    from rok_assistant.core.recognizer import BBox
    from rok_assistant.core.recognizers.text_field import TextFieldRecognizer

    entry = next(e for e in raw["text_fields"] if e["id"] == "gem_dialog_title")

    class _StubEngine:
        def detect_text(self, img):
            return [(BBox(0, 1, 60, 40), "等级3", 0.749),
                    (BBox(60, 1, 294, 40), "宝石矿床", 0.785)]

    rec = TextFieldRecognizer("gem_dialog_title", BBox(*entry["roi"]),
                              entry["pattern"], engine=_StubEngine())
    r = rec.recognize(np.zeros((1080, 1920, 3), dtype=np.uint8))
    assert r.matched, (
        f"pattern {entry['pattern']!r} 匹配不上 OCR 读出的标题块「宝石矿床」")
    assert r.data["value"]


def test_gem_recognizers_build_without_yolo():
    """没配 YOLO 时也要能装配（纯模板部署）。

    注意：装配**不运行**识别器，所以这条抓不到「ROI 装不下模板」——
    那要靠 `test_gem_template_fits_inside_its_roi`。
    """
    from rok_assistant.core.template_registry import TemplateRegistry
    reg = TemplateRegistry.load(MANIFEST)
    recs = reg.build_recognizers(yolo_model=None, ocr_fallback=False)
    for tid in GEM_TEMPLATE_IDS:
        assert tid in recs, f"{tid} 没装配出识别器"
