"""模式页的两块新零件：卡片区上方的统计条、页头的文字/图文分段开关。

与 test_mode_nav.py 分开：那边钉的是「按钮随状态推导」，这边钉的是展示。
"""
import pytest
from PyQt6.QtWidgets import QApplication

from rok_assistant.gui import theme
from rok_assistant.gui.mode_page import ModePage
from rok_assistant.infra.config import AppMode


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def page(qapp):
    return ModePage(AppMode.ZHAIDUO)


_STATS = {"ok": 3, "failed": 1, "env": 0, "rounds": 4, "fills": 5, "target": 10}


# ---------------------------------------------------------------- 统计条
def test_stats_bar_sits_above_the_cards(page):
    """统计条挂在**卡片页内部**，不是整页。

    挂在整页的话空态/未开放页头上也顶着一条全 0 的统计，等于告诉用户
    「这个还没做的模式战绩为 0」。
    """
    card_page = page.body.widget(ModePage.CARD)
    assert card_page.isAncestorOf(page.stats_bar)
    assert card_page.isAncestorOf(page.card_area)
    lay = card_page.layout()
    assert lay.indexOf(page.stats_bar) < lay.indexOf(page.card_area)


def test_stats_bar_is_compact(page):
    """「不要占据太多地方」是明确要求：一条横条，高度不超过两个标准间距。"""
    assert page.stats_bar.height() <= 2 * theme.SP_XL


def test_set_stats_renders_completed_over_target(page):
    """完成个数形如 完成个数/设置个数（用户原话）。"""
    page.set_stats(_STATS)
    assert page.stat_ok.text() == "3/10"


def test_set_stats_renders_failures_and_fills(page):
    page.set_stats(_STATS)
    assert page.stat_failed.text() == "1"
    assert page.stat_fills.text() == "5"


def test_zero_failure_is_not_red(page):
    """0 次失败是中性色。

    给 0 上红色等于让用户以为出了问题 —— 状态色只在语义成立时出现。
    """
    page.set_stats({**_STATS, "failed": 0, "env": 0})
    assert theme.ERROR not in page.stat_failed.styleSheet()
    assert theme.WARNING not in page.stat_env.styleSheet()

    page.set_stats({**_STATS, "failed": 2, "env": 3})
    assert theme.ERROR in page.stat_failed.styleSheet()
    assert theme.WARNING in page.stat_env.styleSheet()


def test_set_stats_tolerates_missing_keys(page):
    """启动中/未运行时读数可能只有一部分字段，缺字段按 0 显示而不是崩。"""
    page.set_stats({})
    assert page.stat_ok.text() == "0/0"
    assert page.stat_failed.text() == "0"


# ---------------------------------------------------------------- 分段开关
def test_segment_buttons_are_mutually_exclusive(page):
    page.text_btn.click()
    assert page.text_btn.isChecked() is True
    assert page.image_btn.isChecked() is False

    page.image_btn.click()
    assert page.image_btn.isChecked() is True
    assert page.text_btn.isChecked() is False


def test_clicking_a_segment_emits_its_mode(page):
    seen = []
    page.view_mode_changed.connect(seen.append)
    page.text_btn.click()
    page.image_btn.click()
    assert seen == ["text", "image"]


def test_reclicking_the_checked_segment_does_not_re_emit(page):
    """再点已选中项不重发信号。

    主窗口收到信号会去改写 config.yaml —— 重复点同一个按钮不该反复落盘。
    """
    seen = []
    page.view_mode_changed.connect(seen.append)
    page.text_btn.click()
    page.text_btn.click()
    assert seen == ["text"]


def test_set_view_mode_checks_without_emitting(page):
    """代码里设模式（启动时读配置）不触发信号。

    否则「读配置 → set_view_mode → 发信号 → 写配置」自己转一圈，用户没
    动过手，配置文件的时间戳却在变。
    """
    seen = []
    page.view_mode_changed.connect(seen.append)
    page.set_view_mode("text")
    assert seen == []
    assert page.text_btn.isChecked() is True
    assert page.image_btn.isChecked() is False
    assert page.view_mode() == "text"
