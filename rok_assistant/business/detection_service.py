import time
from typing import Optional, List
import numpy as np
from core import WindowCapture, YOLODetector, DetectionResult
from infrastructure import get_logger, InferenceError
from .config_manager import ConfigManager


class DetectionService:
    """检测服务"""
    
    def __init__(self, config_manager: ConfigManager):
        """
        Args:
            config_manager: 配置管理器
        """
        self._config_manager = config_manager
        self._window_capture: Optional[WindowCapture] = None
        self._detector: Optional[YOLODetector] = None
        self._last_detection: Optional[DetectionResult] = None
        self._last_detection_time: float = 0
        self._logger = get_logger(self.__class__.__name__)
    
    def initialize(self, window_title: str) -> bool:
        """
        初始化检测服务
        
        Args:
            window_title: 窗口标题
            
        Returns:
            bool: 是否初始化成功
        """
        try:
            # 初始化窗口捕获
            self._window_capture = WindowCapture(window_title)
            if not self._window_capture.find_window():
                self._logger.error("Failed to find window")
                return False
            
            # 初始化YOLO检测器
            model_path = self._config_manager.get('model.path')
            confidence = self._config_manager.get('model.confidence', 0.5)
            iou_threshold = self._config_manager.get('model.iou_threshold', 0.45)
            input_size = self._config_manager.get('model.input_size', 640)
            device = self._config_manager.get('model.device', 'cpu')
            
            self._detector = YOLODetector(
                model_path=model_path,
                confidence_threshold=confidence,
                iou_threshold=iou_threshold,
                input_size=input_size,
                device=device
            )
            
            if not self._detector.load_model():
                self._logger.error("Failed to load model")
                return False
            
            self._logger.info("Detection service initialized successfully")
            return True
        except Exception as e:
            self._logger.error(f"Failed to initialize detection service: {e}")
            return False
    
    def detect(self) -> Optional[DetectionResult]:
        """
        执行检测
        
        Returns:
            Optional[DetectionResult]: 检测结果
        """
        try:
            # 捕获窗口画面
            image = self._window_capture.capture_background()
            if image is None:
                self._logger.error("Failed to capture image")
                return None
            
            # 执行检测
            result = self._detector.detect(image)
            self._last_detection = result
            self._last_detection_time = time.time()
            
            self._logger.debug(f"Detection completed, found {len(result.elements)} elements")
            return result
        except InferenceError as e:
            self._logger.error(f"Inference error: {e}")
            return None
        except Exception as e:
            self._logger.error(f"Detection failed: {e}")
            return None
    
    def get_last_detection(self) -> Optional[DetectionResult]:
        """
        获取上次检测结果
        
        Returns:
            Optional[DetectionResult]: 上次检测结果
        """
        # 检查检测结果是否过期（超过5秒）
        if self._last_detection and (time.time() - self._last_detection_time) < 5:
            return self._last_detection
        return None
    
    def find_element(self, class_name: str) -> Optional[DetectionResult]:
        """
        查找指定类别的元素
        
        Args:
            class_name: 元素类别名称
            
        Returns:
            Optional[DetectionResult]: 检测结果
        """
        result = self.detect()
        if result:
            elements = result.get_elements_by_class(class_name)
            if elements:
                # 创建只包含指定元素的新结果
                return DetectionResult(
                    elements=elements,
                    image_width=result.image_width,
                    image_height=result.image_height,
                    timestamp=result.timestamp
                )
        return None
    
    def get_element_position(self, class_name: str) -> Optional[tuple]:
        """
        获取指定元素的位置
        
        Args:
            class_name: 元素类别名称
            
        Returns:
            Optional[tuple]: 元素中心坐标
        """
        result = self.find_element(class_name)
        if result and result.elements:
            return result.elements[0].center
        return None
    
    def is_element_visible(self, class_name: str) -> bool:
        """
        检查元素是否可见
        
        Args:
            class_name: 元素类别名称
            
        Returns:
            bool: 是否可见
        """
        result = self.find_element(class_name)
        return bool(result and result.elements)
    
    def get_window_capture(self) -> Optional[WindowCapture]:
        """
        获取窗口捕获实例
        
        Returns:
            Optional[WindowCapture]: 窗口捕获实例
        """
        return self._window_capture
    
    def shutdown(self) -> None:
        """
        关闭检测服务
        """
        if self._detector:
            self._detector.unload_model()
        if self._window_capture:
            self._window_capture.close()
        self._logger.info("Detection service shutdown")