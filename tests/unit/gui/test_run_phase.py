"""开始/停止不再阻塞主线程：四个相位（空闲/启动中/运行中/停止中）。

用户反馈「点开始或结束时会卡顿好几秒」。卡的是启动预检（连模拟器 + 载 ONNX）
与停止时逐个 join worker 线程——两者都在主线程上跑。这里钉住两件事：
**点击当场返回**，以及**返回后界面已经切到对应相位**（否则用户看不出点了）。
"""
import time

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from rok_assistant.gui.main_window import MainWindow
from rok_assistant.infra.config import AppMode

Z = AppMode.ZHAIDUO


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _SlowController(QObject):
    """`start` / `stop` 要睡一会儿的替身，用来暴露「主线程被阻塞」。"""

    status_changed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    run_finished = pyqtSignal(dict)

    def __init__(self, start_delay=0.0, stop_delay=0.0, start_result=True):
        super().__init__()
        self.start_delay = start_delay
        self.stop_delay = stop_delay
        self.start_result = start_result
        self.started = False
        self.stopped = False
        self.start_calls = 0
        self.started_with = []

    @property
    def config_loaded(self):
        return True

    def load_config(self):
        return True

    def characters(self, mode=AppMode.ZHAIDUO):
        return [{"instance_id": "inst0", "char_id": "boss",
                 "char_name": "车头", "role": "leader"}]

    def start(self, mode=Z):
        self.start_calls += 1
        self.started_with.append(mode)
        time.sleep(self.start_delay)
        self.started = self.start_result
        return self.start_result

    def stop(self):
        self.stopped = True
        time.sleep(self.stop_delay)

    def snapshot(self, char_id):
        return None

    def stats(self):
        return {"ok": 0, "failed": 0, "env": 0, "rounds": 0, "fills": 0,
                "target": 0}

    def card_view(self):
        # 真控制器从 config.yaml 读显示模式；替身固定图文。
        return "image"

    def set_card_view(self, mode):
        return True


def _start_and_run(w, wait_until, ctrl, start_delay):
    """点开始并等到运行态（多数用例的公共前缀）。"""
    w._pages[Z].start_btn.click()
    wait_until(lambda: w._phase == MainWindow.RUNNING)


# ---------------------------------------------------------------- 启动
def test_start_does_not_block_the_main_thread(qapp, wait_until):
    ctrl = _SlowController(start_delay=0.5)
    w = MainWindow(ctrl)

    t0 = time.monotonic()
    w._pages[Z].start_btn.click()
    elapsed = time.monotonic() - t0

    # 慢启动 0.5s，点击必须当场返回。留 0.2s 余量给线程创建等开销。
    assert elapsed < 0.2, f"点击开始阻塞了主线程 {elapsed:.2f}s"
    assert w._phase == MainWindow.STARTING
    assert w.statusBar().currentMessage() == "正在启动…"
    # 启动中两个按钮都不可点：既防重复启动，也不能「停一个还没起来的东西」
    assert w._pages[Z].start_btn.isEnabled() is False
    assert w._pages[Z].stop_btn.isEnabled() is False
    assert w._pages[Z].start_btn.text() == "启动中…"      # 让等待看得见

    wait_until(lambda: w._phase == MainWindow.RUNNING)
    assert ctrl.started is True
    assert w.statusBar().currentMessage() == "运行中"
    assert w._pages[Z].start_btn.text() == "开始运行"
    assert w._pages[Z].stop_btn.isEnabled() is True


def test_failed_start_settles_back_to_idle(qapp, wait_until):
    """启动失败（预检被拒等）后回到空闲态，按钮不谎报「运行中」。"""
    ctrl = _SlowController(start_delay=0.05, start_result=False)
    w = MainWindow(ctrl)

    w._pages[Z].start_btn.click()
    wait_until(lambda: w._phase == MainWindow.IDLE)

    assert ctrl.started is False
    assert w._pages[Z].start_btn.isEnabled() is True      # 仍可再点
    assert w._pages[Z].stop_btn.isEnabled() is False
    assert w.statusBar().currentMessage() != "运行中"


def test_start_is_ignored_while_starting(qapp, wait_until):
    """启动中再点一次不重入。

    按钮已禁用，但 `_on_start` 可能被程序化调用（脚本、将来的快捷键）——
    真起了两份协调器会争同一个模拟器。
    """
    ctrl = _SlowController(start_delay=0.3)
    w = MainWindow(ctrl)

    w._pages[Z].start_btn.click()
    w._on_start(Z)                                        # 第二次
    wait_until(lambda: w._phase == MainWindow.RUNNING)
    assert ctrl.start_calls == 1


# ---------------------------------------------------------------- 停止
def test_stop_does_not_block_the_main_thread(qapp, wait_until):
    ctrl = _SlowController(stop_delay=0.5)
    w = MainWindow(ctrl)
    _start_and_run(w, wait_until, ctrl, ctrl.start_delay)

    t0 = time.monotonic()
    w._pages[Z].stop_btn.click()
    elapsed = time.monotonic() - t0

    assert elapsed < 0.2, f"点击停止阻塞了主线程 {elapsed:.2f}s"
    assert w._phase == MainWindow.STOPPING
    assert w.statusBar().currentMessage() == "正在停止…"
    assert w._pages[Z].start_btn.isEnabled() is False      # 停完之前不能再开
    assert w._pages[Z].stop_btn.isEnabled() is False
    assert w._pages[Z].stop_btn.text() == "停止中…"

    wait_until(lambda: w._phase == MainWindow.IDLE)
    assert ctrl.stopped is True
    assert w.statusBar().currentMessage() == "已停止"
    assert w._pages[Z].start_btn.isEnabled() is True
    assert w._pages[Z].stop_btn.text() == "停止"


def test_stop_is_ignored_when_not_running(qapp):
    """空闲时调 `_on_stop` 不该去动控制器（它此时没有协调器可停）。"""
    ctrl = _SlowController()
    w = MainWindow(ctrl)
    w._on_stop()
    assert ctrl.stopped is False
    assert w._phase == MainWindow.IDLE


# ---------------------------------------------------------------- 自然收工
def test_run_finished_resets_to_idle(qapp, wait_until):
    ctrl = _SlowController()
    w = MainWindow(ctrl)
    _start_and_run(w, wait_until, ctrl, ctrl.start_delay)

    ctrl.run_finished.emit({"reasons": {}})
    assert w._phase == MainWindow.IDLE
    assert w._pages[Z].start_btn.isEnabled() is True
    assert w._pages[Z].stop_btn.isEnabled() is False


def test_run_finished_during_stopping_does_not_steal_the_phase(qapp, wait_until):
    """收工信号与手动停止撞车时，收尾归停止那条路径。

    两条路径都写相位，谁最后写谁赢——停止中若被收工改成空闲，停止按钮
    会在 worker 还没 join 完时就亮起「可再启动」。
    """
    ctrl = _SlowController(stop_delay=0.3)
    w = MainWindow(ctrl)
    _start_and_run(w, wait_until, ctrl, ctrl.start_delay)

    w._pages[Z].stop_btn.click()
    ctrl.run_finished.emit({"reasons": {}})               # 撞车
    assert w._phase == MainWindow.STOPPING
    wait_until(lambda: w._phase == MainWindow.IDLE)
    assert w.statusBar().currentMessage() == "已停止"
