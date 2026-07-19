import re
from rok_assistant.core.handle_source import Win32HandleSource

def test_window_title_regex_matches(monkeypatch):
    fake_hwnd_by_title = {1234: "MuMuPlayer-1 - 482", 5678: "MuMuPlayer-2 - 482"}
    monkeypatch.setattr(
        Win32HandleSource, "_find_window_by_title",
        lambda self, pattern: next(h for h, t in fake_hwnd_by_title.items()
                                    if re.search(pattern, t))
    )
    src = Win32HandleSource(window_title_pattern="MuMuPlayer-1.*")
    assert src._resolve_hwnd() == 1234

def test_window_title_regex_no_match(monkeypatch):
    monkeypatch.setattr(
        Win32HandleSource, "_find_window_by_title", lambda self, pattern: None
    )
    src = Win32HandleSource(window_title_pattern="nonexistent.*")
    assert src._resolve_hwnd() is None

def test_is_alive_false_when_no_hwnd(monkeypatch):
    monkeypatch.setattr(Win32HandleSource, "_resolve_hwnd", lambda self: None)
    src = Win32HandleSource(window_title_pattern="x")
    assert src.is_alive() is False
