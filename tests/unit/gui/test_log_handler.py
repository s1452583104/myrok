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
