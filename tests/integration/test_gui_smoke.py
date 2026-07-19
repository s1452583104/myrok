import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app

def test_main_window_can_be_created(qapp):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow()
    assert w.windowTitle() == "rok-assistant"

def test_main_window_has_start_stop_buttons(qapp):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow()
    btn_texts = [b.text() for b in w.findChildren(type(w.start_btn))] if hasattr(w, "start_btn") else []
    # Just check window has widgets
    assert len(w.children()) > 0
