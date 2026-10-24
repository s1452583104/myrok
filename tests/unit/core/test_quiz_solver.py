"""三级决策：题库精确 → 题库模糊 → 大模型 → 随机。

顺序是用户 2026-10-24 拍板的：「题库优先、AI 兜底、答不出随机选一个，
靠学习补」。随机是**兜底而不是选项**——没答案时也必须作答，否则整轮
停在原地（答题活动没有「跳过」）。
"""
import json
import random

import pytest

from rok_assistant.core.quiz.bank import QuizBank
from rok_assistant.core.quiz.models import ScreenQuestion
from rok_assistant.core.quiz.solver import Solver
from rok_assistant.core.recognizer import BBox

SHIPPED = [
    {"no": 1, "q": "统帅贝利撒留的昵称是？", "a": "最后的罗马人"},
    {"no": 2, "q": "哥伦布的冒险航海是由欧洲哪个国家的国王资助的？", "a": "西班牙"},
    {"no": 3, "q": "以下哪位统帅才貌倾国？", "a": "不败的复兴者"},
]


def _sq(text: str, *options: str) -> ScreenQuestion:
    letters = "ABCD"
    return ScreenQuestion(
        text=text,
        options={letters[i]: (t, BBox(10, 100 + i * 40, 200, 130 + i * 40))
                 for i, t in enumerate(options)})


@pytest.fixture
def bank(tmp_path):
    shipped = tmp_path / "shipped.json"
    shipped.write_text(json.dumps(SHIPPED, ensure_ascii=False), encoding="utf-8")
    b = QuizBank(shipped_path=shipped, learned_path=tmp_path / "learned.json")
    b.load()
    return b


class _StubLLM:
    def __init__(self, letter=None):
        self.letter = letter
        self.calls = []

    def choose(self, question, options):
        self.calls.append((question, dict(options)))
        return self.letter


# ---- 题库腿 ----

def test_exact_question_uses_the_bank(bank):
    d = Solver(bank).answer(_sq("统帅贝利撒留的昵称是？",
                               "战火双刃", "最后的罗马人", "天选之豹", "不败的复兴者"))
    assert d.letter == "B" and d.text == "最后的罗马人" and d.source == "bank"


def test_one_ocr_wrong_character_still_hits_the_bank(bank):
    """屏幕读成「赞助」，题库写「资助」——fuzzy_threshold 的回归点。"""
    d = Solver(bank).answer(_sq("哥伦布的冒险航海是由欧洲哪个国家的国王赞助的？",
                               "葡萄牙", "西班牙", "意大利", "印度"))
    assert d.letter == "B" and d.source == "bank"


def test_bank_answer_maps_onto_a_misread_option(bank):
    """题库答「不败的复兴者」，屏幕 OCR 成「不的复兴者」：
    答案→选项的对齐要容错（answer_threshold=0.6），否则题库白查。"""
    d = Solver(bank).answer(_sq("以下哪位统帅才貌倾国？",
                               "战火双刃", "天选之豹", "不的复兴者", "最后的罗马人"))
    assert d.letter == "C" and d.source == "bank"


def test_bank_hit_never_calls_the_llm(bank):
    llm = _StubLLM("A")
    Solver(bank, llm).answer(_sq("统帅贝利撒留的昵称是？",
                                "战火双刃", "最后的罗马人", "甲", "乙"))
    assert llm.calls == []


# ---- 大模型腿 ----

def test_llm_is_used_when_the_bank_misses(bank):
    llm = _StubLLM("D")
    d = Solver(bank, llm).answer(_sq("以下食物中，东汉政治家曹操不可能吃到的是？",
                                    "葡萄", "河蚌", "玉米", "栗子"))
    assert (d.letter, d.text, d.source) == ("D", "栗子", "llm")
    assert llm.calls[0][0].startswith("以下食物中")


def test_unmappable_bank_answer_falls_through_to_the_llm(bank):
    """题库命中了题目，但答案对不上任何一个选项（选项被 OCR 读烂）：
    不能硬点，退给大模型。"""
    llm = _StubLLM("A")
    d = Solver(bank, llm).answer(
        _sq("统帅贝利撒留的昵称是？", "甲甲甲", "乙乙乙", "丙丙丙", "丁丁丁"))
    assert d.source == "llm" and d.letter == "A"


def test_llm_letter_outside_the_options_falls_to_random(bank):
    d = Solver(bank, _StubLLM("E"), rng=random.Random(7)).answer(
        _sq("曹操不可能吃到的是？", "葡萄", "河蚌", "玉米", "栗子"))
    assert d.source == "random" and d.letter in "ABCD"


# ---- 随机腿 ----

def test_random_is_deterministic_for_a_given_seed(bank):
    q = _sq("曹操不可能吃到的是？", "葡萄", "河蚌", "玉米", "栗子")
    first = Solver(bank, rng=random.Random(3)).answer(q)
    again = Solver(bank, rng=random.Random(3)).answer(q)
    assert first == again and first.source == "random"


def test_no_options_returns_none(bank):
    assert Solver(bank).answer(ScreenQuestion(text="题", options={})) is None
