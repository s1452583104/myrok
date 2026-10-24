"""大模型兜底：OpenAI 兼容 /chat/completions，一次 POST，永不抛。

不引 requests / openai SDK：绿色包少一个依赖，而这里只有一次 POST。
"""
import http.client
import json

from rok_assistant.core.quiz.llm import LLMClient

OPTIONS = {"A": "考拉", "B": "狮子", "C": "大象", "D": "大熊猫"}


class _FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def read(self) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": self._content}}]}
        ).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _client(content: str, seen: list, **kw) -> LLMClient:
    def opener(req, timeout=None):
        seen.append((req, timeout))
        return _FakeResponse(content)
    return LLMClient(base_url="https://api.example.com/v1/", model="m1",
                     api_key="sk-test", opener=opener, **kw)


def test_choose_posts_to_chat_completions_with_the_question_and_options():
    seen = []
    letter = _client("A", seen).choose("2022年北京冬奥会的吉祥物？", OPTIONS)
    assert letter == "A"
    req, timeout = seen[0]
    assert req.full_url == "https://api.example.com/v1/chat/completions"
    assert req.get_header("Authorization") == "Bearer sk-test"
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "m1"
    user = body["messages"][-1]["content"]
    assert "2022年北京冬奥会的吉祥物？" in user
    assert "D. 大熊猫" in user
    assert timeout == 8.0


def test_choose_accepts_a_lowercase_letter_with_punctuation():
    assert _client("b。", []).choose("题", OPTIONS) == "B"


def test_letter_inside_an_english_word_is_ignored():
    """`The answer is B.` 以前会在前 16 字符里先扫到 answer 的 A。"""
    assert _client("The answer is B.", []).choose("题", OPTIONS) == "B"


def test_single_letter_reply_is_accepted_even_with_whitespace():
    assert _client("A", []).choose("题", OPTIONS) == "A"
    assert _client("  c  ", []).choose("题", OPTIONS) == "C"


def test_standalone_letter_next_to_cjk_is_accepted():
    assert _client("选项C", []).choose("题", OPTIONS) == "C"


def test_reply_without_any_letter_or_option_text_returns_none():
    assert _client("no letter here", []).choose("题", OPTIONS) is None


def test_reply_with_option_text_maps_to_its_letter():
    """模型有时不守规矩直接答内容：能唯一对上选项就认。"""
    assert _client("大象", []).choose("题", OPTIONS) == "C"


def test_reply_with_nothing_usable_returns_none():
    assert _client("我不知道", []).choose("题", OPTIONS) is None


def test_letter_outside_the_options_returns_none():
    assert _client("E", []).choose("题", {"A": "甲", "B": "乙",
                                          "C": "丙", "D": "丁"}) is None


def test_disabled_client_sends_nothing():
    seen = []
    client = _client("A", seen, enabled=False)
    assert client.choose("题", OPTIONS) is None
    assert seen == []


def test_empty_api_key_sends_nothing():
    """没填 Key 就别发匿名请求（会 401，还暴露一个空请求）。"""
    seen = []
    client = LLMClient(base_url="https://x/v1", model="m", api_key="",
                       opener=lambda *a, **k: seen.append(a))
    assert client.choose("题", OPTIONS) is None
    assert seen == []


def test_network_error_is_swallowed():
    def boom(req, timeout=None):
        raise OSError("connection reset")
    client = LLMClient(base_url="https://x/v1", model="m", api_key="k",
                       opener=boom)
    assert client.choose("题", OPTIONS) is None


def test_malformed_payload_is_swallowed():
    def opener(req, timeout=None):
        return _FakeResponse("")          # 空 content
    client = LLMClient(base_url="https://x/v1", model="m", api_key="k",
                       opener=opener)
    assert client.choose("题", OPTIONS) is None


def test_schemeless_base_url_is_swallowed_without_calling_the_opener():
    """配置里漏了 https://：Request() 构造就抛 ValueError，不能漏给调用方。"""
    seen = []
    client = LLMClient(base_url="api.example.com/v1", model="m", api_key="k",
                       opener=lambda *a, **kw: seen.append(a))
    assert client.choose("题", OPTIONS) is None
    assert seen == []


def test_non_string_content_is_swallowed():
    """OpenAI 兼容端点可能把 content 返回成 list/数字：不能 AttributeError。"""
    client = LLMClient(base_url="https://x/v1", model="m", api_key="k",
                       opener=lambda req, timeout=None: _FakeResponse(["A"]))
    assert client.choose("题", OPTIONS) is None


class _TruncatedResponse:
    def read(self) -> bytes:
        raise http.client.IncompleteRead(b"partial", 10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_incomplete_read_is_swallowed():
    """IncompleteRead 是 HTTPException，不是 OSError，也必须降级为 None。"""
    client = LLMClient(base_url="https://x/v1", model="m", api_key="k",
                       opener=lambda req, timeout=None: _TruncatedResponse())
    assert client.choose("题", OPTIONS) is None
