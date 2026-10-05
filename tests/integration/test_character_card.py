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
