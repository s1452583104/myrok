"""题库：随包只读权威库 + 运行时学习库。

**两个文件**：
  * 随包题库 `templates/quiz/quiz_bank.json`（只读，1076 条）
  * 学习结果 `user_dir()/quiz/learned.json`（可写，运行时新增/修正）

**合并规则**（防一次颜色误判污染权威答案）：
  * 随包条目权威：同题以随包答案为准，学习结果不得覆盖
  * 学习条目之间可以互相修正（后学覆盖先学）
  * 落盘用「临时文件 + os.replace」：崩溃不丢题、不产生半截文件
"""
from __future__ import annotations

import difflib
import json
import os
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from ...infra.logger import get_logger

logger = get_logger(__name__)

_QNO_RE = re.compile(r"^q\s*\d+\s*[.．、:：]?\s*", re.I)
# 标点/空白/装饰符：`\W` 在 str 模式下是 Unicode 感知的，CJK 与数字都保留
_STRIP_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize(text: str) -> str:
    """NFKC → 去题号前缀 → 去标点空白 → 小写。

    **数字必须保留**：`24小时` 与 `48小时` 不能归一成同一个值。
    """
    t = unicodedata.normalize("NFKC", text or "").strip()
    t = _QNO_RE.sub("", t)
    return _STRIP_RE.sub("", t).lower()


def similarity(a: str, b: str) -> float:
    """两个**已归一化**字符串的相似度 ∈ [0, 1]。

    `solver.py` 也用它把题库答案对齐到屏幕上的选项文本（OCR 会把
    `不败的复兴者` 读成 `不的复兴者`），所以是公开函数。
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    if a in b or b in a:
        # 互含子串时按长度比打折：短题被长题整个包含不等于同一道题
        return min(len(a), len(b)) / max(len(a), len(b))
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True)
class BankHit:
    answer: str
    source: str        # "exact" | "fuzzy"
    score: float


class QuizBank:
    def __init__(self, shipped_path: Path, learned_path: Path):
        self._shipped_path = Path(shipped_path)
        self._learned_path = Path(learned_path)
        self._shipped: dict[str, str] = {}
        self._learned: dict[str, tuple[str, str]] = {}
        self._loaded = False
        # 一个进程内所有答题线程共享同一个 bank；所有读写都在此锁内（RLock 便于嵌套）。
        self._lock = threading.RLock()

    # ---- 读 ----

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._shipped) + len(self._learned)

    def load(self) -> None:
        with self._lock:
            shipped: dict[str, str] = {}
            for entry in self._read_list(self._shipped_path):
                key = normalize(entry["q"])
                if key:
                    shipped.setdefault(key, entry["a"].strip())
            learned: dict[str, tuple[str, str]] = {}
            for entry in self._read_list(self._learned_path):
                key = normalize(entry["q"])
                if key:
                    learned[key] = (entry["q"].strip(), entry["a"].strip())
            self._shipped = shipped
            self._learned = learned
            self._loaded = True

    @staticmethod
    def _read_list(path: Path) -> list[dict]:
        """读 JSON 数组；文件缺失或损坏都**不抛**（答题不能被题库拖挂）。"""
        if not Path(path).is_file():
            return []
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("[题库] 读不了 %s：%s", path, exc)
            return []
        if not isinstance(data, list):
            logger.warning("[题库] %s 不是 JSON 数组", path)
            return []
        return [e for e in data
                if isinstance(e, dict)
                and isinstance(e.get("q"), str) and e["q"].strip()
                and isinstance(e.get("a"), str) and e["a"].strip()]

    def lookup(self, question: str, threshold: float = 0.72) -> BankHit | None:
        if not self._loaded:
            self.load()
        key = normalize(question)
        if not key:
            return None
        # 快照后再迭代：learn() 可能在另一线程增长 self._learned。
        # self._shipped 只由 load() 整体替换、从不原地修改，取引用即可。
        with self._lock:
            shipped = self._shipped
            learned = dict(self._learned)
        if key in shipped:
            return BankHit(shipped[key], "exact", 1.0)
        if key in learned:
            return BankHit(learned[key][1], "exact", 1.0)

        best: BankHit | None = None
        for table in (shipped, {k: v[1] for k, v in learned.items()}):
            for other, answer in table.items():
                score = similarity(key, other)
                if best is None or score > best.score:
                    best = BankHit(answer, "fuzzy", score)
        if best is not None and best.score >= threshold:
            return best
        return None

    # ---- 写 ----

    def learn(self, question: str, answer: str) -> bool:
        """把「画面判定出来的正确答案」写进学习库。

        返回 True 表示内存里的答案变了（随包条目、无变化、空题/空答返回 False）；
        写盘失败仍返回 True——本次会话内生效，只是丢了持久化。
        """
        with self._lock:
            if not self._loaded:
                self.load()
            key = normalize(question)
            answer = (answer or "").strip()
            if not key or not answer:
                return False
            if key in self._shipped:
                logger.info("[题库] 随包条目权威，忽略学习结果：%s", question)
                return False
            prev = self._learned.get(key)
            if prev is not None and normalize(prev[1]) == normalize(answer):
                return False
            self._learned[key] = (question.strip(), answer)
            self._write_learned()
            return True

    def _write_learned(self) -> None:
        """调用方须持有 self._lock：取快照 + 落盘是一个整体。"""
        rows = [{"q": q, "a": a, "source": "learned"}
                for q, a in self._learned.values()]
        # 每次写用唯一临时名：即使多个 bank 实例指向同一学习文件也不互相踩。
        tmp = self._learned_path.with_name(
            f"{self._learned_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            self._learned_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")
            os.replace(tmp, self._learned_path)
        except OSError as exc:
            logger.warning("[题库] 学习结果写入失败（本次会话内仍生效）：%s", exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
