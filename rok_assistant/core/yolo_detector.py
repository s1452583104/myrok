"""YOLO检测器模块.

提供YOLO目标检测功能.

核心功能:
- 加载/卸载YOLO模型
- 执行目标检测推理
- 解析检测结果
- 支持模型热切换

线程安全: 推理线程安全（YOLO内部处理）
异常: ModelLoadError, InferenceError
"""

import time
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import numpy as np

from infrastructure.exception_handler import InferenceError, ModelLoadError
from infrastructure.logger import get_logger
from models.detection import BoundingBox, DetectionElement, DetectionResult

try:
    from ultralytics import YOLO

    _ULTRALYTICS_AVAILABLE = True
except ImportError:
    _ULTRALYTICS_AVAILABLE = False


class BaseDetector(ABC):
    """检测器抽象基类.

    定义所有检测器必须实现的接口, 支持未来扩展其他检测方式.
    """

    @abstractmethod
    def detect(self, image: np.ndarray) -> DetectionResult:
        """执行目标检测.

        Args:
            image: 输入图像 (BGR格式)

        Returns:
            检测结果
        """
        pass

    @abstractmethod
    def load_model(self, path: str) -> bool:
        """加载检测模型.

        Args:
            path: 模型文件路径

        Returns:
            是否加载成功
        """
        pass

    @abstractmethod
    def unload_model(self) -> None:
        """卸载检测模型."""
        pass


class YOLODetector(BaseDetector):
    """YOLO目标检测模块.

    职责:
    - 加载/卸载YOLO模型
    - 执行目标检测推理
    - 解析检测结果
    - 支持模型热切换

    线程安全: 推理线程安全（YOLO内部处理）
    异常: ModelLoadError, InferenceError

    使用示例:
        detector = YOLODetector(
            model_path="models/rok_detector.pt",
            confidence_threshold=0.5,
        )
        if detector.load_model():
            result = detector.detect(image)
            print(f"Found {result.element_count} elements")
    """

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.5,
        iou_threshold: float = 0.45,
        input_size: int = 640,
        device: str = "cpu",
    ):
        """初始化YOLO检测器.

        Args:
            model_path: 模型文件路径
            confidence_threshold: 置信度阈值
            iou_threshold: NMS IoU阈值
            input_size: 输入图像尺寸
            device: 推理设备 (cpu, cuda, auto)
        """
        self._model_path = model_path
        self._confidence_threshold = confidence_threshold
        self._iou_threshold = iou_threshold
        self._input_size = input_size
        self._device = device
        self._model: Optional[YOLO] = None
        self._class_names: List[str] = []
        self._logger = get_logger(self.__class__.__name__)

    def load_model(self, path: Optional[str] = None) -> bool:
        """加载YOLO模型.

        Args:
            path: 可选的模型路径, 不指定时使用初始化时的路径

        Returns:
            是否加载成功
        """
        if not _ULTRALYTICS_AVAILABLE:
            self._logger.error("ultralytics is not installed")
            return False

        model_path = path or self._model_path

        try:
            import os

            if not os.path.exists(model_path):
                self._logger.error(f"Model file not found: {model_path}")
                raise ModelLoadError(
                    f"Model file not found: {model_path}", model_path=model_path
                )

            self._model = YOLO(model_path)
            self._class_names = list(self._model.names.values())
            self._model_path = model_path
            self._logger.info(
                f"Model loaded: {model_path}, "
                f"classes: {len(self._class_names)}, device: {self._device}"
            )
            return True

        except ModelLoadError:
            raise
        except Exception as e:
            self._logger.error(f"Failed to load model: {e}", exc_info=True)
            return False

    def detect(self, image: np.ndarray) -> DetectionResult:
        """执行目标检测.

        Args:
            image: BGR格式输入图像

        Returns:
            检测结果

        Raises:
            InferenceError: 推理失败
        """
        if self._model is None:
            raise InferenceError("Model not loaded")

        if image is None or image.size == 0:
            raise InferenceError("Empty input image")

        try:
            results = self._model(
                image,
                conf=self._confidence_threshold,
                iou=self._iou_threshold,
                imgsz=self._input_size,
                device=self._device,
                verbose=False,
            )

            return self._parse_results(results[0], image.shape)

        except InferenceError:
            raise
        except Exception as e:
            self._logger.error(f"Inference failed: {e}", exc_info=True)
            raise InferenceError(f"Inference failed: {e}") from e

    def detect_elements(
        self, image: np.ndarray, class_names: Optional[List[str]] = None
    ) -> List[DetectionElement]:
        """执行检测并过滤指定类别的元素.

        Args:
            image: BGR格式输入图像
            class_names: 要过滤的类别名称列表, None表示全部返回

        Returns:
            过滤后的检测元素列表
        """
        result = self.detect(image)
        if class_names is None:
            return result.elements

        filtered = []
        for name in class_names:
            filtered.extend(result.filter_by_class(name))
        return filtered

    def get_element_positions(
        self, image: np.ndarray, class_name: str
    ) -> List[Tuple[int, int]]:
        """获取指定类别元素的中心位置.

        Args:
            image: BGR格式输入图像
            class_name: 类别名称

        Returns:
            中心点坐标列表 [(x, y), ...]
        """
        result = self.detect(image)
        elements = result.filter_by_class(class_name)
        return [e.center for e in elements]

    def _parse_results(
        self, result, original_shape: Tuple[int, ...]
    ) -> DetectionResult:
        """解析YOLO检测结果.

        Args:
            result: YOLO单张图像的推理结果
            original_shape: 原始图像尺寸 (H, W, C)

        Returns:
            解析后的检测结果
        """
        elements: List[DetectionElement] = []
        boxes = result.boxes

        if boxes is not None and len(boxes) > 0:
            # 计算缩放比例
            orig_h, orig_w = original_shape[:2]
            scale_x = orig_w / self._input_size
            scale_y = orig_h / self._input_size

            for i in range(len(boxes)):
                x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy()
                conf = float(boxes.conf[i].cpu().numpy())
                cls_id = int(boxes.cls[i].cpu().numpy())
                cls_name = self._model.names[cls_id]

                # 坐标缩放回原始图像
                bbox = BoundingBox(
                    x1=int(x1 * scale_x),
                    y1=int(y1 * scale_y),
                    x2=int(x2 * scale_x),
                    y2=int(y2 * scale_y),
                )

                center = (
                    int((x1 + x2) / 2 * scale_x),
                    int((y1 + y2) / 2 * scale_y),
                )

                elements.append(
                    DetectionElement(
                        class_name=cls_name,
                        class_id=cls_id,
                        confidence=conf,
                        bbox=bbox,
                        center=center,
                    )
                )

        return DetectionResult(
            elements=elements,
            image_width=orig_w,
            image_height=orig_h,
            timestamp=time.time(),
        )

    def unload_model(self) -> None:
        """卸载YOLO模型."""
        self._model = None
        self._class_names = []
        self._logger.info("Model unloaded")

    def switch_model(self, new_model_path: str) -> bool:
        """运行时切换模型.

        Args:
            new_model_path: 新模型路径

        Returns:
            切换是否成功
        """
        self.unload_model()
        self._model_path = new_model_path
        return self.load_model()

    @property
    def is_loaded(self) -> bool:
        """模型是否已加载."""
        return self._model is not None

    @property
    def class_names(self) -> List[str]:
        """模型类别名称列表."""
        return list(self._class_names)
