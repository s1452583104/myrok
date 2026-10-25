"""答题入口的「活动」卷轴图标（`activity_icon`）：文件在、ROI 放得下模板、能装配。

## 为什么要单列一条

1. **模板必须整个落进 ROI**（理由同 `test_gem_manifest.py`）：
   `TemplateMatch.recognize` 先裁 ROI 再 `cv2.matchTemplate`，ROI 比模板小
   会抛 `cv2.error`；而 runner 对 step 异常不重建 SM、原地重放，6 次就停机——
   一次识别失败被升级成整进程停机（见 CLAUDE.md「状态机」）。
2. **模板不许带红角标**：那是未读活动数（11/12/13 会变），带上它分数会随
   数字漂、掉到和负样本拉不开。角标在图标右上角，所以模板右边界必须
   明显早于角标区（实测图标 x1685-1755，角标 x1738 起）。
3. 模板会随主题/分辨率重裁，尺寸一律现读 PNG，不写死。

坐标与分数实测见 `templates/manifest.yaml` 里 `activity_icon` 上方的注释。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rok_assistant.core.template_registry import imread_unicode

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "templates" / "manifest.yaml"


@pytest.fixture(scope="module")
def entry():
    import yaml
    raw = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in raw["templates"]}
    assert "activity_icon" in by_id, "manifest 缺 activity_icon 条目"
    return by_id["activity_icon"]


def test_activity_icon_file_exists(entry):
    f = MANIFEST.parent / entry["file"]
    assert f.is_file(), f"模板文件不存在：{f}"


def test_activity_icon_roi_is_in_screen(entry):
    x1, y1, x2, y2 = entry["roi"]
    assert 0 <= x1 < x2 <= 1920 and 0 <= y1 < y2 <= 1080, entry["roi"]


def test_activity_icon_template_fits_inside_its_roi(entry):
    tpl = imread_unicode(MANIFEST.parent / entry["file"])
    assert tpl is not None, f"模板读不出来：{entry['file']}"
    th, tw = tpl.shape[:2]
    x1, y1, x2, y2 = entry["roi"]
    assert x2 - x1 >= tw and y2 - y1 >= th, (
        f"ROI {x2 - x1}x{y2 - y1} 装不下模板 {tw}x{th}：cv2.matchTemplate 会断言失败")


def test_activity_icon_template_is_cropped_left_of_the_red_badge(entry):
    """模板右边界要在红角标左边（角标随未读数变，带上就漂）。"""
    tpl = imread_unicode(MANIFEST.parent / entry["file"])
    th, tw = tpl.shape[:2]
    # 实测：图标左沿 x1685，红角标从 x1738 起 → 模板右边界 ≤1740 才不含角标
    assert entry["roi"][0] <= 1686, entry["roi"]
    assert tw <= 54, f"模板宽了（{tw}px）：右边界盖到红角标区"


def test_activity_icon_builds_without_a_yolo_leg(entry):
    """这个类不在 YOLO 模型里，装配后应当只有模板一条腿。"""
    from rok_assistant.core.template_registry import TemplateRegistry

    recs = TemplateRegistry.load(MANIFEST).build_recognizers()
    rec = recs["activity_icon"]
    assert rec.__class__.__name__ == "TemplateMatch", rec.__class__.__name__
