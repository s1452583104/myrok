from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class BoundingBox:
    """边界框"""
    x1: int
    y1: int
    x2: int
    y2: int
    
    @property
    def width(self) -> int:
        return self.x2 - self.x1
    
    @property
    def height(self) -> int:
        return self.y2 - self.y1
    
    @property
    def center(self) -> Tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)


@dataclass
class DetectionElement:
    """检测元素"""
    class_name: str
    class_id: int
    confidence: float
    bbox: BoundingBox
    center: Tuple[int, int]


@dataclass
class DetectionResult:
    """检测结果"""
    elements: List[DetectionElement]
    image_width: int
    image_height: int
    timestamp: float
    
    def get_elements_by_class(self, class_name: str) -> List[DetectionElement]:
        """根据类别获取元素"""
        return [elem for elem in self.elements if elem.class_name == class_name]
    
    def get_element_by_class(self, class_name: str) -> Optional[DetectionElement]:
        """获取指定类别的第一个元素"""
        elements = self.get_elements_by_class(class_name)
        return elements[0] if elements else None
    
    def get_element_count(self, class_name: str) -> int:
        """获取指定类别的元素数量"""
        return len(self.get_elements_by_class(class_name))