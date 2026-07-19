from pathlib import Path
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
