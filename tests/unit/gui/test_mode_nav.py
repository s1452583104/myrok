"""模式导航与 _sync_ui_state() 的三输入推导。

模式页是新组件，单开一个文件；卡片/日志那些既有契约仍在
tests/integration/test_gui_smoke.py 里。
"""
import pytest
from PyQt6.QtWidgets import QApplication

from rok_assistant.gui.main_window import MainWindow
from rok_assistant.infra.config import AppMode, IMPLEMENTED_MODES


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeController:
    """只满足 MainWindow 需要的那几个方法/信号，不碰运行时。"""

    def __init__(self, chars=None):
        from PyQt6.QtCore import QObject, pyqtSignal

        class _C(QObject):
            status_changed = pyqtSignal(dict)
            error_occurred = pyqtSignal(str)
            run_finished = pyqtSignal(dict)

        self._q = _C()
        self.status_changed = self._q.status_changed
        self.error_occurred = self._q.error_occurred
        self.run_finished = self._q.run_finished
        self._chars = chars or []
        self.started_with = []

    @property
    def config_loaded(self):
        return True

    def load_config(self):
        return True

    def reload_config(self):
        pass

    def characters(self):
        return list(self._chars)

    def start(self, mode=AppMode.ZHAIDUO):
        self.started_with.append(mode)
        return mode in IMPLEMENTED_MODES

    def stop(self):
        pass

    def snapshot(self, char_id):
        return None


def test_nav_lists_all_three_modes(qapp):
    w = MainWindow(_FakeController())
    labels = [w.mode_nav.item(i).text() for i in range(w.mode_nav.count())]
    assert labels == ["寨多多模式", "宝石模式", "答题模式"]
    assert w.mode_nav.currentRow() == 0        # 固定开在寨多多


def test_each_page_owns_its_own_buttons(qapp):
    w = MainWindow(_FakeController())
    for mode, page in w._pages.items():
        assert page.mode is mode
        assert page.start_btn is not None and page.stop_btn is not None
    # 开始/停止不再挂在 MainWindow 上（spec §6 的契约变更）
    assert not hasattr(w, "start_btn")
    assert not hasattr(w, "stop_btn")


def test_unimplemented_modes_start_disabled_and_show_placeholder(qapp):
    w = MainWindow(_FakeController())
    for mode in (AppMode.GEM, AppMode.QUIZ):
        assert not w._pages[mode].start_btn.isEnabled()
        assert w._pages[mode].body.currentIndex() == 2   # 占位页
    assert w._pages[AppMode.ZHAIDUO].start_btn.isEnabled()


def test_running_locks_nav_and_only_that_pages_stop(qapp):
    w = MainWindow(_FakeController())
    w._running_mode = AppMode.ZHAIDUO
    w._sync_ui_state()
    assert not w.mode_nav.isEnabled()                          # 运行中锁导航
    assert not w._pages[AppMode.ZHAIDUO].start_btn.isEnabled()
    assert w._pages[AppMode.ZHAIDUO].stop_btn.isEnabled()
    assert not w._pages[AppMode.GEM].stop_btn.isEnabled()


def test_stopping_unlocks_everything(qapp):
    w = MainWindow(_FakeController())
    w._running_mode = AppMode.ZHAIDUO
    w._sync_ui_state()
    w._running_mode = None
    w._sync_ui_state()
    assert w.mode_nav.isEnabled()
    assert w._pages[AppMode.ZHAIDUO].start_btn.isEnabled()
    assert not w._pages[AppMode.ZHAIDUO].stop_btn.isEnabled()


def test_start_passes_this_pages_mode_to_controller(qapp):
    c = _FakeController()
    w = MainWindow(c)
    w._pages[AppMode.ZHAIDUO].start_btn.click()
    assert c.started_with == [AppMode.ZHAIDUO]
