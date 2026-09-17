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

    def build_recognizers(self, yolo_model: Path | None = None,
                          ocr_fallback: bool = True, ocr_engine=None,
                          yolo_shared=None) -> dict:
        """Build {template_id: recognizer} for all loaded templates.

        2026-09-17 三识别栈融合：
        - type=template_match：TemplateMatch（校准阈值，生产主路径）。
          配置 yolo_model 时同一 id 装配 Chain([TemplateMatch, 兜底])——
          模板先行，YOLO 只在模板未命中时兜底（接住动画帧/背景偏移）；
          fill_ 名字类的兜底是 OCR（用户要求：角色名字走 OCR，账号无关）。
        - type=yolo_detect：未配置 yolo_model 时与旧版一致抛 ValueError
          （回归测试锚定）；配置后构建 YoloClassAdapter。
        """
        # local imports: deliberate, keeps module import light (cv2/recognizers
        # are only needed when recognizers are actually built)
        import cv2
        from .recognizers.template_match import TemplateMatch
        from .recognizer import BBox, RecognizerChain

        shared_yolo = yolo_shared
        if shared_yolo is None and yolo_model is not None:
            from .recognizers.yolo_detect import SharedYoloDetector
            shared_yolo = SharedYoloDetector(yolo_model)
        # 类名集合（装配时取一次；顺带强制加载模型，尽早暴露权重问题）
        yolo_class_names = set(shared_yolo.names.values()) \
            if shared_yolo is not None else set()

        out = {}
        for tid, spec in self._t.items():
            roi = None if spec.roi.is_full \
                else BBox(spec.roi.x1, spec.roi.y1, spec.roi.x2, spec.roi.y2)
            if spec.type == "template_match":
                img = cv2.imread(str(spec.file))
                if img is None:
                    raise FileNotFoundError(f"cannot load template image: {spec.file}")
                primary = TemplateMatch(img, threshold=spec.threshold, roi=roi,
                                        name=tid)
                fallback = None
                if shared_yolo is not None:
                    if tid.startswith("fill_"):
                        fallback = self._ocr_fallback_for(
                            tid, roi, ocr_fallback, ocr_engine)
                    elif tid in yolo_class_names:
                        from .recognizers.yolo_detect import YoloClassAdapter
                        fallback = YoloClassAdapter(
                            shared_yolo, class_name=tid, roi=roi,
                            threshold=spec.threshold, name=f"{tid}@yolo")
                    # 类不在模型里（如 queue_recall_icon 被 YOLO 排除训练）：
                    # 模板为主，不挂兜底 —— 挂了运行时 resolve 会 KeyError
                out[tid] = RecognizerChain([primary, fallback], threshold=0.0) \
                    if fallback is not None else primary
            elif spec.type == "yolo_detect":
                if shared_yolo is None:
                    raise ValueError(
                        f"unsupported template type for {tid}: {spec.type}")
                from .recognizers.yolo_detect import YoloClassAdapter
                out[tid] = YoloClassAdapter(
                    shared_yolo,
                    class_id=spec.classes[0] if spec.classes else None,
                    roi=roi, threshold=spec.threshold, name=tid)
            else:
                raise ValueError(f"unsupported template type for {tid}: {spec.type}")
        return out

    @staticmethod
    def _ocr_fallback_for(tid, roi, ocr_fallback, ocr_engine):
        """fill_<名字> 的 OCR 兜底：名字取自 id，账号/配置改动不再失效。"""
        from .recognizers.ocr_text import OCRText, RapidOcrEngine
        if not ocr_fallback:
            return None
        name = tid[len("fill_"):]
        return OCRText(expected_text=name, roi=roi,
                       engine=ocr_engine if ocr_engine is not None
                       else RapidOcrEngine(),
                       name=f"{tid}@ocr")

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
