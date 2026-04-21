from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
import time
import numpy as np
from ultralytics import YOLO
from infrastructure import get_logger, ModelLoadError, InferenceError


class BoundingBox:
    """边界框"""
    def __init__(self, x1: int, y1: int, x2: int, y2: int):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
    
    @property
    def width(self) -> int:
        return self.x2 - self.x1
    
    @property
    def height(self) -> int:
        return self.y2 - self.y1
    
    @property
    def center(self) -> Tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)


class DetectionElement:
    """检测元素"""
    def __init__(self, class_name: str, class_id: int, confidence: float, bbox: BoundingBox, center: Tuple[int, int]):
        self.class_name = class_name
        self.class_id = class_id
        self.confidence = confidence
        self.bbox = bbox
        self.center = center


class DetectionResult:
    """检测结果"""
    def __init__(self, elements: List[DetectionElement], image_width: int, image_height: int, timestamp: float):
        self.elements = elements
        self.image_width = image_width
        self.image_height = image_height
        self.timestamp = timestamp
    
    def get_elements_by_class(self, class_name: str) -> List[DetectionElement]:
        """根据类别获取元素"""
        return [elem for elem in self.elements if elem.class_name == class_name]
    
    def get_element_by_class(self, class_name: str) -> Optional[DetectionElement]:
        """获取指定类别的第一个元素"""
        elements = self.get_elements_by_class(class_name)
        return elements[0] if elements else None


class BaseDetector(ABC):
    """检测器抽象基类"""
    @abstractmethod
    def detect(self, image: np.ndarray) -> DetectionResult:
        pass
    
    @abstractmethod
    def load_model(self, path: str) -> bool:
        pass
    
    @abstractmethod
    def unload_model(self) -> None:
        pass


class YOLODetector(BaseDetector):
    """YOLO目标检测模块"""
    
    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.5,
        iou_threshold: float = 0.45,
        input_size: int = 640,
        device: str = "cpu",
    ):
        self._model_path = model_path
        self._confidence_threshold = confidence_threshold
        self._iou_threshold = iou_threshold
        self._input_size = input_size
        self._device = device
        self._model: Optional[YOLO] = None
        self._class_names: List[str] = []
        self._logger = get_logger(self.__class__.__name__)

    def load_model(self) -> bool:
        """
        加载YOLO模型

        Returns:
            bool: 加载是否成功
        """
        try:
            self._model = YOLO(self._model_path)
            self._class_names = list(self._model.names.values())
            self._logger.info(
                f"Model loaded: {self._model_path}, "
                f"classes: {len(self._class_names)}, device: {self._device}"
            )
            return True
        except Exception as e:
            self._logger.error(f"Failed to load model: {e}")
            return False

    def detect(self, image: np.ndarray) -> DetectionResult:
        """
        执行目标检测

        Args:
            image: BGR格式输入图像

        Returns:
            DetectionResult: 检测结果

        Raises:
            InferenceError: 推理失败
        """
        if self._model is None:
            raise InferenceError("Model not loaded")

        try:
            start_time = time.time()
            results = self._model(
                image,
                conf=self._confidence_threshold,
                iou=self._iou_threshold,
                imgsz=self._input_size,
                device=self._device,
                verbose=False,
            )
            inference_time = time.time() - start_time

            result = self._parse_results(results[0], image.shape)
            self._logger.debug(f"Inference time: {inference_time:.3f}s, elements: {len(result.elements)}")
            return result

        except Exception as e:
            raise InferenceError(f"Inference failed: {e}") from e

    def _parse_results(self, result, original_shape: tuple) -> DetectionResult:
        """解析YOLO检测结果"""
        elements = []
        boxes = result.boxes

        if boxes is not None:
            for i in range(len(boxes)):
                x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy()
                conf = float(boxes.conf[i].cpu().numpy())
                cls_id = int(boxes.cls[i].cpu().numpy())
                cls_name = self._model.names[cls_id]

                elements.append(DetectionElement(
                    class_name=cls_name,
                    class_id=cls_id,
                    confidence=conf,
                    bbox=BoundingBox(
                        x1=int(x1),
                        y1=int(y1),
                        x2=int(x2),
                        y2=int(y2),
                    ),
                    center=(
                        int((x1 + x2) / 2),
                        int((y1 + y2) / 2),
                    ),
                ))

        return DetectionResult(
            elements=elements,
            image_width=original_shape[1],
            image_height=original_shape[0],
            timestamp=time.time(),
        )

    def detect_elements(self, class_names: List[str]) -> List[DetectionElement]:
        """检测指定类别的元素"""
        # 这个方法需要结合具体的图像输入，这里作为示例
        return []

    def get_element_positions(self, class_name: str) -> List[Tuple[int, int]]:
        """获取指定类别元素的位置"""
        # 这个方法需要结合具体的图像输入，这里作为示例
        return []

    def unload_model(self) -> None:
        """卸载模型"""
        if self._model:
            del self._model
            self._model = None
            self._logger.info("Model unloaded")

    def switch_model(self, new_model_path: str) -> bool:
        """
        运行时切换模型

        Args:
            new_model_path: 新模型路径

        Returns:
            bool: 切换是否成功
        """
        self.unload_model()
        self._model_path = new_model_path
        return self.load_model()

    @property
    def is_loaded(self) -> bool:
        """模型是否已加载"""
        return self._model is not None

    @property
    def class_names(self) -> List[str]:
        """类别名称列表"""
        return self._class_names