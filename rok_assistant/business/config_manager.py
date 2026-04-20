"""配置管理器模块.

提供配置文件的读写、验证和热更新功能.

核心功能:
- YAML配置文件读写
- 配置验证
- 文件监听热更新
- 默认值管理
"""

import os
import threading
import time
from typing import Any, List, Optional

import yaml

from coordination.event_bus import ConfigChangedEvent, EventBus
from infrastructure.exception_handler import ConfigValidationError
from infrastructure.logger import get_logger
from models.config import AppConfig


class ConfigValidator:
    """配置验证器.

    验证配置字典的合法性和合理性.
    """

    REQUIRED_SECTIONS = ["window", "model", "safety", "automation", "logging"]

    VALID_INPUT_SIZES = (320, 416, 512, 640, 768, 1024)

    @classmethod
    def validate(cls, config: dict) -> List[str]:
        """验证配置, 返回错误列表.

        Args:
            config: 原始配置字典

        Returns:
            错误信息列表, 空列表表示验证通过
        """
        errors: List[str] = []

        # 检查必填section
        for section in cls.REQUIRED_SECTIONS:
            if section not in config:
                errors.append(f"Missing required section: {section}")

        # 验证window
        window = config.get("window", {})
        if not window.get("title"):
            errors.append("window.title cannot be empty")

        # 验证model
        model = config.get("model", {})
        conf = model.get("confidence", 0)
        if not (0 < conf <= 1):
            errors.append(f"model.confidence must be in (0, 1], got {conf}")

        input_size = model.get("input_size", 0)
        if input_size not in cls.VALID_INPUT_SIZES:
            errors.append(
                f"model.input_size must be in {cls.VALID_INPUT_SIZES}, got {input_size}"
            )

        device = model.get("device", "cpu")
        if device not in ("cpu", "cuda", "auto"):
            errors.append(f"model.device must be one of: cpu, cuda, auto. Got: {device}")

        # 验证safety
        safety = config.get("safety", {})
        min_delay = safety.get("min_delay", 0)
        max_delay = safety.get("max_delay", 0)
        if min_delay >= max_delay:
            errors.append("safety.min_delay must be < safety.max_delay")

        max_actions = safety.get("max_actions_per_minute", 0)
        if max_actions > 60:
            errors.append("safety.max_actions_per_minute should not exceed 60")

        # 验证automation.gem_collect
        gem = config.get("automation", {}).get("gem_collect", {})
        if gem.get("enabled"):
            level = gem.get("min_level", 0)
            if not (1 <= level <= 25):
                errors.append(
                    f"gem_collect.min_level must be in [1, 25], got {level}"
                )

        # 验证logging level
        logging_cfg = config.get("logging", {})
        log_level = logging_cfg.get("level", "INFO")
        if log_level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            errors.append(f"logging.level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL")

        return errors


class ConfigManager:
    """配置管理器.

    职责:
    - 配置文件读写
    - 配置验证
    - 热更新（文件监听）
    - 默认值管理

    线程安全: 是

    使用示例:
        bus = EventBus()
        manager = ConfigManager("config.yaml", bus)
        config = manager.load()
        manager.start_watching()
    """

    def __init__(self, config_path: str, event_bus: EventBus):
        """初始化配置管理器.

        Args:
            config_path: 配置文件路径
            event_bus: 事件总线实例
        """
        self._config_path = config_path
        self._event_bus = event_bus
        self._config: Optional[AppConfig] = None
        self._watcher: Optional[Any] = None
        self._lock = threading.Lock()
        self._logger = get_logger(self.__class__.__name__)

    def load(self) -> AppConfig:
        """加载配置文件.

        如果文件不存在, 使用默认配置并创建文件.

        Returns:
            加载的配置对象

        Raises:
            ConfigValidationError: 配置验证失败
        """
        with self._lock:
            if not os.path.exists(self._config_path):
                self._logger.warning(
                    f"Config not found, using defaults: {self._config_path}"
                )
                self._config = AppConfig.get_defaults()
                self.save(self._config)
                return self._config

            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    raw_config = yaml.safe_load(f)

                if not isinstance(raw_config, dict):
                    raw_config = {}

                # 验证配置
                errors = ConfigValidator.validate(raw_config)
                if errors:
                    self._logger.error(f"Config validation errors: {errors}")
                    raise ConfigValidationError(errors)

                self._config = AppConfig.from_dict(raw_config)
                self._logger.info(f"Config loaded: {self._config_path}")
                return self._config

            except yaml.YAMLError as e:
                self._logger.error(f"YAML parse error: {e}")
                raise
            except ConfigValidationError:
                raise
            except Exception as e:
                self._logger.error(f"Failed to load config: {e}")
                raise

    def save(self, config: AppConfig) -> bool:
        """保存配置到文件.

        Args:
            config: 要保存的配置对象

        Returns:
            是否保存成功
        """
        try:
            config_dir = os.path.dirname(self._config_path)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)

            with open(self._config_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    config.to_dict(),
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

            with self._lock:
                self._config = config

            self._logger.info(f"Config saved: {self._config_path}")
            return True

        except Exception as e:
            self._logger.error(f"Failed to save config: {e}")
            return False

    def get(self) -> Optional[AppConfig]:
        """获取当前配置.

        Returns:
            当前配置对象, 未加载时返回None
        """
        with self._lock:
            return self._config

    def get_section(self, section: str) -> Any:
        """获取配置的指定部分.

        Args:
            section: 配置节名称 (window, model, safety, etc.)

        Returns:
            配置节数据, 不存在时返回None
        """
        with self._lock:
            if self._config is None:
                return None
            return getattr(self._config, section, None)

    def set_value(self, section: str, key: str, value: Any) -> bool:
        """设置配置值.

        Args:
            section: 配置节名称
            key: 配置键
            value: 配置值

        Returns:
            是否设置成功
        """
        with self._lock:
            if self._config is None:
                return False

            section_obj = getattr(self._config, section, None)
            if section_obj is None:
                return False

            if hasattr(section_obj, key):
                setattr(section_obj, key, value)
                self._logger.debug(f"Config updated: {section}.{key} = {value}")
                return True
            return False

    def start_watching(self) -> None:
        """启动配置热更新监听.

        使用watchdog库监听配置文件变化, 自动重新加载.
        """
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            class ConfigChangeHandler(FileSystemEventHandler):
                def __init__(self, callback):
                    self._callback = callback

                def on_modified(self, event):
                    if not event.is_directory:
                        self._callback(event)

            self._watcher = Observer()
            handler = ConfigChangeHandler(self._on_config_changed)
            watch_dir = os.path.dirname(self._config_path) or "."
            self._watcher.schedule(handler, recursive=False, path=watch_dir)
            self._watcher.start()
            self._logger.info(f"Config watching started: {watch_dir}")

        except ImportError:
            self._logger.warning(
                "watchdog not installed, config hot-reload disabled"
            )
        except Exception as e:
            self._logger.error(f"Failed to start config watcher: {e}")

    def stop_watching(self) -> None:
        """停止配置热更新监听."""
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher.join(timeout=2)
            self._watcher = None
            self._logger.info("Config watching stopped")

    def _on_config_changed(self, event: Any) -> None:
        """配置变更回调.

        Args:
            event: watchdog事件对象
        """
        time.sleep(0.5)  # 等待文件写入完成
        try:
            new_config = self.load()
            self._event_bus.publish(ConfigChangedEvent(new_config=new_config))
            self._logger.info("Configuration reloaded successfully")
        except Exception as e:
            self._logger.error(f"Config reload failed: {e}")
