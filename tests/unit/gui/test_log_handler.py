from rok_assistant.gui.log_handler import char_id_from_thread_name


def test_parses_worker_thread_name():
    # runner.py:117 的命名格式
    assert char_id_from_thread_name("worker:mumu0:如愿") == "如愿"


def test_parses_char_id_containing_colon():
    """char_id 里出现冒号时，只切前两段，剩下的整体作为 id。"""
    assert char_id_from_thread_name("worker:mumu0:boss:2") == "boss:2"


def test_main_thread_returns_empty():
    assert char_id_from_thread_name("MainThread") == ""


def test_non_worker_thread_returns_empty():
    assert char_id_from_thread_name("Thread-3") == ""


def test_malformed_worker_name_returns_empty():
    assert char_id_from_thread_name("worker:") == ""
    assert char_id_from_thread_name("worker") == ""


import logging

from PyQt6.QtWidgets import QApplication
import pytest


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_handler_emits_char_id_and_text(qapp):
    from rok_assistant.gui.log_handler import QtLogHandler
    h = QtLogHandler()
    received = []
    h.record_emitted.connect(lambda cid, text: received.append((cid, text)))
    rec = logging.LogRecord("rok_assistant.workers.runner", logging.INFO,
                            __file__, 1, "hello %s", ("world",), None)
    h.emit(rec)
    assert len(received) == 1
    cid, text = received[0]
    assert cid == ""                     # 主线程 -> 空串，由调用方转状态栏
    assert "hello world" in text


def test_handler_uses_thread_name_for_attribution(qapp):
    """在名为 worker:<inst>:<char> 的线程里发日志，归属应解析到该角色。"""
    import threading
    from rok_assistant.gui.log_handler import QtLogHandler
    h = QtLogHandler()
    received = []
    h.record_emitted.connect(lambda cid, text: received.append((cid, text)))
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)

    t = threading.Thread(target=lambda: h.emit(rec), name="worker:mumu1:阑珊")
    t.start()
    t.join()
    # worker 线程 emit -> Qt 排队到主线程；不跑事件循环就永远收不到。
    # （brief 原文缺这一句，见 task-2-report.md 的偏差说明）
    qapp.processEvents()
    assert received[0][0] == "阑珊"
