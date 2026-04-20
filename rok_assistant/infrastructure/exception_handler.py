"""自定义异常模块.

定义系统中使用的所有异常类型, 按照层次分类:
- 核心层异常: 窗口、捕获、模型、推理
- 业务层异常: 任务、元素、频率限制
- 配置异常: 验证失败
- 引擎异常: 不可恢复错误
"""

from typing import List, Optional


class RokAssistantError(Exception):
    """基础异常类.

    所有自定义异常的基类, 提供可恢复性标记.

    Attributes:
        recoverable: 是否可自动恢复
    """

    def __init__(self, message: str, recoverable: bool = True):
        super().__init__(message)
        self.recoverable = recoverable
        self.message = message


# ========== 核心层异常 ==========


class WindowNotFoundError(RokAssistantError):
    """窗口未找到异常.

    当无法找到匹配的游戏窗口时抛出.
    """

    def __init__(self, window_title: str = ""):
        msg = f"Window not found: {window_title}" if window_title else "Window not found"
        super().__init__(msg, recoverable=True)
        self.window_title = window_title


class CaptureError(RokAssistantError):
    """截图失败异常.

    当窗口截图操作失败时抛出.
    """

    def __init__(self, message: str = "Capture failed"):
        super().__init__(message, recoverable=True)


class ModelLoadError(RokAssistantError):
    """模型加载失败异常.

    当YOLO模型文件无法加载时抛出, 不可恢复.
    """

    def __init__(self, message: str = "Model load failed", model_path: str = ""):
        if model_path:
            message = f"Model load failed: {model_path}"
        super().__init__(message, recoverable=False)
        self.model_path = model_path


class InferenceError(RokAssistantError):
    """推理失败异常.

    当YOLO推理过程出错时抛出.
    """

    def __init__(self, message: str = "Inference failed"):
        super().__init__(message, recoverable=True)


# ========== 业务层异常 ==========


class TaskExecutionError(RokAssistantError):
    """任务执行失败异常.

    当自动化任务执行过程中发生错误时抛出.

    Attributes:
        task_id: 失败的任务ID
    """

    def __init__(self, task_id: str, message: str = "Task execution failed"):
        super().__init__(f"Task {task_id}: {message}", recoverable=True)
        self.task_id = task_id


class ElementNotFoundError(RokAssistantError):
    """游戏元素未找到异常.

    当检测不到指定的游戏界面元素时抛出.

    Attributes:
        element_type: 未找到的元素类型
        context: 上下文信息
    """

    def __init__(self, element_type: str, context: str = ""):
        msg = f"Element not found: {element_type}"
        if context:
            msg += f" ({context})"
        super().__init__(msg, recoverable=True)
        self.element_type = element_type
        self.context = context


class RateLimitError(RokAssistantError):
    """操作频率超限异常.

    当操作频率超过安全限制时抛出.
    """

    def __init__(self, message: str = "Action rate limit exceeded"):
        super().__init__(message, recoverable=True)


# ========== 配置异常 ==========


class ConfigValidationError(RokAssistantError):
    """配置验证失败异常.

    当配置文件格式或内容不合法时抛出, 不可恢复.

    Attributes:
        errors: 验证错误列表
    """

    def __init__(self, errors: List[str]):
        super().__init__(
            f"Config validation failed: {errors}", recoverable=False
        )
        self.errors = errors


# ========== 引擎异常 ==========


class EngineError(RokAssistantError):
    """引擎异常.

    当自动化引擎发生不可恢复错误时抛出.
    """

    def __init__(self, message: str = "Engine error"):
        super().__init__(message, recoverable=False)
