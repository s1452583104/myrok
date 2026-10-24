"""大模型兜底：OpenAI 兼容的 /chat/completions，一次 POST。

**永不抛**：网络错、超时、返回体不合规一律返回 None，由 `Solver` 退到
随机。答题线程上抛异常会把一次「这题不会」升级成 WorkerRunner 的
连续失败（见 Global Constraints）。

不引 requests / openai SDK：只有一次 POST，urllib 够用；绿色包里少一个
依赖就少一类装不上的环境。
"""
from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Mapping

from ...infra.logger import get_logger

logger = get_logger(__name__)

_SYSTEM = ("你是《万国觉醒》答题活动的答题器。只输出一个选项字母"
           "（A、B、C 或 D），不要解释，不要输出其他任何字符。")
_MAX_TOKENS = 8
# 独立的选项字母：前后都不能紧挨着英文字母，否则 `answer` 里的 a 会被当成答案
_LETTER_RE = re.compile(r"(?<![A-Za-z])([A-Da-d])(?![A-Za-z])")


class LLMClient:
    def __init__(self, *, base_url: str, model: str, api_key: str,
                 timeout_s: float = 8.0, enabled: bool = True, opener=None):
        self._base_url = (base_url or "").rstrip("/")
        self._model = model or ""
        self._api_key = api_key or ""
        self._timeout = float(timeout_s)
        self._enabled = bool(enabled)
        # opener 注入点：单测用假 opener，生产用 urllib.request.urlopen
        self._opener = opener if opener is not None else urllib.request.urlopen

    def choose(self, question: str, options: Mapping[str, str]) -> str | None:
        """让模型从 options 里选一个字母；任何问题都返回 None。"""
        if not (self._enabled and self._api_key and self._base_url and self._model):
            return None
        if not options:
            return None
        lines = [f"{letter}. {text}" for letter, text in sorted(options.items())]
        body = {
            "model": self._model,
            "temperature": 0,
            "max_tokens": _MAX_TOKENS,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user",
                 "content": f"题目：{question}\n" + "\n".join(lines)},
            ],
        }
        try:
            req = urllib.request.Request(
                self._base_url + "/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self._api_key}"},
                method="POST")
            with self._opener(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            letter = _extract_letter(content, options)
        except Exception as exc:  # noqa: BLE001 — 永不抛的边界：任何失败都退到随机
            # 请求构造（schemeless URL 的 ValueError）、传输（OSError/
            # IncompleteRead）、JSON 解析、返回体形状（KeyError/TypeError）、
            # 以及 content 不是字符串（AttributeError）全部在这里降级。
            logger.warning("[答题] 大模型兜底失败（本题退到随机）：%s", exc)
            return None
        if letter is None:
            logger.warning("[答题] 大模型回答无法映射到选项：%r", content)
        return letter


def _extract_letter(content: str, options: Mapping[str, str]) -> str | None:
    """从模型答复里取选项字母。

    1. 整段就是一个字母（`A` / ` c `）→ 直接取；
    2. 否则取第一个**独立**的 A–D（前后都不是英文字母）：`The answer is B.`
       不能再把 answer 的 a 当成 A；
    3. 没有字母，再退到「答复里唯一包含的选项文本」；
    4. 都没有 → None。
    """
    text = (content or "").strip()
    if len(text) == 1 and text.upper() in options:
        return text.upper()
    for match in _LETTER_RE.finditer(text):
        letter = match.group(1).upper()
        if letter in options:
            return letter
    hits = [letter for letter, opt in options.items()
            if opt and opt in text]
    return hits[0] if len(hits) == 1 else None
