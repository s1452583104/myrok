"""2s 定时刷新的三件事：统计条、缩略图、以及不该做的事。

用户反馈点开始/结束卡顿。除了启停本身，2s 一次的定时器也在主线程上做
**全帧 JPEG 编码 + 解码 + 平滑缩放**：1920×1080 的帧按面积计价，号越多越
贵，而画面绝大多数时候根本没变。这里钉住「不重复画」与「文字模式不取帧」。
"""
import base64

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from rok_assistant.gui.main_window import MainWindow
from rok_assistant.infra.config import AppMode

Z = AppMode.ZHAIDUO

# 1×1 PNG。不用 QImage+QBuffer 现场生成：临时 QByteArray 被 GC 后 QBuffer
# 留悬垂指针，进程退出时随机 access violation（见 test_character_card.py）。
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg==")
_FRAME_A = _TINY_PNG
_FRAME_B = _TINY_PNG + b"\x00"          # 只求「字节不同」


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _C(QObject):
    status_changed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    run_finished = pyqtSignal(dict)

    def __init__(self, stats=None, frames=None, stats_after_stop=None):
        super().__init__()
        self._stats = stats or {}
        self._after = stats_after_stop
        self._frames = frames or {}
        self.snapshot_calls = 0
        self._stopped = False

    @property
    def config_loaded(self):
        return True

    def load_config(self):
        return True

    def characters(self, mode=AppMode.ZHAIDUO):
        return [{"instance_id": "inst0", "char_id": "boss",
                 "char_name": "车头", "role": "leader"}]

    def start(self, mode=Z):
        return True

    def stop(self):
        self._stopped = True

    def snapshot(self, char_id):
        self.snapshot_calls += 1
        return self._frames.get(char_id)

    def stats(self):
        if self._stopped and self._after is not None:
            return dict(self._after)
        return dict(self._stats)

    def card_view(self):
        # 真控制器从 config.yaml 读显示模式；替身固定图文。
        return "image"

    def set_card_view(self, mode):
        return True


def _count_thumb_writes(w, char_id):
    """把卡片的 set_thumbnail 包一层计数，返回调用列表。

    只包这一个实例的方法（实例属性遮蔽类方法），卡片真实行为照跑。
    """
    card = w._cards[char_id]
    seen = []
    orig = card.set_thumbnail

    def spy(data):
        seen.append(data)
        return orig(data)

    card.set_thumbnail = spy
    return seen


# ---------------------------------------------------------------- 统计条
def test_refresh_pushes_stats_to_the_page(qapp):
    w = MainWindow(_C(stats={"ok": 3, "failed": 1, "env": 0, "fills": 5,
                             "rounds": 4, "target": 10}))
    w._on_refresh()
    assert w._pages[Z].stat_ok.text() == "3/10"
    assert w._pages[Z].stat_failed.text() == "1"
    assert w._pages[Z].stat_fills.text() == "5"


def test_stop_refreshes_stats_one_last_time(qapp, wait_until):
    """停止后统计条立刻显示这一轮的战绩。

    停完不刷的话，最后那几个数字要等下一个 2s 周期——而定时器在空闲时
    已经不取帧了，用户点完停止盯着看的就是一份过期读数。
    """
    ctrl = _C(stats={"ok": 1, "failed": 0, "env": 0, "fills": 0,
                     "rounds": 1, "target": 10},
              stats_after_stop={"ok": 7, "failed": 0, "env": 0, "fills": 0,
                                "rounds": 7, "target": 10})
    w = MainWindow(ctrl)
    w._set_phase(MainWindow.RUNNING, Z)
    w._pages[Z].stop_btn.click()
    wait_until(lambda: w._phase == MainWindow.IDLE)
    assert w._pages[Z].stat_ok.text() == "7/10"


# ---------------------------------------------------------------- 取帧
def test_refresh_does_not_pull_frames_when_idle(qapp):
    """空闲时不取帧。

    未运行时协调器根本没有画面可给，每个周期白跑一趟 N 个模拟器。
    """
    ctrl = _C(frames={"boss": _FRAME_A})
    w = MainWindow(ctrl)
    w._on_refresh()
    assert ctrl.snapshot_calls == 0


def test_refresh_pulls_frames_while_running(qapp):
    ctrl = _C(frames={"boss": _FRAME_A})
    w = MainWindow(ctrl)
    w._set_phase(MainWindow.RUNNING, Z)
    w._on_refresh()
    assert ctrl.snapshot_calls == 1
    assert w._cards["boss"].thumbnail.pixmap().isNull() is False


def test_unchanged_frame_is_not_redrawn(qapp):
    """同一帧只画一次。

    取帧照旧（帧可能变），但**字节没变就不重画**：重画要走 QPixmap 解码 +
    平滑缩放，那才是主线程上真正的开销。
    """
    ctrl = _C(frames={"boss": _FRAME_A})
    w = MainWindow(ctrl)
    w._set_phase(MainWindow.RUNNING, Z)
    written = _count_thumb_writes(w, "boss")

    w._on_refresh()
    w._on_refresh()
    w._on_refresh()
    assert ctrl.snapshot_calls == 3          # 每轮都去问
    assert written == [_FRAME_A]             # 但只画了一次


def test_changed_frame_is_redrawn(qapp):
    ctrl = _C(frames={"boss": _FRAME_A})
    w = MainWindow(ctrl)
    w._set_phase(MainWindow.RUNNING, Z)
    written = _count_thumb_writes(w, "boss")

    w._on_refresh()
    ctrl._frames["boss"] = _FRAME_B
    w._on_refresh()
    assert written == [_FRAME_A, _FRAME_B]


def test_text_mode_does_not_pull_frames_at_all(qapp):
    """文字模式**连取帧都不做**。

    卡片自己会拦住不画（CharacterCard.set_thumbnail 有兜底），但帧是在
    协调器里编码 JPEG 过来的——不取，才真的省下那笔开销。
    """
    ctrl = _C(frames={"boss": _FRAME_A})
    w = MainWindow(ctrl)
    w._set_phase(MainWindow.RUNNING, Z)
    w._pages[Z].text_btn.click()          # 走用户点开关的真实路径

    w._on_refresh()
    assert ctrl.snapshot_calls == 0


def test_missing_frame_does_not_clear_the_thumbnail(qapp):
    """协调器这一轮没给帧（如正在切场景）时保留上一张，别闪成空白。"""
    ctrl = _C(frames={"boss": _FRAME_A})
    w = MainWindow(ctrl)
    w._set_phase(MainWindow.RUNNING, Z)
    w._on_refresh()
    assert w._cards["boss"].thumbnail.pixmap().isNull() is False

    ctrl._frames.clear()
    w._on_refresh()
    assert w._cards["boss"].thumbnail.pixmap().isNull() is False
