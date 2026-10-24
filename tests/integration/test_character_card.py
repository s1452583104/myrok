import base64
import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app

def test_card_displays_name_and_role_in_chinese(qapp):
    """配置页写「车头」，主界面却写「leader」是同一个人看到两个词
    （2026-10-05 用户反馈）。"""
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="Hero", role="leader", status="idle")
    assert "Hero" in card.title_label.text()
    assert "车头" in card.title_label.text()
    assert "leader" not in card.title_label.text()


def test_card_status_is_chinese_but_unknown_falls_back(qapp):
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="M1", role="member", status="WAIT_MEMBERS")
    assert card.status_label.text() == "等待成员填兵"
    card.set_status("SOME_NEW_STATE")     # 状态机新增状态：显示原文而不是空白
    assert card.status_label.text() == "SOME_NEW_STATE"

def test_card_set_error_makes_red(qapp):
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="M1", role="member", status="idle")
    card.set_error("something broke")
    assert "error" in card.status_label.text().lower() or card.error_state


def test_card_has_log_view_and_appends(qapp):
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="Hero", role="leader", status="idle")
    card.append_log("12:00:01 发起集结")
    card.append_log("12:03:10 已回城")
    text = card.log_view.toPlainText()
    assert "发起集结" in text and "已回城" in text
    assert card.log_view.isReadOnly()


def test_card_hides_thumbnail_in_text_mode(qapp):
    """文字模式不展示模拟器截屏，且卡片变矮 —— 省下的高度还给一屏更多卡片。"""
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="Hero", role="leader", status="idle")
    tall = card.height()

    card.set_view_mode("text")
    # 用 isHidden() 而不是 isVisible()：卡片没 show() 过时 isVisible() 恒为
    # False，两种模式下都是 False，那条断言等于没写。
    assert card.thumbnail.isHidden() is True
    assert card.height() < tall

    card.set_view_mode("image")
    assert card.thumbnail.isHidden() is False
    assert card.height() == tall


def test_card_keeps_log_and_status_in_text_mode(qapp):
    """文字模式只是不画截屏，状态与日志照常 —— 它换的是取景方式，不是信息量。"""
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="Hero", role="leader", status="idle")
    card.set_view_mode("text")
    card.set_status("SEARCH_FORTRESS")
    card.append_log("12:00:01 发起集结")
    assert card.status_label.text() == "搜索城寨"
    assert "发起集结" in card.log_view.toPlainText()


def test_set_thumbnail_is_a_noop_in_text_mode(qapp):
    """文字模式下收到帧也不能把它画出来。

    取帧的短路在主窗口那侧（文字模式根本不调 snapshot），这里兜一道：
    两条路径任一漏了，用户都会在文字模式里看到一张不该出现的截屏。
    """
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="Hero", role="leader", status="idle")
    card.set_view_mode("text")
    card.set_thumbnail(_tiny_png())
    assert card.thumbnail.pixmap().isNull()


# 1×1 PNG。**不用 QImage + QBuffer 现场生成**：`QBuffer(QByteArray())` 里的
# QByteArray 是临时对象，构造完就被 GC，QBuffer 留下悬垂指针，进程在退出时
# 随机 access violation（实测 3/3 复现，而用例本身全绿 —— 最难查的那类崩）。
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg==")


def _tiny_png() -> bytes:
    return _TINY_PNG


def test_card_log_view_is_ring_buffered(qapp):
    """只保留最近 200 行，防止长跑把内存吃光。"""
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="Hero", role="leader", status="idle")
    for i in range(250):
        card.append_log(f"line {i}")
    text = card.log_view.toPlainText()
    assert "line 249" in text
    assert "line 0\n" not in text
    assert card.log_view.blockCount() <= 200
