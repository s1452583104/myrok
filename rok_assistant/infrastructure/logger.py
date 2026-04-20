"""日志系统模块.

提供统一的日志管理功能, 支持:
- 文件轮转日志
- 控制台输出
- 多级别日志记录
- 模块化日志命名
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional


class LoggerFactory:
    """日志工厂.

    职责:
    - 统一日志配置
    - 文件轮转
    - 格式化管理

    使用示例:
        LoggerFactory.setup(log_level="DEBUG", log_file="logs/app.log")
        logger = LoggerFactory.get_logger("MyModule")
        logger.info("Hello world")
    """

    _initialized: bool = False

    @classmethod
    def setup(
        cls,
        log_level: str = "INFO",
        log_file: str = "logs/rok_assistant.log",
        max_size: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
    ) -> None:
        """初始化日志系统.

        Args:
            log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: 日志文件路径
            max_size: 单个日志文件最大大小 (字节)
            backup_count: 保留的旧日志文件数量
        """
        if cls._initialized:
            return

        # 创建日志目录
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        # 根日志器配置
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        # 避免重复添加handler
        if root_logger.handlers:
            root_logger.handlers.clear()

        # 格式
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 文件处理器（轮转）
        try:
            file_handler = RotatingFileHandler(
                log_file, maxBytes=max_size, backupCount=backup_count, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
            root_logger.addHandler(file_handler)
        except (OSError, PermissionError) as e:
            print(f"Warning: Could not create log file handler: {e}", file=sys.stderr)

        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        root_logger.addHandler(console_handler)

        cls._initialized = True

    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """获取命名日志记录器.

        Args:
            name: 模块/类名称

        Returns:
            配置好的Logger实例
        """
        return logging.getLogger(f"rok.{name}")


# 便捷函数
def get_logger(name: str) -> logging.Logger:
    """获取日志记录器的便捷函数.

    Args:
        name: 模块/类名称

    Returns:
        配置好的Logger实例
    """
    return LoggerFactory.get_logger(name)
