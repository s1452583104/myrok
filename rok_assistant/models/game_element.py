from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple


@dataclass
class Resource:
    """资源"""
    type: str  # wood, food, stone, gold
    current: int
    capacity: int
    production: int


@dataclass
class Building:
    """建筑"""
    name: str
    level: int
    upgrade_time: Optional[int] = None  # 升级所需时间（秒）
    is_upgrading: bool = False


@dataclass
class Commander:
    """武将"""
    name: str
    level: int
    stars: int
    skill_levels: List[int]
    equipment: Dict[str, str] = None


@dataclass
class Troop:
    """部队"""
    type: str  # infantry, cavalry, archer, siege
    count: int
    level: int


@dataclass
class GemMine:
    """宝石矿"""
    x: int
    y: int
    level: int
    owner: Optional[str] = None
    is_occupied: bool = False


@dataclass
class GameState:
    """游戏状态"""
    resources: Dict[str, Resource]
    buildings: Dict[str, Building]
    commanders: List[Commander]
    troops: List[Troop]
    current_location: Optional[Tuple[int, int]] = None
    timestamp: float = 0


@dataclass
class GameElement:
    """游戏元素基类"""
    name: str
    position: Tuple[int, int]
    type: str


@dataclass
class ButtonElement(GameElement):
    """按钮元素"""
    action: str
    is_clickable: bool = True


@dataclass
class PanelElement(GameElement):
    """面板元素"""
    size: Tuple[int, int]
    is_visible: bool = True