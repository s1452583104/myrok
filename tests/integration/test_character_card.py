import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app

def test_card_displays_name_and_role(qapp):
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="Hero", role="leader", status="waiting")
    assert "Hero" in card.title_label.text()
    assert "leader" in card.title_label.text()

def test_card_set_error_makes_red(qapp):
    from rok_assistant.gui.character_card import CharacterCard
    card = CharacterCard(name="M1", role="member", status="idle")
    card.set_error("something broke")
    assert "error" in card.status_label.text().lower() or card.error_state
