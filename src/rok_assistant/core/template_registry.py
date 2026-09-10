from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass(frozen=True)
class ROI:
    x1: int; y1: int; x2: int; y2: int
    @property
    def is_full(self) -> bool:
        return self.x1 == 0 and self.y1 == 0 and self.x2 == 0 and self.y2 == 0

@dataclass(frozen=True)
class TemplateSpec:
    id: str
    file: Path
    threshold: float
    type: str  # "template_match" or "yolo_detect"
    roi: ROI
    classes: list[int]

class TemplateRegistry:
    def __init__(self, templates: dict[str, TemplateSpec]):
        self._t = templates

    def __contains__(self, k: str) -> bool:
        return k in self._t

    def get(self, k: str) -> TemplateSpec:
        return self._t[k]

    def build_recognizers(self) -> dict:
        """Build {template_id: TemplateMatch} for all loaded templates."""
        import cv2
        from .recognizers.template_match import TemplateMatch
        from .recognizer import BBox
        out = {}
        for tid, spec in self._t.items():
            img = cv2.imread(str(spec.file))
            if img is None:
                raise FileNotFoundError(f"template image missing: {spec.file}")
            roi = None if spec.roi.is_full else BBox(spec.roi.x1, spec.roi.y1, spec.roi.x2, spec.roi.y2)
            out[tid] = TemplateMatch(img, threshold=spec.threshold, roi=roi, name=tid)
        return out

    @staticmethod
    def load(manifest_path: Path) -> "TemplateRegistry":
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        templates = {}
        for entry in raw.get("templates", []):
            roi_raw = entry.get("roi", "full")
            if roi_raw == "full" or roi_raw is None:
                roi = ROI(0, 0, 0, 0)
            elif isinstance(roi_raw, list) and len(roi_raw) == 4:
                roi = ROI(*roi_raw)
            else:
                raise ValueError(f"Bad ROI in {entry['id']}: {roi_raw}")
            spec = TemplateSpec(
                id=entry["id"],
                file=manifest_path.parent / entry["file"],
                threshold=float(entry.get("threshold", 0.9)),
                type=entry.get("type", "template_match"),
                roi=roi,
                classes=entry.get("classes", []),
            )
            templates[spec.id] = spec
        return TemplateRegistry(templates)
