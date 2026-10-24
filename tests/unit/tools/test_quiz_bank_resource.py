"""随包题库：不是「文件在不在」，而是「答题模式的地面真值是否真在里面」。

这份数据是答题模式的权威答案来源（学习结果不得覆盖它），所以格式与
几条关键条目都要钉住；换题库文件等于换行为，必须在这里留痕。
"""
import json

import pytest

from rok_assistant.infra.app_paths import resolve_asset

BANK_PATH = resolve_asset("templates/quiz/quiz_bank.json")

# (题干, 答案) —— 与 `dati/test/` 素材一一对应（spec §11.1）。
# 第 3 条是**模糊匹配**的关键回归点：屏幕 OCR 出「赞助」，题库写「资助」。
EXPECTED = [
    ("统帅贝利撒留的昵称是？", "最后的罗马人"),
    ("联盟领土界面中，领土资源最多能储存多长时间的产量？", "24小时"),
    ("哥伦布的冒险航海是由欧洲哪个国家的国王资助的？", "西班牙"),
    ("空间中哪一指数越低，越接近真空的状态？", "气压"),
]


@pytest.fixture(scope="module")
def bank():
    assert BANK_PATH.is_file(), f"随包题库不存在：{BANK_PATH}"
    return json.loads(BANK_PATH.read_text(encoding="utf-8"))


def test_bank_is_a_non_empty_array_of_q_a_pairs(bank):
    assert isinstance(bank, list) and len(bank) >= 1000
    for entry in bank[:50]:
        assert isinstance(entry["q"], str) and entry["q"].strip()
        assert isinstance(entry["a"], str) and entry["a"].strip()


def test_bank_numbers_are_unique(bank):
    """`no` 是「第几题」的展示编号，重复说明导入时拼过文件。"""
    nos = [e["no"] for e in bank]
    assert len(nos) == len(set(nos))


@pytest.mark.parametrize("question,answer", EXPECTED)
def test_bank_contains_the_acceptance_ground_truth(bank, question, answer):
    hits = [e for e in bank if e["q"] == question]
    assert hits, f"题库缺这条地面真值：{question}"
    assert hits[0]["a"] == answer


def test_bank_ships_with_the_package():
    """绿色包缺了它，答题只能靠 LLM/随机——必须在打包时就拦下。"""
    from tools.build_package import REQUIRED_RESOURCES
    assert "templates/quiz/quiz_bank.json" in REQUIRED_RESOURCES
