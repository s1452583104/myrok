"""题库：归一化、精确/模糊匹配、随包权威不被覆盖、学习原子落盘。"""
import json
import threading

import pytest

from rok_assistant.core.quiz.bank import QuizBank, normalize

SHIPPED = [
    {"no": 1, "q": "统帅贝利撒留的昵称是？", "a": "最后的罗马人"},
    {"no": 2, "q": "联盟领土界面中，领土资源最多能储存多长时间的产量？", "a": "24小时"},
    {"no": 3, "q": "哥伦布的冒险航海是由欧洲哪个国家的国王资助的？", "a": "西班牙"},
]


@pytest.fixture
def paths(tmp_path):
    shipped = tmp_path / "quiz_bank.json"
    shipped.write_text(json.dumps(SHIPPED, ensure_ascii=False), encoding="utf-8")
    return shipped, tmp_path / "learned.json"


def _bank(paths) -> QuizBank:
    bank = QuizBank(shipped_path=paths[0], learned_path=paths[1])
    bank.load()
    return bank


# ---- 归一化 ----

def test_normalize_strips_fullwidth_punctuation_and_spaces():
    assert normalize("  统帅贝利撒留的昵称是？ ") == normalize("统帅贝利撒留的昵称是?")


def test_normalize_drops_the_question_number_prefix():
    assert normalize("Q12 统帅贝利撒留的昵称是？") == "统帅贝利撒留的昵称是"


def test_normalize_keeps_digits():
    """`24小时` 与 `48小时` 是两道不同的题：把数字归一没了就是灾难。"""
    assert normalize("24小时") != normalize("48小时")
    assert normalize("24小时") == "24小时"


# ---- 匹配 ----

def test_exact_lookup(paths):
    hit = _bank(paths).lookup("统帅贝利撒留的昵称是？")
    assert hit is not None and hit.answer == "最后的罗马人"
    assert hit.source == "exact" and hit.score == 1.0


def test_fuzzy_lookup_survives_one_wrong_character(paths):
    """屏幕 OCR 出「赞助」、题库写「资助」——这条是 fuzzy_threshold 的关键回归点。"""
    hit = _bank(paths).lookup("哥伦布的冒险航海是由欧洲哪个国家的国王赞助的？")
    assert hit is not None
    assert hit.answer == "西班牙"
    assert hit.source == "fuzzy" and hit.score >= 0.72


def test_unrelated_question_is_a_miss(paths):
    assert _bank(paths).lookup("以下食物中，东汉政治家曹操不可能吃到的是？") is None


def test_empty_question_is_a_miss(paths):
    assert _bank(paths).lookup("   ") is None


# ---- 学习 ----

def test_learn_writes_and_reads_back(paths):
    bank = _bank(paths)
    assert bank.learn("以下食物中，东汉政治家曹操不可能吃到的是？", "玉米") is True
    assert bank.lookup("以下食物中，东汉政治家曹操不可能吃到的是？").answer == "玉米"
    # 落盘后重新加载仍在
    again = _bank(paths)
    assert again.lookup("以下食物中，东汉政治家曹操不可能吃到的是？").answer == "玉米"


def test_learn_never_overwrites_a_shipped_answer(paths):
    """一次颜色误判不得污染权威答案：随包条目只读。"""
    bank = _bank(paths)
    assert bank.learn("统帅贝利撒留的昵称是？", "战火双刃") is False
    assert bank.lookup("统帅贝利撒留的昵称是？").answer == "最后的罗马人"


def test_learned_entries_may_correct_each_other(paths):
    bank = _bank(paths)
    q = "下面哪个技能不是贝利撒留的？"
    bank.learn(q, "雷霆之势")
    assert bank.learn(q, "战火双刃") is True      # 后学覆盖先学
    assert bank.lookup(q).answer == "战火双刃"


def test_learn_is_idempotent(paths):
    bank = _bank(paths)
    q = "同一道题"
    assert bank.learn(q, "甲") is True
    assert bank.learn(q, "甲") is False


def test_learn_is_atomic_and_leaves_no_tmp_file(paths):
    bank = _bank(paths)
    bank.learn("原子写测试", "乙")
    rows = json.loads(paths[1].read_text(encoding="utf-8"))
    assert [r["q"] for r in rows] == ["原子写测试"]
    assert not list(paths[1].parent.glob("*.tmp"))


def test_corrupt_learned_file_does_not_raise(paths):
    """学习文件被手改坏不该让整轮跑挂：随包题库照常可用。"""
    paths[1].write_text("{ 这不是 JSON", encoding="utf-8")
    bank = _bank(paths)
    assert bank.lookup("统帅贝利撒留的昵称是？").answer == "最后的罗马人"


def test_missing_shipped_file_degrades_to_empty(tmp_path):
    bank = QuizBank(shipped_path=tmp_path / "nope.json",
                    learned_path=tmp_path / "learned.json")
    bank.load()
    assert bank.size == 0
    assert bank.lookup("任何题") is None


# ---- 并发与写盘失败（一个 bank 被所有答题线程共享） ----

def test_concurrent_lookup_and_learn_does_not_raise(paths):
    """learn 增长字典时，另一线程的 lookup 不得撞上 changed size during iteration。"""
    bank = _bank(paths)
    n = 300
    errors: list[BaseException] = []

    def worker(tag: str) -> None:
        try:
            for i in range(n):
                q = f"{tag}-并发题-{i}"
                assert bank.learn(q, f"答案{tag}-{i}") is True
                hit = bank.lookup(q)
                assert hit is not None and hit.answer == f"答案{tag}-{i}"
                # 未命中题会遍历整张学习表（模糊腿），正是并发迭代的触发点
                bank.lookup("完全不存在的并发题目")
        except BaseException as exc:  # noqa: BLE001 - 测试要收集任何逃逸异常
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in ("甲", "乙")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert bank.size == len(SHIPPED) + 2 * n
    for tag in ("甲", "乙"):
        for i in range(n):
            assert bank.lookup(f"{tag}-并发题-{i}").answer == f"答案{tag}-{i}"


def test_learn_returns_true_and_keeps_memory_when_disk_write_fails(
        paths, monkeypatch):
    """写盘失败仍返回 True：内存已生效，只是丢持久化。"""
    bank = _bank(paths)

    def boom(*args, **kwargs):
        raise OSError("模拟磁盘满")

    monkeypatch.setattr("rok_assistant.core.quiz.bank.os.replace", boom)
    assert bank.learn("写盘失败但内存生效", "丙") is True
    assert bank.lookup("写盘失败但内存生效").answer == "丙"
    assert bank.size == len(SHIPPED) + 1
