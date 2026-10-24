"""答题模式的数据形状。纯数据，不 import cv2 / Qt / workers。"""
from __future__ import annotations

from dataclasses import dataclass

from ..recognizer import BBox

LETTERS: tuple[str, ...] = ("A", "B", "C", "D")

# RapidOcrEngine.detect_text() 的元素形状
TextBlock = tuple[BBox, str, float]


@dataclass(frozen=True)
class ScreenQuestion:
    """一屏题目。`options` 是 {字母: (选项正文, 选项 bbox)}。

    bbox 留着是给点击与绿色判定用的：点哪、验哪都靠它，不能只留文本。
    """

    text: str
    options: dict[str, tuple[str, BBox]]

    def option_texts(self) -> dict[str, str]:
        return {k: v[0] for k, v in self.options.items()}


@dataclass(frozen=True)
class Decision:
    """一次作答决策。source ∈ bank | llm | random（写日志与验收用）。"""

    letter: str
    text: str
    source: str
