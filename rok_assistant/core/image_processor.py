import cv2
import numpy as np
from typing import Optional, Tuple
from infrastructure import get_logger


class ImageProcessor:
    """图像处理器模块"""
    
    def __init__(self):
        self._logger = get_logger(self.__class__.__name__)
    
    def preprocess(self, image: np.ndarray, target_size: Tuple[int, int] = (640, 640)) -> np.ndarray:
        """
        图像预处理
        
        Args:
            image: 输入图像
            target_size: 目标尺寸
            
        Returns:
            np.ndarray: 预处理后的图像
        """
        try:
            # 调整大小
            resized = cv2.resize(image, target_size)
            # 转换为RGB格式（如果需要）
            if len(resized.shape) == 3 and resized.shape[2] == 3:
                resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            # 归一化
            normalized = resized / 255.0
            return normalized
        except Exception as e:
            self._logger.error(f"Preprocess failed: {e}")
            return image
    
    def postprocess(self, image: np.ndarray, results) -> np.ndarray:
        """
        图像后处理（绘制检测结果）
        
        Args:
            image: 原始图像
            results: 检测结果
            
        Returns:
            np.ndarray: 绘制结果后的图像
        """
        try:
            # 绘制边界框和标签
            for element in results.elements:
                x1, y1, x2, y2 = element.bbox.x1, element.bbox.y1, element.bbox.x2, element.bbox.y2
                # 绘制边界框
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                # 绘制标签
                label = f"{element.class_name}: {element.confidence:.2f}"
                cv2.putText(image, label, (x1, y1 - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            return image
        except Exception as e:
            self._logger.error(f"Postprocess failed: {e}")
            return image
    
    def crop_region(self, image: np.ndarray, x: int, y: int, w: int, h: int) -> Optional[np.ndarray]:
        """
        裁剪图像区域
        
        Args:
            image: 输入图像
            x: 起始x坐标
            y: 起始y坐标
            w: 宽度
            h: 高度
            
        Returns:
            Optional[np.ndarray]: 裁剪后的图像
        """
        try:
            return image[y:y+h, x:x+w]
        except Exception as e:
            self._logger.error(f"Crop region failed: {e}")
            return None
    
    def resize(self, image: np.ndarray, width: int, height: int) -> np.ndarray:
        """
        调整图像大小
        
        Args:
            image: 输入图像
            width: 目标宽度
            height: 目标高度
            
        Returns:
            np.ndarray: 调整大小后的图像
        """
        try:
            return cv2.resize(image, (width, height))
        except Exception as e:
            self._logger.error(f"Resize failed: {e}")
            return image
    
    def convert_to_gray(self, image: np.ndarray) -> np.ndarray:
        """
        转换为灰度图像
        
        Args:
            image: 输入图像
            
        Returns:
            np.ndarray: 灰度图像
        """
        try:
            if len(image.shape) == 3:
                return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            return image
        except Exception as e:
            self._logger.error(f"Convert to gray failed: {e}")
            return image
    
    def apply_blur(self, image: np.ndarray, kernel_size: Tuple[int, int] = (5, 5)) -> np.ndarray:
        """
        应用模糊
        
        Args:
            image: 输入图像
            kernel_size: 核大小
            
        Returns:
            np.ndarray: 模糊后的图像
        """
        try:
            return cv2.GaussianBlur(image, kernel_size, 0)
        except Exception as e:
            self._logger.error(f"Apply blur failed: {e}")
            return image
    
    def threshold(self, image: np.ndarray, thresh: int = 127, maxval: int = 255) -> np.ndarray:
        """
        阈值处理
        
        Args:
            image: 输入图像
            thresh: 阈值
            maxval: 最大值
            
        Returns:
            np.ndarray: 阈值处理后的图像
        """
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image
            _, binary = cv2.threshold(gray, thresh, maxval, cv2.THRESH_BINARY)
            return binary
        except Exception as e:
            self._logger.error(f"Threshold failed: {e}")
            return image