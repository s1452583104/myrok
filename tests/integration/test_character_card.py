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
