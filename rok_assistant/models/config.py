from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class WindowConfig:
    """窗口配置"""
    title: str
    process_name: str
    game_path: str = ''


@dataclass
class ModelConfig:
    """模型配置"""
    path: str
    confidence: float
    input_size: int
    iou_threshold: float
    device: str


@dataclass
class SafetyConfig:
    """安全配置"""
    min_delay: float
    max_delay: float
    random_offset: int
    click_duration: float
    max_actions_per_minute: int


@dataclass
class GemCollectConfig:
    """宝石采集配置"""
    enabled: bool
    min_level: int
    collect_radius: int
    army_count: int
    army_type: str
    check_interval: int
    max_concurrent: int


@dataclass
class ResourceCollectConfig:
    """资源收集配置"""
    enabled: bool
    interval: int
    max_storage_percent: int


@dataclass
class BuildingUpgradeConfig:
    """建筑升级配置"""
    enabled: bool
    priority: List[str]


@dataclass
class ArmyTrainingConfig:
    """军队训练配置"""
    enabled: bool
    troop_type: str
    quantity: int


@dataclass
class AutomationConfig:
    """自动化配置"""
    gem_collect: GemCollectConfig
    resource_collect: ResourceCollectConfig
    building_upgrade: BuildingUpgradeConfig
    army_training: ArmyTrainingConfig


@dataclass
class InteractionConfig:
    """交互配置"""
    detection_fps: int
    preview_enabled: bool
    debug_overlay: bool


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str
    file: str
    max_size: int
    backup_count: int


@dataclass
class PluginsConfig:
    """插件配置"""
    enabled: bool
    search_paths: List[str]


@dataclass
class Config:
    """配置根类"""
    window: WindowConfig
    model: ModelConfig
    safety: SafetyConfig
    automation: AutomationConfig
    interaction: InteractionConfig
    logging: LoggingConfig
    plugins: PluginsConfig


class ConfigValidator:
    """配置验证器"""
    
    @staticmethod
    def validate(config: Dict) -> bool:
        """验证配置"""
        required_sections = ['window', 'model', 'safety', 'automation']
        
        for section in required_sections:
            if section not in config:
                return False
        
        # 验证窗口配置
        if 'title' not in config.get('window', {}):
            return False
        
        # 验证模型配置
        if 'path' not in config.get('model', {}):
            return False
        
        return True