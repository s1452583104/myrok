from .window_capture import WindowCapture
from .yolo_detector import (
    BoundingBox,
    DetectionElement,
    DetectionResult,
    BaseDetector,
    YOLODetector
)
from .input_controller import (
    BaseInputController,
    PyAutoGUIInputController,
    BackgroundInputController,
    InputController
)
from .image_processor import ImageProcessor

# 导入任务策略基类
from abc import ABC, abstractmethod
from typing import Any


class BaseTaskStrategy(ABC):
    """任务策略基类"""
    @abstractmethod
    def execute(self, context: Any) -> Any:
        pass

__all__ = [
    'WindowCapture',
    'BoundingBox',
    'DetectionElement',
    'DetectionResult',
    'BaseDetector',
    'YOLODetector',
    'BaseInputController',
    'PyAutoGUIInputController',
    'BackgroundInputController',
    'InputController',
    'ImageProcessor',
    'BaseTaskStrategy'
]