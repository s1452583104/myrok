"""文字模式 / 图文模式开关的接线：页头点一下，所有卡片跟着走，并落盘。

用**真** GuiController（配一个假协调器）而不是替身控制器：显示模式存在
config.yaml 里，走替身就把「读配置 / 写配置」这段真实路径测没了。
"""
import pytest
from PyQt6.QtWidgets import QApplication

from rok_assistant.gui.controller import GuiController
from rok_assistant.gui.main_window import MainWindow
from rok_assistant.infra.config import AppMode

Z = AppMode.ZHAIDUO

_CFG_HEAD = """
app:
  mumu_manager_path: M.exe
  adb_path: adb.exe
"""

_CFG_BODY = """
zhaiduo:
  instances:
    - id: inst0
      name: a
      adb_address: "127.0.0.1:5555"
      characters:
        - id: boss
          name: 车头
          role: leader
          target_levels:
          - 7
          march_preset: 1
          march_troop_types: [cavalry]
        - id: helper
          name: 填兵
          role: member
          target_levels:
          - 7
          march_preset: 1
          march_troop_types: [cavalry]
          fill_target_leaders:
            - instance: inst0
              name: 车头
"""


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeCoordinator:
    def __init__(self, *a, **kw):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def snapshot(self, char_id):
        return None

    def stats(self):
        return {}


def _write_config(tmp_path, card_view=None):
    head = _CFG_HEAD
    if card_view is not None:
        head = head.replace("app:\n", f"app:\n  card_view: {card_view}\n")
    path = tmp_path / "config.yaml"
    path.write_text(head + _CFG_BODY, encoding="utf-8")
    return path


def _window(tmp_path, card_view=None):
    path = _write_config(tmp_path, card_view)
    return MainWindow(GuiController(config_path=path,
                                    coordinator_factory=_FakeCoordinator)), path


# ---------------------------------------------------------------- 启动读取
def test_window_applies_the_saved_text_mode(qapp, tmp_path):
    w, _ = _window(tmp_path, card_view="text")
    assert w._pages[Z].view_mode() == "text"
    assert all(c.thumbnail.isHidden() for c in w._cards.values())


def test_window_defaults_to_image_mode(qapp, tmp_path):
    """配置里没写 card_view（老配置）时按图文走。"""
    w, _ = _window(tmp_path)
    assert w._pages[Z].view_mode() == "image"
    assert not any(c.thumbnail.isHidden() for c in w._cards.values())


# ---------------------------------------------------------------- 切换
def test_switching_to_text_hides_every_card(qapp, tmp_path):
    w, _ = _window(tmp_path)
    w._pages[Z].text_btn.click()
    assert w._pages[Z].view_mode() == "text"
    assert all(c.thumbnail.isHidden() for c in w._cards.values())


def test_switching_persists_to_config(qapp, tmp_path):
    """用户选的模式要落盘（写进 config.yaml），下次开窗还是它。"""
    w, path = _window(tmp_path)
    w._pages[Z].text_btn.click()
    text = path.read_text(encoding="utf-8")
    assert "card_view: text" in text
    assert "adb_path: adb.exe" in text        # 别的键没被动过

    w._pages[Z].image_btn.click()
    assert "card_view: image" in path.read_text(encoding="utf-8")


def test_switch_applies_to_every_page(qapp, tmp_path):
    """三个模式页共用一套显示模式（开关只在寨多多页头上，但它是全局观感）。"""
    w, _ = _window(tmp_path)
    w._pages[Z].text_btn.click()
    assert all(p.view_mode() == "text" for p in w._pages.values())


def test_persist_failure_keeps_the_switch_for_this_session(qapp, tmp_path,
                                                           monkeypatch):
    """写盘失败不拦切换：状态栏说明情况，本次会话照常生效。

    为了一个观感开关写不进去就把界面卡住，比不保存糟得多。
    """
    w, _ = _window(tmp_path)
    monkeypatch.setattr(w._controller, "set_card_view", lambda mode: False)

    w._pages[Z].text_btn.click()
    assert w._pages[Z].view_mode() == "text"              # 本次生效
    assert all(c.thumbnail.isHidden() for c in w._cards.values())
    assert "未能写入" in w.statusBar().currentMessage()


def test_switching_reports_success(qapp, tmp_path):
    w, _ = _window(tmp_path)
    w._pages[Z].text_btn.click()
    assert "文字模式" in w.statusBar().currentMessage()


# ---------------------------------------------------------------- 重建
def test_rebuilt_cards_inherit_the_current_mode(qapp, tmp_path):
    """点「刷新配置」重建卡片后，新卡仍是当前模式。

    新卡默认是图文模式，不显式同步的话用户切到文字模式、一刷新就全变回
    带截屏的高卡——而且没有任何提示。
    """
    w, _ = _window(tmp_path)
    w._pages[Z].text_btn.click()

    w._rebuild_cards()
    assert all(c.thumbnail.isHidden() for c in w._cards.values())
