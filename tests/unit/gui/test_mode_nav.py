"""模式导航与 _sync_ui_state() 的三输入推导。

模式页是新组件，单开一个文件；卡片/日志那些既有契约仍在
tests/integration/test_gui_smoke.py 里。
"""
import pytest
from PyQt6.QtWidgets import QApplication

from rok_assistant.gui.main_window import MainWindow
from rok_assistant.gui.mode_page import ModePage
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

    def characters(self, mode=AppMode.ZHAIDUO):
        return list(self._chars)

    def start(self, mode=AppMode.ZHAIDUO):
        self.started_with.append(mode)
        return mode in IMPLEMENTED_MODES

    def stop(self):
        pass

    def snapshot(self, char_id):
        return None

    def stats(self):
        # 真控制器一定有这个方法（界面统计条每 2s 读一次）。替身缺了它，
        # 定时器一响就是在 Qt 槽里抛 AttributeError —— PyQt6 直接 abort 进程。
        return {}

    def card_view(self):
        # 真控制器从 config.yaml 读显示模式；替身固定图文。
        return "image"

    def set_card_view(self, mode):
        return True


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


def test_quiz_page_is_open(qapp):
    """答题模式已进 IMPLEMENTED_MODES：按钮可点、不显示「开发中」占位页。

    与 test_gem_page_is_open 同形。锁着的模式是 `ModePage.LOCKED`（索引 2），
    开放的模式在没角色时落到 `EMPTY`（索引 1）。断言「不是 LOCKED」而不是
    「等于 EMPTY」：后者会把「有没有卡」这个无关变量焊进这条用例。
    """
    w = MainWindow(_FakeController())
    page = w._pages[AppMode.QUIZ]
    assert page.implemented
    assert page.start_btn.isEnabled()
    assert page.body.currentIndex() != ModePage.LOCKED


def test_gem_page_is_open(qapp):
    """宝石模式进入 IMPLEMENTED_MODES：按钮可点、不显示「开发中」占位页。

    锁着的模式是 `ModePage.LOCKED`（索引 2）；开放的模式在没角色时落到
    `EMPTY`（索引 1）。断言用「不是 LOCKED」而不是「等于 EMPTY」——
    后者会把「有没有卡」这个无关变量也焊进这条用例。
    """
    w = MainWindow(_FakeController())
    page = w._pages[AppMode.GEM]
    assert page.implemented
    assert page.start_btn.isEnabled()
    assert page.body.currentIndex() != ModePage.LOCKED


def test_running_locks_nav_and_only_that_pages_stop(qapp):
    w = MainWindow(_FakeController())
    # 2026-10-16 起相位是唯一状态源（异步启停引入「启动中/停止中」中间态），
    # 直接戳 `_running_mode` 只会新增一个没人读的属性，断言会静默变空测。
    w._set_phase(MainWindow.RUNNING, AppMode.ZHAIDUO)
    assert not w.mode_nav.isEnabled()                          # 运行中锁导航
    assert not w._pages[AppMode.ZHAIDUO].start_btn.isEnabled()
    assert w._pages[AppMode.ZHAIDUO].stop_btn.isEnabled()
    assert not w._pages[AppMode.GEM].stop_btn.isEnabled()


def test_stopping_unlocks_everything(qapp):
    w = MainWindow(_FakeController())
    w._set_phase(MainWindow.RUNNING, AppMode.ZHAIDUO)
    assert not w.mode_nav.isEnabled()
    w._set_phase(MainWindow.IDLE)
    assert w.mode_nav.isEnabled()
    assert w._pages[AppMode.ZHAIDUO].start_btn.isEnabled()
    assert not w._pages[AppMode.ZHAIDUO].stop_btn.isEnabled()


def test_start_passes_this_pages_mode_to_controller(qapp, wait_until):
    c = _FakeController()
    w = MainWindow(c)
    w._pages[AppMode.ZHAIDUO].start_btn.click()
    # 启动走后台线程：要转事件循环等结果回来（点击当场返回是刻意的）
    wait_until(lambda: w._phase == MainWindow.RUNNING)
    assert c.started_with == [AppMode.ZHAIDUO]


class _PerModeController(_FakeController):
    """按模式给不同角色清单的替身。"""

    def __init__(self):
        super().__init__(chars=[])
        self._by_mode = {
            AppMode.ZHAIDUO: [{"instance_id": "mumu0", "char_id": "boss",
                               "char_name": "车头", "role": "leader"}],
            AppMode.GEM: [{"instance_id": "mumu1", "char_id": "g0",
                           "char_name": "采集号", "role": ""}],
            AppMode.QUIZ: [{"instance_id": "mumu0", "char_id": "q0",
                            "char_name": "答题号", "role": "quiz"}],
        }

    def characters(self, mode=AppMode.ZHAIDUO):
        return list(self._by_mode.get(mode, []))


def test_gem_cards_land_on_the_gem_page(qapp):
    """切到宝石页建卡：卡在宝石页的布局里，不在寨多多页。"""
    w = MainWindow(_PerModeController())
    assert set(w._cards_by_mode[AppMode.ZHAIDUO]) == {"boss"}

    w.mode_nav.setCurrentRow(list(AppMode).index(AppMode.GEM))
    gem_page = w._pages[AppMode.GEM]
    assert gem_page.card_layout.count() == 1
    assert set(w._cards_by_mode[AppMode.GEM]) == {"g0"}
    # 寨多多那页的卡还在自己那儿，没被搬走也没被清掉
    assert w._pages[AppMode.ZHAIDUO].card_layout.count() == 1
    assert set(w._cards_by_mode[AppMode.ZHAIDUO]) == {"boss"}


def test_quiz_cards_land_on_the_quiz_page(qapp):
    """切到答题页建卡：卡在答题页，寨多多/宝石两页的卡不受影响。"""
    w = MainWindow(_PerModeController())
    w.mode_nav.setCurrentRow(list(AppMode).index(AppMode.GEM))
    w.mode_nav.setCurrentRow(list(AppMode).index(AppMode.QUIZ))
    quiz_page = w._pages[AppMode.QUIZ]
    assert quiz_page.card_layout.count() == 1
    assert set(w._cards_by_mode[AppMode.QUIZ]) == {"q0"}
    assert set(w._cards_by_mode[AppMode.GEM]) == {"g0"}
    assert set(w._cards_by_mode[AppMode.ZHAIDUO]) == {"boss"}


def test_current_cards_alias_follows_the_selected_mode(qapp):
    """`w._cards` 指向当前选中模式的卡册——既有断言全按扁平键用它。"""
    w = MainWindow(_PerModeController())
    assert set(w._cards) == {"boss"}
    w.mode_nav.setCurrentRow(list(AppMode).index(AppMode.GEM))
    assert set(w._cards) == {"g0"}


def test_page_state_uses_its_own_card_count(qapp):
    """`_sync_ui_state` 的「有没有卡」判据必须是**本页**的卡数，不是当前卡册。

    判别点：建完寨多多的卡之后（`_card_mode` 指向寨多多），宝石页一张卡都
    没有，**不能**因为「当前卡册非空」就显示卡片区——那是把本页的空态
    判成了别页的状态。
    """
    w = MainWindow(_PerModeController())
    assert w._pages[AppMode.ZHAIDUO].body.currentIndex() == ModePage.CARD
    # 宝石页此刻还没建过卡：落在空态，而不是顶着寨多多的卡
    assert w._pages[AppMode.GEM].body.currentIndex() == ModePage.EMPTY
    # 答题页此刻还没建过卡：同样是空态，与本页卡数一致，不是「开发中」
    assert w._pages[AppMode.QUIZ].body.currentIndex() == ModePage.EMPTY


def test_log_lines_route_to_the_card_that_owns_the_char_id(qapp):
    """角色 id 撞车时，日志要投给真的拥有它的那张卡。

    宝石与寨子的角色 id 由用户各自起名，两边都叫 c0 是可能的。
    """
    w = MainWindow(_PerModeController())
    # 先把宝石页也建出来（__init__ 只建了寨多多那页），否则下面
    # `_cards_by_mode[GEM]["g0"]` 会 KeyError。
    w.mode_nav.setCurrentRow(list(AppMode).index(AppMode.GEM))
    assert set(w._cards_by_mode[AppMode.GEM]) == {"g0"}
    w._set_phase(MainWindow.RUNNING, AppMode.GEM)
    w._on_log_line("boss", "寨子的日志")
    assert "寨子的日志" in w._cards_by_mode[AppMode.ZHAIDUO]["boss"].log_view.toPlainText()
    assert "寨子的日志" not in w._cards_by_mode[AppMode.GEM]["g0"].log_view.toPlainText()


def test_switching_away_and_back_preserves_the_logs(qapp):
    """切走再切回，原模式的卡与日志必须原样还在。

    `_rebuild_cards` 造的是**全新**的 CharacterCard（日志控件是空的），
    所以切页不能无条件重建——否则用户跑完一轮切去看别的模式再切回来，
    寨多多的日志就没了。
    """
    w = MainWindow(_PerModeController())
    w._on_log_line("boss", "寨子的日志")
    assert "寨子的日志" in \
        w._cards_by_mode[AppMode.ZHAIDUO]["boss"].log_view.toPlainText()

    gem_row = list(AppMode).index(AppMode.GEM)
    zhaiduo_row = list(AppMode).index(AppMode.ZHAIDUO)
    w.mode_nav.setCurrentRow(gem_row)
    w.mode_nav.setCurrentRow(zhaiduo_row)

    assert "寨子的日志" in \
        w._cards_by_mode[AppMode.ZHAIDUO]["boss"].log_view.toPlainText()
    assert w._pages[AppMode.ZHAIDUO].card_layout.count() == 1
    # 别名跟着选中页回去
    assert set(w._cards) == {"boss"}
