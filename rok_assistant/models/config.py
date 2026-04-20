"""配置数据模型模块.

定义系统中使用的所有配置数据结构.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class WindowConfig:
    """窗口配置.

    Attributes:
        title: 窗口标题关键词（模糊匹配）
        process_name: 进程名称
    """

    title: str = "万国觉醒"
    process_name: str = "RiseofKingdoms.exe"


@dataclass
class ModelConfig:
    """检测模型配置.

    Attributes:
        path: 模型文件路径
        confidence: 置信度阈值
        input_size: 输入图像尺寸
        iou_threshold: NMS IoU阈值
        device: 推理设备 (cpu, cuda, auto)
    """

    path: str = "models/current/rok_detector.pt"
    confidence: float = 0.6
    input_size: int = 640
    iou_threshold: float = 0.45
    device: str = "cpu"


@dataclass
class SafetyConfig:
    """安全操作配置.

    Attributes:
        min_delay: 操作最小间隔(秒)
        max_delay: 操作最大间隔(秒)
        random_offset: 点击随机偏移(像素)
        click_duration: 点击持续时间(秒)
        max_actions_per_minute: 每分钟最大操作数
    """

    min_delay: float = 0.05
    max_delay: float = 0.3
    random_offset: int = 5
    click_duration: float = 0.1
    max_actions_per_minute: int = 30


@dataclass
class GemCollectConfig:
    """宝石采集配置.

    Attributes:
        enabled: 是否启用
        min_level: 最低采集等级
        collect_radius: 采集距离判断
        army_count: 派出军队数量
        army_type: 军队类型 (infantry, archer, cavalry)
        check_interval: 状态检查间隔(秒)
        max_concurrent: 最大同时采集队列数
    """

    enabled: bool = False
    min_level: int = 5
    collect_radius: int = 10
    army_count: int = 1
    army_type: str = "infantry"
    check_interval: int = 300
    max_concurrent: int = 3


@dataclass
class MineCoord:
    """矿点坐标.

    Attributes:
        x: X坐标
        y: Y坐标（如"C9"）
    """

    x: int
    y: str


@dataclass
class TeamConfig:
    """队列配置.

    Attributes:
        team_id: 队列ID
        commander: 主将名称
        secondary_commander: 副将名称
        troop_type: 兵种类型
        troop_count: 出兵数量
    """

    team_id: int
    commander: str
    secondary_commander: str = ""
    troop_type: str = "cavalry"
    troop_count: int = 10000


@dataclass
class RedeployModeConfig:
    """重新派兵模式配置.

    Attributes:
        recall_delay: 采集延迟(秒)
        redeploy_delay: 重新派遣延迟(秒)
    """

    recall_delay: int = 300
    redeploy_delay: int = 5


@dataclass
class GarrisonModeConfig:
    """驻扎模式配置.

    Attributes:
        check_interval: 检查满载间隔(秒)
        full_load_threshold: 满载阈值
    """

    check_interval: int = 600
    full_load_threshold: float = 0.95


@dataclass
class GemCollectionConfig:
    """宝石采集配置（新版）.

    Attributes:
        enabled: 是否启用宝石采集
        mode: 模式: redeploy(重新派兵) / garrison(驻扎)
        mine_coords: 矿点坐标列表
        teams: 队列配置
        redeploy_mode: 重新派兵模式配置
        garrison_mode: 驻扎模式配置
        auto_detect_mine: 自动检测矿点
        mine_detection_radius: 矿点检测半径
    """

    enabled: bool = False
    mode: str = "redeploy"
    mine_coords: List[MineCoord] = field(default_factory=list)
    teams: List[TeamConfig] = field(default_factory=list)
    redeploy_mode: RedeployModeConfig = field(
        default_factory=RedeployModeConfig
    )
    garrison_mode: GarrisonModeConfig = field(
        default_factory=GarrisonModeConfig
    )
    auto_detect_mine: bool = False
    mine_detection_radius: int = 5


@dataclass
class AutoLoginConfig:
    """自动登录配置.

    Attributes:
        enabled: 启用自动登录
        ocr_keywords: OCR识别关键词
        login_button_position: 登录按钮位置
        max_retries: 最大重试次数
        retry_interval: 重试间隔(秒)
    """

    enabled: bool = True
    ocr_keywords: List[str] = field(
        default_factory=lambda: ["登录", "登陆", "开始游戏", "Start Game", "Login"]
    )
    login_button_position: Dict[str, int] = field(
        default_factory=lambda: {"x": 960, "y": 540, "w": 200, "h": 60}
    )
    max_retries: int = 3
    retry_interval: int = 5


@dataclass
class AutoRestartConfig:
    """自动重启配置.

    Attributes:
        enabled: 启用异常重启
        check_interval: 检查间隔(秒)
    """

    enabled: bool = False
    check_interval: int = 30


@dataclass
class GameLauncherConfig:
    """游戏启动配置.

    Attributes:
        game_path: 游戏exe路径
        process_name: 进程名称
        window_title: 窗口标题关键词
        launch_args: 启动参数
        startup_timeout: 启动超时(秒)
        login_check_delay: 登录界面检查延迟(秒)
        auto_login: 自动登录配置
        auto_restart: 自动重启配置
    """

    game_path: str = ""
    process_name: str = "RiseofKingdoms.exe"
    window_title: str = "万国觉醒"
    launch_args: List[str] = field(default_factory=list)
    startup_timeout: int = 60
    login_check_delay: int = 10
    auto_login: AutoLoginConfig = field(default_factory=AutoLoginConfig)
    auto_restart: AutoRestartConfig = field(default_factory=AutoRestartConfig)


@dataclass
class ResourceCollectConfig:
    """资源收集配置.

    Attributes:
        enabled: 是否启用
        interval: 收集间隔(秒)
        max_storage_percent: 存储阈值(%)
    """

    enabled: bool = False
    interval: int = 36000  # 10小时
    max_storage_percent: int = 90


@dataclass
class BuildingUpgradeConfig:
    """建筑升级配置.

    Attributes:
        enabled: 是否启用
        priority: 升级优先级列表
    """

    enabled: bool = False
    priority: List[str] = field(
        default_factory=lambda: ["academy", "barracks", "warehouse"]
    )


@dataclass
class ArmyTrainingConfig:
    """军队训练配置.

    Attributes:
        enabled: 是否启用
        troop_type: 兵种类型
        quantity: 训练数量
    """

    enabled: bool = False
    troop_type: str = "infantry"
    quantity: int = 1000


@dataclass
class AutomationConfig:
    """自动化配置.

    Attributes:
        gem_collection: 宝石采集配置（新版）
        gem_collect: 宝石采集配置（旧版，兼容）
        resource_collect: 资源收集配置
        building_upgrade: 建筑升级配置
        army_training: 军队训练配置
    """

    gem_collection: GemCollectionConfig = field(
        default_factory=GemCollectionConfig
    )
    gem_collect: GemCollectConfig = field(default_factory=GemCollectConfig)
    resource_collect: ResourceCollectConfig = field(
        default_factory=ResourceCollectConfig
    )
    building_upgrade: BuildingUpgradeConfig = field(
        default_factory=BuildingUpgradeConfig
    )
    army_training: ArmyTrainingConfig = field(default_factory=ArmyTrainingConfig)


@dataclass
class InteractionConfig:
    """界面交互配置.

    Attributes:
        detection_fps: 检测帧率
        preview_enabled: 是否显示实时预览
        debug_overlay: 是否显示检测框叠加
    """

    detection_fps: int = 2
    preview_enabled: bool = True
    debug_overlay: bool = True


@dataclass
class LoggingConfig:
    """日志配置.

    Attributes:
        level: 日志级别
        file: 日志文件路径
        max_size: 单个日志文件最大大小(字节)
        backup_count: 保留的旧日志文件数量
    """

    level: str = "INFO"
    file: str = "logs/rok_assistant.log"
    max_size: int = 10485760  # 10MB
    backup_count: int = 5


@dataclass
class PluginConfig:
    """插件配置.

    Attributes:
        enabled: 是否启用插件系统
        search_paths: 插件搜索路径列表
    """

    enabled: bool = True
    search_paths: List[str] = field(default_factory=lambda: ["plugins"])


@dataclass
class AppConfig:
    """应用总配置.

    Attributes:
        window: 窗口配置
        model: 模型配置
        safety: 安全配置
        game_launcher: 游戏启动配置
        automation: 自动化配置
        interaction: 界面交互配置
        logging: 日志配置
        plugins: 插件配置
    """

    window: WindowConfig = field(default_factory=WindowConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    game_launcher: GameLauncherConfig = field(
        default_factory=GameLauncherConfig
    )
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    interaction: InteractionConfig = field(default_factory=InteractionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    plugins: PluginConfig = field(default_factory=PluginConfig)

    @classmethod
    def get_defaults(cls) -> "AppConfig":
        """获取默认配置.

        Returns:
            默认配置对象
        """
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        """从字典创建配置.

        Args:
            data: 配置字典

        Returns:
            配置对象
        """
        automation_data = data.get("automation", {})
        game_launcher_data = data.get("game_launcher", {})
        
        return cls(
            window=WindowConfig(**data.get("window", {})),
            model=ModelConfig(**data.get("model", {})),
            safety=SafetyConfig(**data.get("safety", {})),
            game_launcher=GameLauncherConfig(**game_launcher_data),
            automation=AutomationConfig(
                gem_collection=GemCollectionConfig(
                    **automation_data.get("gem_collection", {})
                ),
                gem_collect=GemCollectConfig(
                    **automation_data.get("gem_collect", {})
                ),
                resource_collect=ResourceCollectConfig(
                    **automation_data.get("resource_collect", {})
                ),
                building_upgrade=BuildingUpgradeConfig(
                    **automation_data.get("building_upgrade", {})
                ),
                army_training=ArmyTrainingConfig(
                    **automation_data.get("army_training", {})
                ),
            ),
            interaction=InteractionConfig(**data.get("interaction", {})),
            logging=LoggingConfig(**data.get("logging", {})),
            plugins=PluginConfig(**data.get("plugins", {})),
        )

    def to_dict(self) -> dict:
        """转换为字典.

        Returns:
            配置字典
        """
        return {
            "window": asdict(self.window),
            "model": asdict(self.model),
            "safety": asdict(self.safety),
            "game_launcher": asdict(self.game_launcher),
            "automation": {
                "gem_collection": asdict(self.automation.gem_collection),
                "gem_collect": asdict(self.automation.gem_collect),
                "resource_collect": asdict(self.automation.resource_collect),
                "building_upgrade": asdict(self.automation.building_upgrade),
                "army_training": asdict(self.automation.army_training),
            },
            "interaction": asdict(self.interaction),
            "logging": asdict(self.logging),
            "plugins": asdict(self.plugins),
        }
