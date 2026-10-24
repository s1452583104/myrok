"""答题模式的协调器。

与宝石模式同一副骨架：一台模拟器一个号、各干各的，没有事件总线跨实例
路由、没有动作账本、没有车头/成员分工。

**跨轮复用的是活对象，不是状态机**（与寨子模式同一条原则）：
  * `QuizBank` —— 1076 条随包题库 + 学习库，读一次就够
  * OCR 引擎 —— 加载模型要好几秒
  * `Solver` —— 每次 start 重建一次（解包配置，很便宜）
SM 每轮由 `_sm_factory_for` 重建，见的都是这几个对象。
"""
from __future__ import annotations

from ..core.quiz.bank import QuizBank
from ..core.quiz.llm import LLMClient
from ..core.quiz.solver import Solver
from ..infra.app_paths import resolve_asset, user_dir
from ..infra.config import AppMode
from ..infra.logger import get_logger
from ..workers.factory import create_quiz_state_machine
from .base_runtime import BaseCoordinator

logger = get_logger(__name__)


def _default_bank() -> QuizBank:
    """随包题库只读、学习结果写 `user_dir()`（冻结后 exe 同级）。

    **两手都要用 app_paths**：相对路径按 CWD 解在绿色包里是错的
    （双击时 CWD 可能是 System32）。
    """
    return QuizBank(shipped_path=resolve_asset("templates/quiz/quiz_bank.json"),
                    learned_path=user_dir() / "quiz" / "learned.json")


def _llm_from_config(cfg) -> LLMClient | None:
    """没启用、或没填 Key → None（题库外的题直接随机，不发请求）。"""
    if not cfg.enabled or not cfg.api_key.strip():
        return None
    return LLMClient(base_url=cfg.base_url, model=cfg.model,
                     api_key=cfg.api_key, timeout_s=cfg.timeout_s)


class QuizCoordinator(BaseCoordinator):
    def __init__(self, config, event_bus=None, template_dir=None, *,
                 ocr=None, bank_factory=None):
        super().__init__(config, event_bus=event_bus,
                         template_dir=template_dir)
        self._ocr = ocr
        self._bank_factory = bank_factory or _default_bank
        self._bank: QuizBank | None = None
        self._solver: Solver | None = None

    def _instances(self):
        return self._config.instances_for(AppMode.QUIZ)

    def _pre_start(self, instances) -> None:
        if self._bank is None:
            self._bank = self._bank_factory()
            self._bank.load()
            logger.info("[答题] 题库已加载：%s 条（随包 + 学习）",
                        self._bank.size)
        if self._ocr is None:
            # 延迟 import：加载 onnxruntime 要好几秒，模块导入时不该付这笔钱
            from ..core.recognizers.ocr_text import RapidOcrEngine
            self._ocr = RapidOcrEngine()
        llm = _llm_from_config(self._config.quiz.llm)
        logger.info("[答题] 大模型兜底：%s", "已启用" if llm else "未启用")
        self._solver = Solver(self._bank, llm,
                              fuzzy_threshold=self._config.quiz.fuzzy_threshold)

    def _sm_factory_for(self, char, handle, recognizers, profile):
        quiz = self._config.quiz
        return create_quiz_state_machine(
            char, handle, recognizers, self._ocr, self._bank, self._solver,
            verify_delay=quiz.verify_delay,
            min_green_ratio=quiz.min_green_ratio,
            round_cooldown_min=quiz.round_cooldown_min,
            parse_retries=quiz.parse_retries,
            entry_taps=quiz.entry_taps,
            auto_click=quiz.auto_click,
            human=profile)

    def _max_rounds(self) -> int:
        """`quiz.max_rounds`，**不是** `app.max_rounds`（spec §5）。"""
        return self._config.quiz.max_rounds
