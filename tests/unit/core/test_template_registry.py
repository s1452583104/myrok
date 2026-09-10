from pathlib import Path
import shutil
import cv2
import numpy as np
import pytest
from rok_assistant.core.template_registry import TemplateRegistry, TemplateSpec, ROI

FIX = Path(__file__).parent.parent.parent / "fixtures"

@pytest.fixture
def manifest_with_png(tmp_path):
    # Create stub template files
    (tmp_path / "btn_a.png").write_bytes(b"")
    (tmp_path / "btn_b.png").write_bytes(b"")
    (tmp_path / "card.onnx").write_bytes(b"")
    # Copy manifest
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text((FIX / "manifest_test.yaml").read_text())
    return manifest

def test_load_manifest(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    assert "btn_a" in reg
    assert "btn_b" in reg
    assert "card" in reg

def test_get_template_spec(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    spec = reg.get("btn_a")
    assert isinstance(spec, TemplateSpec)
    assert spec.threshold == 0.9
    assert spec.roi.x1 == 10

def test_roi_full(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    spec = reg.get("btn_b")
    assert spec.roi.is_full

def test_template_spec_type(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    spec = reg.get("card")
    assert spec.type == "yolo_detect"

@pytest.fixture
def image_manifest(tmp_path):
    # Manifest referencing a real (loadable) template image
    shutil.copy(FIX / "template_search.png", tmp_path / "template_search.png")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "templates:\n"
        "  - id: search\n"
        "    file: template_search.png\n"
        "    roi: full\n"
        "    threshold: 0.9\n"
        "  - id: search_roi\n"
        "    file: template_search.png\n"
        "    roi: [0, 0, 80, 80]\n"
        "    threshold: 0.9\n"
    )
    return manifest

def test_build_recognizers_returns_template_matches(image_manifest):
    from rok_assistant.core.recognizers.template_match import TemplateMatch
    reg = TemplateRegistry.load(image_manifest)
    recs = reg.build_recognizers()
    assert set(recs) >= {"search", "search_roi"}
    assert all(isinstance(r, TemplateMatch) for r in recs.values())
    img = cv2.imread(str(FIX / "screenshot_with_template.png"))
    # full-screen ROI -> roi=None in the recognizer
    r = recs["search"].recognize(img)
    assert r.matched
    assert abs(r.bbox.x1 - 40) < 2
    # bounded ROI -> BBox, coords back in global image space
    r2 = recs["search_roi"].recognize(img)
    assert r2.matched
    assert abs(r2.bbox.x1 - 40) < 2

def test_build_recognizers_missing_image_raises(manifest_with_png):
    # btn_a.png is a stub of empty bytes -> cv2.imread returns None
    reg = TemplateRegistry.load(manifest_with_png)
    with pytest.raises(FileNotFoundError):
        reg.build_recognizers()
