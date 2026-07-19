import cv2
from pathlib import Path
from rok_assistant.core.recognizers.template_match import TemplateMatch

FIX = Path(__file__).parent.parent.parent.parent / "fixtures"

def test_match_finds_template():
    tpl = cv2.imread(str(FIX / "template_search.png"))
    img = cv2.imread(str(FIX / "screenshot_with_template.png"))
    r = TemplateMatch(template=tpl, threshold=0.9).recognize(img)
    assert r.matched
    assert r.bbox is not None
    assert abs(r.bbox.x1 - 40) < 2

def test_match_finds_nothing():
    tpl = cv2.imread(str(FIX / "template_search.png"))
    img = cv2.imread(str(FIX / "screenshot_without_template.png"))
    r = TemplateMatch(template=tpl, threshold=0.95).recognize(img)
    assert not r.matched

def test_match_with_roi():
    tpl = cv2.imread(str(FIX / "template_search.png"))
    img = cv2.imread(str(FIX / "screenshot_with_template.png"))
    from rok_assistant.core.recognizer import BBox
    roi = BBox(0, 0, 80, 80)
    r = TemplateMatch(template=tpl, threshold=0.9, roi=roi).recognize(img)
    assert r.matched
    # bbox coords should be in original (global) image space
    assert abs(r.bbox.x1 - 40) < 2
