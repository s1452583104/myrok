import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app

def test_log_panel_starts_empty(qapp):
    from rok_assistant.gui.log_panel import LogPanel
    p = LogPanel()
    assert p.toPlainText() == ""

def test_log_panel_appends_message(qapp):
    from rok_assistant.gui.log_panel import LogPanel
    p = LogPanel()
    p.append_message("hello")
    assert "hello" in p.toPlainText()

def test_log_panel_caps_lines(qapp):
    from rok_assistant.gui.log_panel import LogPanel
    p = LogPanel(max_lines=3)
    for i in range(10):
        p.append_message(f"line {i}")
    text = p.toPlainText()
    assert "line 0" not in text
    assert "line 9" in text
    assert len(text.splitlines()) == 3
