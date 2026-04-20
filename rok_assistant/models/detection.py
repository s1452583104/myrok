"""检测结果数据模型模块.

定义检测相关的数据结构:
- BoundingBox: 边界框
- DetectionElement: 单个检测元素
- DetectionResult: 检测结果集合
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class BoundingBox:
    """边界框.

    Attributes:
        x1: 左上角X坐标
        y1: 左上角Y坐标
        x2: 右下角X坐标
        y2: 右下角Y坐标
    """

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def center(self) -> Tuple[int, int]:
        """边界框中心点坐标."""
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    @property
    def width(self) -> int:
        """边界框宽度."""
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        """边界框高度."""
        return self.y2 - self.y1

    def to_dict(self) -> dict:
        """转换为字典.

        Returns:
            边界框字典
        """
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}

    @classmethod
    def from_dict(cls, d: dict) -> "BoundingBox":
        """从字典创建边界框.

        Args:
            d: 包含x1, y1, x2, y2的字典

        Returns:
            BoundingBox实例
        """
        return cls(x1=d["x1"], y1=d["y1"], x2=d["x2"], y2=d["y2"])


@dataclass
class DetectionElement:
    """单个检测到的元素.

    Attributes:
        class_name: 类别名称
        class_id: 类别ID
        confidence: 置信度 (0-1)
        bbox: 边界框
        center: 中心点坐标
    """

    class_name: str
    class_id: int
    confidence: float
    bbox: BoundingBox
    center: Tuple[int, int]

    def is_high_confidence(self, threshold: float = 0.7) -> bool:
        """判断是否为高置信度检测.

        Args:
            threshold: 置信度阈值

        Returns:
            是否高于阈值
        """
        return self.confidence >= threshold

    def to_dict(self) -> dict:
        """转换为字典.

        Returns:
            检测元素字典
        """
        return {
            "class_name": self.class_name,
            "class_id": self.class_id,
            "confidence": self.confidence,
            "bbox": self.bbox.to_dict(),
            "center": {"x": self.center[0], "y": self.center[1]},
        }


@dataclass
class DetectionResult:
    """检测结果.

    Attributes:
        elements: 检测到的元素列表
        image_width: 原始图像宽度
        image_height: 原始图像高度
        timestamp: 检测时间戳
    """

    elements: List[DetectionElement]
    image_width: int
    image_height: int
    timestamp: float

    @property
    def element_count(self) -> int:
        """检测到的元素数量."""
        return len(self.elements)

    def filter_by_class(self, class_name: str) -> List[DetectionElement]:
        """按类别名称过滤元素.

        Args:
            class_name: 类别名称

        Returns:
            匹配的元素列表
        """
        return [e for e in self.elements if e.class_name == class_name]

    def filter_by_confidence(self, min_conf: float) -> List[DetectionElement]:
        """按置信度过滤元素.

        Args:
            min_conf: 最低置信度

        Returns:
            置信度>=min_conf的元素列表
        """
        return [e for e in self.elements if e.confidence >= min_conf]

    def find_nearest(
        self, x: int, y: int, class_name: Optional[str] = None
    ) -> Optional[DetectionElement]:
        """查找距离指定点最近的元素.

        Args:
            x: 参考点X坐标
            y: 参考点Y坐标
            class_name: 可选的类别过滤

        Returns:
            最近的元素, 无匹配时返回None
        """
        candidates = self.elements
        if class_name:
            candidates = [e for e in candidates if e.class_name == class_name]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda e: (e.center[0] - x) ** 2 + (e.center[1] - y) ** 2,
        )

    def to_dict(self) -> dict:
        """转换为字典.

        Returns:
            检测结果字典
        """
        return {
            "elements": [e.to_dict() for e in self.elements],
            "image_width": self.image_width,
            "image_height": self.image_height,
            "timestamp": self.timestamp,
        }


@dataclass
class TaskResult:
    """任务执行结果.

    Attributes:
        task_id: 任务ID
        success: 是否成功
        error: 错误信息
        data: 附加数据
        duration: 执行时长(秒)
    """

    task_id: str
    success: bool
    error: str = ""
    data: dict = None
    duration: float = 0.0

    def __post_init__(self):
        if self.data is None:
            self.data = {}
