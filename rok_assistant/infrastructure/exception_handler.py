import traceback
from typing import Optional
from .logger import get_logger


class ROKAssistantError(Exception):
    """基础异常类"""
    pass


class WindowNotFoundError(ROKAssistantError):
    """窗口未找到异常"""
    pass


class CaptureError(ROKAssistantError):
    """截图异常"""
    pass


class ModelLoadError(ROKAssistantError):
    """模型加载异常"""
    pass


class InferenceError(ROKAssistantError):
    """推理异常"""
    pass


class EngineError(ROKAssistantError):
    """引擎异常"""
    pass


class TaskExecutionError(ROKAssistantError):
    """任务执行异常"""
    pass


class ConfigError(ROKAssistantError):
    """配置异常"""
    pass


class ExceptionHandler:
    """异常处理器"""
    
    def __init__(self):
        self._logger = get_logger(self.__class__.__name__)
    
    def handle_exception(self, e: Exception, context: Optional[str] = None) -> bool:
        """处理异常
        
        Args:
            e: 异常对象
            context: 上下文信息
            
        Returns:
            bool: 是否可以继续执行
        """
        error_message = f"Error: {str(e)}"
        if context:
            error_message = f"{context}: {error_message}"
        
        self._logger.error(error_message)
        self._logger.debug(traceback.format_exc())
        
        # 根据异常类型决定处理策略
        if isinstance(e, (WindowNotFoundError, CaptureError)):
            # 可恢复的错误
            self._logger.info("Attempting to recover...")
            return True
        elif isinstance(e, (ModelLoadError, InferenceError)):
            # 需要重新加载模型
            self._logger.error("Critical error: model issues")
            return False
        elif isinstance(e, ConfigError):
            # 配置错误
            self._logger.error("Configuration error, please check config.yaml")
            return False
        else:
            # 其他异常
            self._logger.error("Unexpected error")
            return True