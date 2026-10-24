"""三级作答决策：题库精确 → 题库模糊 → 大模型 → 随机。

`source` 会写进日志与验收输出，**是排查「为什么答错」的第一判据**：
bank 答错是题库脏了，llm 答错是模型不会，random 答错是两腿都没兜住。
"""
from __future__ import annotations

import random

from ...infra.logger import get_logger
from .bank import QuizBank, normalize, similarity
from .models import LETTERS, Decision, ScreenQuestion

logger = get_logger(__name__)


class Solver:
    def __init__(self, bank: QuizBank, llm=None, *,
                 fuzzy_threshold: float = 0.72,
                 answer_threshold: float = 0.6,
                 rng: random.Random | None = None):
        self._bank = bank
        self._llm = llm
        self._fuzzy_threshold = float(fuzzy_threshold)
        self._answer_threshold = float(answer_threshold)
        self._rng = rng if rng is not None else random.Random()

    def answer(self, question: ScreenQuestion) -> Decision | None:
        """给一道题一个决策；四选项不齐时返回 None（**不猜**）。"""
        letters = [l for l in LETTERS if l in question.options]
        if not letters:
            return None

        hit = self._bank.lookup(question.text, threshold=self._fuzzy_threshold)
        if hit is not None:
            letter = self._match_answer(hit.answer, question)
            if letter is not None:
                return Decision(letter, question.options[letter][0], "bank")
            logger.info("[答题] 题库答案 %r 对不上屏幕上的任何选项，"
                        "继续走兜底", hit.answer)

        if self._llm is not None:
            letter = self._llm.choose(question.text, question.option_texts())
            if letter in question.options:
                return Decision(letter, question.options[letter][0], "llm")

        letter = self._rng.choice(letters)
        return Decision(letter, question.options[letter][0], "random")

    def _match_answer(self, answer: str, question: ScreenQuestion) -> str | None:
        """题库/模型的答案文本 → 屏幕上的选项字母。

        先精确（归一化后相等），再按相似度取最高且过 `answer_threshold`
        的那个。四条选项里唯一命中才算——两个都像就放弃，绝不硬点。
        """
        key = normalize(answer)
        if not key:
            return None
        exact = [l for l, (text, _box) in question.options.items()
                 if normalize(text) == key]
        if len(exact) == 1:
            return exact[0]
        best_letter, best_score = None, 0.0
        for letter, (text, _box) in question.options.items():
            score = similarity(key, normalize(text))
            if score > best_score:
                best_letter, best_score = letter, score
        if best_letter is not None and best_score >= self._answer_threshold:
            return best_letter
        return None
