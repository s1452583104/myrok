import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date
from pathlib import Path

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog

from rok_assistant.infra.licensing import guard as guard_mod

MACHINE_CODE = "AAAA-BBBB-CCCC-DDDD-E"


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _StubGuard:
    """只实现 GUI 用到的三个方法，不碰磁盘。"""

    def __init__(self, kind, days_left=0, activate_ok=False):
        self._st = guard_mod.LicenseStatus(kind, None, days_left, MACHINE_CODE)
        self._activate_ok = activate_ok

    def status(self):
        return self._st

    def machine_code(self):
        return MACHINE_CODE

    def activate(self, text):
        return ((True, "激活成功") if self._activate_ok
                else (False, "激活码无效"))


class _FakeController(QObject):
    status_changed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    run_finished = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.config_loaded = True
        self.started = False

    def characters(self):
        return []

    def load_config(self):
        return True

    def reload_config(self):
        pass

    def start(self):
        self.started = True
        return True

    def stop(self):
        pass

    def snapshot(self, char_id):
        return None


@pytest.fixture
def window(qapp):
    from rok_assistant.gui.main_window import MainWindow
    def _make(ctrl=None):
        return MainWindow(controller=ctrl or _FakeController())
    return _make


# ---- 状态标签 ----

def test_trial_label_shows_days_left(monkeypatch, window):
    monkeypatch.setattr(guard_mod, "current_guard",
                        lambda: _StubGuard("trial", 12))
    w = window()
    assert w.license_label.text() == "试用剩余 12 天"


def test_expired_label(monkeypatch, window):
    monkeypatch.setattr(guard_mod, "current_guard", lambda: _StubGuard("expired"))
    w = window()
    assert w.license_label.text() == "试用已结束，请输入激活码"


def test_license_failure_does_not_break_window(monkeypatch, window):
    """授权读不出来也得能开窗——否则用户连报障都做不到。"""
    class _Boom:
        def status(self):
            raise RuntimeError("注册表炸了")
    monkeypatch.setattr(guard_mod, "current_guard", lambda: _Boom())
    w = window()
    assert w.license_label.text() == "授权状态未知"


# ---- Start 闸门 ----

def test_expired_start_does_not_start_controller(monkeypatch, window):
    from rok_assistant.gui.main_window import MainWindow
    monkeypatch.setattr(guard_mod, "current_guard", lambda: _StubGuard("expired"))
    monkeypatch.setattr(MainWindow, "_open_license_dialog", lambda self: None)
    ctrl = _FakeController()
    w = window(ctrl)
    w.start_btn.click()
    assert ctrl.started is False
    assert w.start_btn.isEnabled() is True     # 没切成运行态
    assert "试用已结束" in w.statusBar().currentMessage()


def test_trial_start_still_starts(monkeypatch, window):
    monkeypatch.setattr(guard_mod, "current_guard",
                        lambda: _StubGuard("trial", 12))
    ctrl = _FakeController()
    w = window(ctrl)
    w.start_btn.click()
    assert ctrl.started is True


def test_expired_start_opens_license_dialog(monkeypatch, window):
    from rok_assistant.gui.main_window import MainWindow
    opened = []
    monkeypatch.setattr(guard_mod, "current_guard", lambda: _StubGuard("expired"))
    monkeypatch.setattr(MainWindow, "_open_license_dialog",
                        lambda self: opened.append(True))
    # 必须绑到局部变量：`window().start_btn.click()` 里窗口是临时对象，
    # CPython 取完 start_btn 属性就回收了它，C++ 侧连同按钮一起删掉，
    # .click() 会抛「wrapped C/C++ object ... has been deleted」。
    w = window()
    w.start_btn.click()
    assert opened == [True]


def test_start_with_broken_license_guard_is_blocked_not_crashed(monkeypatch, window):
    """授权读不出来时点 Start：拦住并给出提示，**不能**让异常逃出槽。

    异常逃出 Qt 槽 → PyQt6 默认 qFatal → 整个进程 abort。同时这里必须
    fail closed：放行等于「让 status() 抛异常即可免授权」。
    """
    class _Boom:
        def status(self):
            raise RuntimeError("注册表炸了")

        def machine_code(self):
            return MACHINE_CODE

    monkeypatch.setattr(guard_mod, "current_guard", lambda: _Boom())
    ctrl = _FakeController()
    w = window(ctrl)
    w.start_btn.click()                        # 不抛
    assert ctrl.started is False
    assert w.license_label.text() == "授权状态未知"
    assert "授权状态未知" in w.statusBar().currentMessage()


# ---- 到期前 7 天提醒（spec §8.1）----

def test_should_warn_within_7_days():
    from rok_assistant.gui import main_window
    st = guard_mod.LicenseStatus("trial", date(2026, 11, 1), 7, MACHINE_CODE)
    assert main_window.should_warn(st, None) is True


def test_should_not_warn_with_more_than_7_days():
    from rok_assistant.gui import main_window
    st = guard_mod.LicenseStatus("trial", date(2026, 11, 1), 8, MACHINE_CODE)
    assert main_window.should_warn(st, None) is False


def test_should_not_warn_when_dismissed():
    from rok_assistant.gui import main_window
    st = guard_mod.LicenseStatus("trial", date(2026, 11, 1), 3, MACHINE_CODE)
    assert main_window.should_warn(st, main_window.warn_key(st)) is False


def test_warn_rearms_when_expiry_changes():
    """买了天数 → 到期日变了 → 重新提醒一次。

    否则用户「不再提醒」之后就再也收不到提醒，买完才发现快到期。
    """
    from rok_assistant.gui import main_window
    old = guard_mod.LicenseStatus("licensed", date(2026, 11, 1), 3, MACHINE_CODE)
    new = guard_mod.LicenseStatus("licensed", date(2026, 11, 5), 5, MACHINE_CODE)
    assert main_window.should_warn(new, main_window.warn_key(old)) is True


def test_permanent_and_expired_never_warn():
    from rok_assistant.gui import main_window
    assert main_window.should_warn(
        guard_mod.LicenseStatus("permanent", None, None, MACHINE_CODE),
        None) is False
    # 已到期不弹「即将到期」——那是 Start 闸门的事
    assert main_window.should_warn(
        guard_mod.LicenseStatus("expired", None, 0, MACHINE_CODE),
        None) is False


# ---- 对话框 ----

def test_dialog_shows_machine_code(qapp):
    from rok_assistant.gui.license_dialog import LicenseDialog
    dlg = LicenseDialog(_StubGuard("trial", 5))
    assert dlg.machine_code_edit.text() == MACHINE_CODE
    assert dlg.machine_code_edit.isReadOnly() is True


def test_dialog_reports_failure_without_closing(qapp):
    from rok_assistant.gui.license_dialog import LicenseDialog
    dlg = LicenseDialog(_StubGuard("expired"))
    dlg.code_edit.setPlainText("随便一串")
    dlg.activate_btn.click()
    assert dlg.result() != int(QDialog.DialogCode.Accepted)
    assert dlg.status_label.text() == "激活码无效"


def test_dialog_accepts_on_success(qapp):
    from rok_assistant.gui.license_dialog import LicenseDialog
    dlg = LicenseDialog(_StubGuard("expired", activate_ok=True))
    dlg.code_edit.setPlainText("码")
    dlg.activate_btn.click()
    assert dlg.result() == int(QDialog.DialogCode.Accepted)


def test_dialog_does_not_crash_when_guard_raises(qapp):
    """激活窗是授权出问题时**唯一**的自救入口：读不出状态要能开，激活抛了不能崩。

    异常逃出 Qt 槽 → PyQt6 默认 qFatal → 整个进程 abort。
    """
    from rok_assistant.gui.license_dialog import LicenseDialog

    class _Boom:
        def status(self):
            raise RuntimeError("注册表炸了")

        def machine_code(self):
            return MACHINE_CODE

        def activate(self, text):
            raise RuntimeError("写不进去")

    dlg = LicenseDialog(_Boom())               # 不抛
    assert "授权状态未知" in dlg.status_label.text()
    dlg.code_edit.setPlainText("随便一串")
    dlg.activate_btn.click()                   # 不抛
    assert "激活失败" in dlg.status_label.text()
    assert dlg.result() != int(QDialog.DialogCode.Accepted)


# ---- controller 的纵深防御 ----

def test_controller_start_blocked_when_expired(monkeypatch, tmp_path):
    from rok_assistant.gui.controller import GuiController
    monkeypatch.setattr(guard_mod, "current_guard", lambda: _StubGuard("expired"))
    errs = []
    c = GuiController(config_path=tmp_path / "nope.yaml")
    c.error_occurred.connect(errs.append)
    assert c.start() is False
    assert errs and "试用已结束" in errs[0]
