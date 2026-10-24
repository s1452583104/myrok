# -*- coding: utf-8 -*-
"""答题模式验收：拿 dati/test 的真实素材跑生产判据，逐条打印 PASS/FAIL/SKIP。

用法:
  $PY -X utf8 -I tools/quiz_acceptance.py [素材目录]

素材目录默认 `dati/test`。目录不存在或没有素材 -> 打印 SKIP、退出 0：
`dati/` 在版本控制外，pytest 与打包流程都不许依赖它（spec §11）。
有 FAIL 时退出 1；参数错退出 2。

判据（spec §11.3）：
  1. parse   —— 题干与四个选项对得上（比对用同一帧的 OCR 结果，OCR 错字不追究）
  2. decide  —— 有真值的题必须题库命中且字母正确；题库外的题只断言来源
  3. verify  —— 绿色高亮判到同一个字母，且其余选项在该阈值下全判否
  4. learn   —— 学习写盘、不覆盖随包答案

**本脚本不进 pytest**：整屏 OCR 是秒级的，且素材未入库。
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import cv2                                                          # noqa: E402
import numpy as np                                                  # noqa: E402

from rok_assistant.core.quiz.bank import QuizBank                    # noqa: E402
from rok_assistant.core.quiz.models import LETTERS                   # noqa: E402
from rok_assistant.core.quiz.screen import (                         # noqa: E402
    ENTRY_LABELS, detect_quiz, find_quiz_entry, parse_question)
from rok_assistant.core.quiz.solver import Solver                    # noqa: E402
from rok_assistant.core.quiz.verify import (                         # noqa: E402
    green_ratio, pick_correct_option)
from rok_assistant.core.recognizers.ocr_text import RapidOcrEngine   # noqa: E402
from rok_assistant.infra.app_paths import resolve_asset              # noqa: E402

DEFAULT_MATERIALS = ROOT / "dati" / "test"
BANK_PATH = resolve_asset("templates/quiz/quiz_bank.json")
MIN_GREEN = 0.55          # 与 QuizConfig.min_green_ratio 的默认值一致

# 文件名里的稳定片段。**不要拿中文名当键**：控制台是 GBK，中文会被转义。
_STILLS = {
    "activity": "_10_63",
    "q4": "_11_63",
    "q1": "_12_63",
    "q2": "_13_63",
    "q3": "_14_63",
}
_VIDEOS = {"video1": "9212bd3a", "video2": "d343aa61"}

# spec §11.1 的地面真值：(素材键, 期望字母或 None, 期望来源)
# q4 是**题库未命中**的那张（曹操吃不到什么）——只断言来源，字母由随机决定。
_GROUND_TRUTH = [
    ("q1", "A", "bank"),      # 统帅贝利撒留的昵称
    ("q2", "A", "bank"),      # 联盟领土最多储存 24 小时
    ("q3", "B", "bank"),      # 哥伦布 / 西班牙：画面写「赞助」、题库写「资助」→ 模糊命中
    ("q4", None, "random"),   # 曹操不可能吃到 → 题库没有
]

# q1/q2/q3 的题干与四个选项的**稳定子串**（实测 OCR 输出）。用子串而不是
# 全文：OCR 对生僻字会读错（「不死」→「不的」），绑全文等于绑 OCR 模型版本。
_PARSE_EXPECT = {
    "q1": ("贝利撒留", {"A": "罗马人", "B": "战火双刃",
                        "C": "天选之豹", "D": "复兴者"}),
    "q2": ("领土资源", {"A": "24小时", "B": "36小时",
                        "C": "12小时", "D": "18小时"}),
    "q3": ("哥伦布", {"A": "葡萄牙", "B": "西班牙",
                      "C": "意大利", "D": "印度"}),
}

# 视频抽帧：该帧里「绿色高亮那一项」的文本片段
_VERIFY_MARKS = [
    ("video1", 27.3, "气压"),
    # 只取名字前缀：本机 RapidOCR 把 `克利奥帕特拉` 读成 `克利奥佩特拉`，
    # 验收不该因 OCR 的「帕/佩」差异判失败（判据是「绿的是哪个选项」）。
    ("video1", 35.4, "克利奥"),
]
# 只 OCR 出 3 个选项 + 有横跨分列轴的复活 toast：期望**解析失败**（→ SM 重试）
_PARSE_FAIL_FRAME = ("video2", 57.5)
# 习题演练的正常帧：验「提示语 / 求助 / 放弃 不进候选池」
_PRACTICE_FRAME = ("video1", 10.9)


def index_materials(root: Path) -> dict[str, Path]:
    """按文件名里的稳定片段索引素材；缺失的键**不出现**（调用方据此 SKIP）。"""
    out: dict[str, Path] = {}
    if not root.is_dir():
        return out
    files = [p for p in root.iterdir() if p.is_file()]
    for key, marker in {**_STILLS, **_VIDEOS}.items():
        for p in files:
            if marker in p.name:
                out[key] = p
                break
    return out


def entry_hit(blocks, point):
    """验收回显：`point` 来自哪个入口标签块 → `(标签, BBox)`；认不出 → `(None, None)`。

    纯函数，不读素材——`tools.quiz_acceptance` 的助手测试直接调它。
    """
    if point is None:
        return None, None
    for box, text, _conf in blocks:
        if box.center() == tuple(point):
            t = text.strip()
            for label in ENTRY_LABELS:
                if label in t:
                    return label, box
    return None, None


def is_practice_card_row(box, blocks) -> bool:
    """所选块是不是「习题演练」的可点卡片行，而不是右上方的栏目头。

    真实活动帧（2664×1200）：栏目头 (1547,388,1688,428) 高 40，在卡片行
    上方；四张卡片行高 37，全部在它下面。按高度取块会点到栏目头。
    """
    same = [b for b, text, _conf in blocks if text.strip() == "习题演练"]
    if box is None or not same:
        return False
    header = min(same, key=lambda b: b.center()[1])
    return (box != header
            and box.center()[1] > header.center()[1]
            and (box.y2 - box.y1) < (header.y2 - header.y1))


def _imread(path: Path) -> np.ndarray:
    """读图：Windows 上 `cv2.imread` 读不了中文路径，先按字节读再解码。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise SystemExit(f"读不出素材：{path}")
    return frame


def _sample_video(path: Path, seconds: float) -> np.ndarray:
    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise SystemExit(f"视频抽帧失败：{path} @{seconds}s")
    return frame


class _Report:
    """PASS / FAIL / SKIP 三态计数。FAIL 决定退出码。"""

    def __init__(self):
        self.fails = 0
        self.passes = 0
        self.skips = 0

    def check(self, ok: bool, name: str, detail: str = "") -> bool:
        tag = "PASS" if ok else "FAIL"
        if ok:
            self.passes += 1
        else:
            self.fails += 1
        print(f"{tag}  {name}" + (f"  —— {detail}" if detail else ""))
        return ok

    def skip(self, name: str, detail: str = "") -> None:
        self.skips += 1
        print(f"SKIP  {name}" + (f"  —— {detail}" if detail else ""))

    def summary(self) -> None:
        print(f"\n合计：{self.passes} PASS / {self.fails} FAIL / "
              f"{self.skips} SKIP")


def _letter_holding(question, marker: str) -> str | None:
    """选项文本里含 `marker` 的那个字母。"""
    for letter, text in question.option_texts().items():
        if marker in text:
            return letter
    return None


def _check_stills(found, engine, solver, rep: _Report) -> None:
    # ---- 活动页：认得出、没有题目、能定位入口 ----
    path = found.get("activity")
    if path is None:
        rep.skip("活动页", "素材缺失")
    else:
        frame = _imread(path)
        blocks = engine.detect_text(frame)
        rep.check(detect_quiz(blocks), "活动页 detect_quiz()",
                  f"{frame.shape[1]}x{frame.shape[0]}，{len(blocks)} 块")
        rep.check(parse_question(blocks, frame.shape[1]) is None,
                  "活动页没有题目（parse 必须 None）")
        # 正常帧：必须优先命中「进入」按钮，而不是同名/近名的习题演练块
        entry = find_quiz_entry(blocks)
        label, box = entry_hit(blocks, entry)
        rep.check("进入" in (label or ""), "活动页优先命中「进入」",
                  f"标签={label} 框={box} 点={entry}")
        # 回退级：过滤掉「进入」块后再找，必须选到卡片行（不是 40px 栏目头，
        # 也不是 `习题演练来获取` 这类说明文字）
        no_enter = [b for b in blocks if "进入" not in b[1].strip()]
        fallback = find_quiz_entry(no_enter)
        fb_label, fb_box = entry_hit(no_enter, fallback)
        rep.check(fb_label == "习题演练" and is_practice_card_row(fb_box, no_enter),
                  "过滤「进入」后回退到「习题演练」卡片行",
                  f"标签={fb_label} 框={fb_box} 中心="
                  f"{None if fb_box is None else fb_box.center()}")

    # ---- 四张答题帧：解析 + 决策 ----
    for key, want_letter, want_source in _GROUND_TRUTH:
        path = found.get(key)
        if path is None:
            rep.skip(key, "素材缺失")
            continue
        frame = _imread(path)
        blocks = engine.detect_text(frame)
        q = parse_question(blocks, frame.shape[1])
        if q is None:
            rep.check(False, f"{key} 解析", "认不出 4 个选项")
            continue
        rep.check(sorted(q.options) == list(LETTERS), f"{key} 四个选项",
                  " / ".join(f"{k}.{t}" for k, t in q.option_texts().items()))
        expect = _PARSE_EXPECT.get(key)
        if expect is not None:
            needle, want_opts = expect
            texts = q.option_texts()
            rep.check(needle in q.text, f"{key} 题干含「{needle}」", q.text)
            rep.check(all(t.strip() for t in texts.values()),
                      f"{key} 选项文本非空", " / ".join(texts.values()))
            wrong = [f"{l}={texts.get(l)!r}（期望含「{want}」）"
                     for l, want in want_opts.items()
                     if want not in texts.get(l, "")]
            rep.check(not wrong, f"{key} 选项文本符合预期",
                      " / ".join(wrong) if wrong else
                      " / ".join(f"{l}.{texts[l]}" for l in LETTERS))
        d = solver.answer(q)
        if d is None:
            rep.check(False, f"{key} 决策", "Solver 没给答案")
            continue
        detail = f"选 {d.letter}. {d.text}（source={d.source}）"
        if want_letter is None:
            rep.check(d.source == want_source, f"{key} 决策来源", detail)
        else:
            rep.check(d.source == want_source and d.letter == want_letter,
                      f"{key} 决策", detail)


def _check_videos(found, engine, rep: _Report, bank: QuizBank,
                  learned_path: Path) -> None:
    # ---- 正常习题帧：四选项 + 提示语/按钮不进候选池 ----
    key, seconds = _PRACTICE_FRAME
    path = found.get(key)
    if path is None:
        rep.skip("习题帧", "素材缺失")
    else:
        frame = _sample_video(path, seconds)
        blocks = engine.detect_text(frame)
        q = parse_question(blocks, frame.shape[1])
        if q is None:
            rep.check(False, "习题帧解析", f"{key}@{seconds}s 认不出 4 个选项")
        else:
            texts = " ".join(q.option_texts().values())
            bad = [w for w in ("求助", "放弃", "机会") if w in texts]
            rep.check(not bad, "提示语/按钮不进选项池",
                      f"4 个选项，误入 {bad}" if bad else
                      " / ".join(q.option_texts().values()))

    # ---- 绿色高亮：判到同一个字母，其余全判否 ----
    for key, seconds, marker in _VERIFY_MARKS:
        path = found.get(key)
        if path is None:
            rep.skip(f"{key}@{seconds}s", "素材缺失")
            continue
        frame = _sample_video(path, seconds)
        blocks = engine.detect_text(frame)
        q = parse_question(blocks, frame.shape[1])
        if q is None:
            rep.check(False, f"{key}@{seconds}s 解析", "认不出 4 个选项")
            continue
        want = _letter_holding(q, marker)
        if want is None:
            rep.check(False, f"{key}@{seconds}s 定位绿块",
                      f"没有选项含「{marker}」")
            continue
        boxes = {k: v[1] for k, v in q.options.items()}
        got = pick_correct_option(frame, boxes, min_ratio=MIN_GREEN)
        ratios = {k: round(green_ratio(frame, b), 2) for k, b in boxes.items()}
        rep.check(got == want, f"{key}@{seconds}s 绿色判定",
                  f"期望 {want}「{marker}」，得到 {got}；绿占比 {ratios}")
        others = [k for k in boxes if k != want]
        rep.check(all(ratios[k] < MIN_GREEN for k in others),
                  f"{key}@{seconds}s 其余选项全判否",
                  f"{{ {', '.join(f'{k}: {ratios[k]}' for k in others)} }}")

    # ---- 只 OCR 出 3 个选项：期望解析失败（→ SM 原地重试） ----
    key, seconds = _PARSE_FAIL_FRAME
    path = found.get(key)
    if path is None:
        rep.skip("3 选项帧", "素材缺失")
    else:
        frame = _sample_video(path, seconds)
        blocks = engine.detect_text(frame)
        q = parse_question(blocks, frame.shape[1])
        rep.check(q is None, f"{key}@{seconds}s 3 个选项必须解析失败",
                  f"得到 {None if q is None else q.option_texts()}")

    # ---- 学习：新题写盘、随包答案不被覆盖 ----
    key, seconds, _marker = _VERIFY_MARKS[0]
    path = found.get(key)
    if path is None:
        rep.skip("学习", "素材缺失")
        return
    frame = _sample_video(path, seconds)
    blocks = engine.detect_text(frame)
    q = parse_question(blocks, frame.shape[1])
    if q is None:
        rep.skip("学习", "该帧解析失败")
        return
    boxes = {k: v[1] for k, v in q.options.items()}
    correct = pick_correct_option(frame, boxes, min_ratio=MIN_GREEN)
    # 学「绿的那个选项」；没判出绿色就退到第一个选项——这里验的是写盘链路，
    # 不是答案对不对（绿色判定在上面的 verify 段已经单独断言过）。
    answer = q.options[correct][0] if correct is not None \
        else next(iter(q.option_texts().values()))
    probe = q.text + "（验收探针）"          # 保证是题库里没有的新题
    shipped_before = BANK_PATH.read_bytes()
    rep.check(bank.learn(probe, answer), "learn 写入新题", probe)
    rep.check(BANK_PATH.read_bytes() == shipped_before, "learn 不碰随包题库")
    entries = json.loads(learned_path.read_text(encoding="utf-8"))
    rep.check(any(e.get("a") == answer for e in entries),
              "learned.json 读得回来", f"{len(entries)} 条")
    rep.check(bank.learn("统帅贝利撒留的昵称是？", "错误答案") is False,
              "learn 不覆盖随包答案")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # 以 `-` 开头的一律当未知参数（`--help`、拼错的 flag），不能当素材路径
    if len(args) > 1 or any(a.startswith("-") for a in args):
        print("用法：tools/quiz_acceptance.py [素材目录]")
        return 2
    root = Path(args[0]) if args else DEFAULT_MATERIALS

    rep = _Report()
    found = index_materials(root)
    if not found:
        rep.skip("素材", f"{root} 不存在或没有素材 —— SKIP（dati/ 不入库）")
        rep.summary()
        return 0
    if not BANK_PATH.is_file():
        print(f"随包题库不存在：{BANK_PATH}（先做 Task 2）")
        return 1

    engine = RapidOcrEngine()
    with tempfile.TemporaryDirectory() as tmp:
        learned = Path(tmp) / "learned.json"
        bank = QuizBank(BANK_PATH, learned)
        bank.load()
        # 固定种子：随机兜底不联网、可复现；LLM 一律不接（验收不许发请求）
        solver = Solver(bank, None, rng=random.Random(20261024))
        _check_stills(found, engine, solver, rep)
        _check_videos(found, engine, rep, bank, learned)
    rep.summary()
    return 1 if rep.fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
