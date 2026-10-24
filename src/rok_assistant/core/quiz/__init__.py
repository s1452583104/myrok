"""答题模式的纯逻辑包：OCR 块解析、题库、绿色判定、三级决策、LLM 兜底。

**这里不 import Qt，也不 import workers**：`core` 只向下依赖 `infra`。
"""
from .models import LETTERS, Decision, ScreenQuestion, TextBlock

__all__ = ["LETTERS", "Decision", "ScreenQuestion", "TextBlock"]
