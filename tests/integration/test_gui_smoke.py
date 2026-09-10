import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeController(QObject):
    """MainWindow 注入替身：无信号时也能离屏构造、驱动按钮。"""
    status_changed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, chars=None):
        super().__init__()
        self._chars = chars if chars is not None else [
            {"instance_id": "inst0", "char_id": "boss",
             "char_name": "车头", "role": "leader"},
            {"instance_id": "inst1", "char_id": "worker",
             "char_name": "成员", "role": "member"},
        ]
        self.config_loaded = True
        self.started = False
        self.stopped = False
        self.snapshots: dict[str, bytes | None] = {}

    def load_config(self) -> bool:
        return self.config_loaded

    def reload_config(self) -> None:
        pass

    def characters(self):
        return list(self._chars)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def snapshot(self, char_id):
        return self.snapshots.get(char_id)


def test_main_window_can_be_created(qapp):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow(controller=FakeController())
    assert w.windowTitle() == "rok-assistant"

def test_main_window_default_controller_is_lazy(qapp, tmp_path):
    # 指向不存在的配置文件：构造不崩、不弹错误框（error_occurred 连接晚于建卡），
    # 只是建不出卡片并提示
    from rok_assistant.gui.main_window import MainWindow
    from rok_assistant.gui.controller import GuiController
    w = MainWindow(controller=GuiController(config_path=tmp_path / "nope.yaml"))
    assert w._controller.config_loaded is False
    assert w._cards == {}

def test_main_window_has_start_stop_buttons(qapp):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow(controller=FakeController())
    assert w.start_btn.text() == "Start"
    assert w.stop_btn.text() == "Stop"
    assert not w.stop_btn.isEnabled()   # 初始未运行

def test_cards_built_per_character(qapp):
    from rok_assistant.gui.main_window import MainWindow
    w = MainWindow(controller=FakeController())
    assert set(w._cards) == {"boss", "worker"}

def test_start_stop_buttons_drive_controller(qapp):
    from rok_assistant.gui.main_window import MainWindow
    fake = FakeController()
    w = MainWindow(controller=fake)
    w.start_btn.click()
    assert fake.started
    assert not w.start_btn.isEnabled()
    assert w.stop_btn.isEnabled()
    assert w.statusBar().currentMessage() == "运行中"
    w.stop_btn.click()
    assert fake.stopped
    assert w.start_btn.isEnabled()
    assert not w.stop_btn.isEnabled()
    assert w.statusBar().currentMessage() == "已停止"

def test_status_update_routes_to_card(qapp):
    from rok_assistant.gui.main_window import MainWindow
    fake = FakeController()
    w = MainWindow(controller=fake)
    fake.status_changed.emit({"char_id": "worker", "state": "WAIT_LAUNCH_EVENT"})
    assert w._cards["worker"].status_label.text() == "WAIT_LAUNCH_EVENT"

def test_refresh_button_rebuilds_cards(qapp):
    from rok_assistant.gui.main_window import MainWindow
    fake = FakeController()
    w = MainWindow(controller=fake)
    fake._chars.append({"instance_id": "inst2", "char_id": "c3",
                        "char_name": "三号", "role": "either"})
    w.refresh_btn.click()
    assert set(w._cards) == {"boss", "worker", "c3"}

def test_timer_pulls_snapshots_into_cards(qapp):
    import cv2
    import numpy as np
    from rok_assistant.gui.main_window import MainWindow
    fake = FakeController()
    ok, buf = cv2.imencode(".jpg", np.zeros((4, 4, 3), np.uint8))
    assert ok
    fake.snapshots["boss"] = buf.tobytes()
    w = MainWindow(controller=fake)
    w._on_refresh()   # 直接调用，避免依赖真实定时器时序
    assert not w._cards["boss"].thumbnail.pixmap().isNull()
