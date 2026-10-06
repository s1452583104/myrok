from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml


def imread_unicode(path: Path) -> np.ndarray | None:
    """读图，且能在非 ASCII 路径下工作。

    Windows 上 `cv2.imread` 遇到中文/日文路径会**静默返回 None**（同样的坑
    在 workers/runner.py 的 cv2.imwrite 那里已经踩过）。用户把绿色包解压到
    `D:\\游戏\\rok-assistant` 之类的目录时，53 张模板会集体加载失败，所以
    统一走 imdecode + np.fromfile。
    """
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)

@dataclass(frozen=True)
class ROI:
    x1: int; y1: int; x2: int; y2: int
    @property
    def is_full(self) -> bool:
        return self.x1 == 0 and self.y1 == 0 and self.x2 == 0 and self.y2 == 0

# YOLO 腿的置信度阈值默认值（2026-10-04 定标：val 65 帧）。
# 换 app.yolo_model 后要重跑 tools/calibrate_yolo_threshold.py 复核。
# 与模板阈值是**两把尺子**：TM_CCOEFF_NORMED 的 0.9 和 YOLO conf 的 0.9 不可比，
# 所以不再共用 spec.threshold。定标结论：46/50 个 id 在「GT 无 + 模板未命中」的
# 帧上假阳性地板 = 0.000，0.5 离地板余量极大；同时接得住模板掉分的帧
# （search_icon 实测 0.845 < 模板阈值 0.9）。个别 id 用 manifest 的
# `yolo_threshold:` 覆盖（preset_* / alliance_btn 关闭、queue_march_icon 抬高）。
DEFAULT_YOLO_THRESHOLD = 0.5

# 战争列表里车头名字所在的一列（1920x1080 实机测量）。配置点名、manifest 里
# 却没有条目的车头，OCR 判据就按这个 ROI 装——见 `_fill_name_roi`。
DEFAULT_FILL_NAME_ROI = ROI(460, 240, 760, 660)


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    file: Path
    threshold: float
    type: str  # "template_match" or "yolo_detect"
    roi: ROI
    classes: list[int]
    yolo_threshold: float | None = None   # None = 用 DEFAULT_YOLO_THRESHOLD

@dataclass(frozen=True)
class PixelStatSpec:
    """像素统计判据条目（manifest 顶层 `pixel_stats:` 小节）。

    与 TemplateSpec 分开是有意的：这些 id 没有模板图，放进 `templates:` 会让
    `entry["file"]` KeyError，或被 auto_label_yolo / ingest_raw_imgs 逐个
    cv2.imread 后注入垃圾框。`kind` 决定装配哪个判据族。
    """
    id: str
    kind: str  # "preset_slot"

class TemplateRegistry:
    def __init__(self, templates: dict[str, TemplateSpec],
                 pixel_stats: list[PixelStatSpec] | None = None):
        self._t = templates
        self._pixel = list(pixel_stats or [])

    def __contains__(self, k: str) -> bool:
        return k in self._t

    def get(self, k: str) -> TemplateSpec:
        return self._t[k]

    def build_recognizers(self, yolo_model: Path | None = None,
                          ocr_fallback: bool = True, ocr_engine=None,
                          yolo_shared=None, fill_names=None) -> dict:
        """Build {template_id: recognizer} for all loaded templates.

        2026-09-17 三识别栈融合，2026-10-04 调整先后：
        - type=template_match：配置 yolo_model 时同一 id 装配 Chain——
          **YOLO 先行**，模板作为第二腿（用户要求：优先用 YOLO 匹配）。
          理由：模板在动画帧/背景偏移上会掉分到阈值以下，而 YOLO 仍检出
          （search_icon 实测模板 0.879 / YOLO 0.845，模板阈值 0.9）。
          两条腿各有自己的阈值：YOLO 用 `yolo_threshold`（缺省
          DEFAULT_YOLO_THRESHOLD），模板用 `spec.threshold`。
          fill_ 例外：兜底腿是 OCR（用户要求角色名字走 OCR，账号无关），
          仍**模板先行**——OCR 慢且受字体影响，不该抢在主判据前面。
        - type=yolo_detect：未配置 yolo_model 时与旧版一致抛 ValueError
          （回归测试锚定）；配置后构建 YoloClassAdapter。

        `fill_names`（2026-10-06）：配置里 `fill_target_leaders` 点名的车头。
        manifest 里没有 `fill_<名字>` 条目时**就地生成 OCR 判据**——车头是
        账号/配置绑定的，不该要求用户改配置的同时还去动随包走的 manifest。
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
        # 名字类判据共用**一个** OCR 后端：RapidOCR 的模型是重资源，每个
        # fill_ id 各建一个会让同一帧被反复推理（单帧缓存挂在后端上，见
        # RapidOcrEngine docstring）。构造本身是懒的，不加载模型。
        if ocr_fallback and ocr_engine is None:
            from .recognizers.ocr_text import RapidOcrEngine
            ocr_engine = RapidOcrEngine()

        out = {}
        for tid, spec in self._t.items():
            roi = None if spec.roi.is_full \
                else BBox(spec.roi.x1, spec.roi.y1, spec.roi.x2, spec.roi.y2)
            if spec.type == "template_match":
                img = imread_unicode(spec.file)
                if img is None:
                    raise FileNotFoundError(f"cannot load template image: {spec.file}")
                primary = TemplateMatch(img, threshold=spec.threshold, roi=roi,
                                        name=tid)
                aux = None            # 第二条腿；排第一还是第二由 yolo_first 决定
                yolo_first = False
                if tid.startswith("fill_"):
                    # 名字类：OCR 兜底，模板仍先行（见 docstring）。
                    # **不受 yolo_model 影响**：YOLO 不训角色名这类账号绑定的
                    # 文本，`ocr_name_fallback` 是独立开关，被「配没配 YOLO」
                    # 二次门控时纯模板模式下会静默失效。
                    aux = self._ocr_fallback_for(tid, roi, ocr_fallback, ocr_engine)
                elif shared_yolo is not None and tid in yolo_class_names:
                    from .recognizers.yolo_detect import YoloClassAdapter
                    yolo_thr = (DEFAULT_YOLO_THRESHOLD
                                if spec.yolo_threshold is None
                                else spec.yolo_threshold)
                    aux = YoloClassAdapter(
                        shared_yolo, class_name=tid, roi=roi,
                        threshold=yolo_thr, name=f"{tid}@yolo")
                    yolo_first = True
                # 类不在模型里（如 queue_recall_icon 被 YOLO 排除训练）：
                # 模板为主，不挂第二条腿 —— 挂了运行时 resolve 会 KeyError
                legs = ([aux, primary] if yolo_first else [primary, aux]) \
                    if aux is not None else None
                out[tid] = RecognizerChain(legs, threshold=0.0) \
                    if legs is not None else primary
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
        out.update(self._build_config_fill_recognizers(
            fill_names, ocr_fallback, ocr_engine))
        out.update(self._build_pixel_recognizers())
        return out

    def _build_config_fill_recognizers(self, fill_names, ocr_fallback,
                                       ocr_engine) -> dict:
        """给配置点名、但 manifest 里没有条目的车头补一条 OCR 判据。

        为什么必须由配置驱动：车头名是账号/配置绑定的，manifest 是随发行包
        走的静态资源。用户改 `fill_target_leaders` 换车头时，manifest 不会
        自动多出 `fill_<名字>` 条目——旧行为是 MemberStateMachine 只打一条
        warning，随后 `_find` 永远返回 None、`_poll_join` 60 次轮询空转到
        `no_rally_found`，改配置等于静默失效。

        名字直接取自配置（`_ocr_fallback_for` 从 id 反推），所以生成的判据
        与账号无关。manifest 里已有的条目优先，不动它们（模板先行）。
        """
        if not ocr_fallback or not fill_names:
            return {}
        from .recognizer import BBox
        roi = self._fill_name_roi()
        bbox = None if roi.is_full else BBox(roi.x1, roi.y1, roi.x2, roi.y2)
        out = {}
        for name in fill_names:
            tid = f"fill_{name}"
            if tid in self._t or tid in out:
                continue
            out[tid] = self._ocr_fallback_for(tid, bbox, True, ocr_engine)
        return out

    def _fill_name_roi(self) -> ROI:
        """战争列表里车头名字所在的一列的 ROI。

        优先沿用 manifest 里任一 `fill_*` 条目的 roi（实测基准，单一真相）；
        一条都没有时退回实测常量。**绝不退回全屏**：全屏 OCR 会把聊天框里
        的同名文本也认成目标行，`_poll_join` 随后按固定几何点到一片空地上。
        """
        for tid, spec in self._t.items():
            if tid.startswith("fill_") and not spec.roi.is_full:
                return spec.roi
        return DEFAULT_FILL_NAME_ROI

    def _build_pixel_recognizers(self) -> dict:
        """装配 manifest 顶层 `pixel_stats:` 小节。

        2026-09-27：`selected_preset_N` 从 YOLO 类改成像素判据——同一图标同一
        位置只有填充亮度不同，`preset_N` 实例数又是它的 13~20 倍，模型永远选
        多数类（v9 实测在槽 3 上给出 `preset_4@0.06`）。判据见
        `recognizers/pixel_stat.py`，那里同时是预览与运行时的常量真相。
        """
        for spec in self._pixel:
            if spec.kind not in ("preset_slot",):
                raise ValueError(
                    f"unsupported pixel_stat kind for {spec.id}: {spec.kind}")
        out: dict = {}
        preset_ids = [s.id for s in self._pixel if s.kind == "preset_slot"]
        if preset_ids:
            # 六个 id 共用**一个** judge：单帧只扫一遍 7 个 patch
            from .recognizers.pixel_stat import build_preset_recognizers
            out.update(build_preset_recognizers(preset_ids))
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
                yolo_threshold=(None if entry.get("yolo_threshold") is None
                                else float(entry["yolo_threshold"])),
            )
            templates[spec.id] = spec
        pixel_stats = [
            PixelStatSpec(id=e["id"], kind=e.get("kind", "preset_slot"))
            for e in (raw.get("pixel_stats") or [])
        ]
        return TemplateRegistry(templates, pixel_stats)
