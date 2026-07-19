from rok_assistant.coordination.failure_handler import FailureHandler, RecoveryAction


def test_handle_recognition_failure_first_two_retries():
    h = FailureHandler(max_retries=3)
    a = h.handle("recognition_failed", {"worker_id": "w1", "scene": "search"})
    assert a == RecoveryAction.RETRY


def test_handle_recognition_failure_after_max():
    h = FailureHandler(max_retries=3)
    h.handle("recognition_failed", {"worker_id": "w1", "scene": "search"})
    h.handle("recognition_failed", {"worker_id": "w1", "scene": "search"})
    a = h.handle("recognition_failed", {"worker_id": "w1", "scene": "search"})
    assert a == RecoveryAction.SKIP_STEP


def test_handle_locked_skips():
    h = FailureHandler(max_retries=3)
    a = h.handle("fortress_locked", {"worker_id": "w1"})
    assert a == RecoveryAction.SKIP_TARGET


def test_handle_window_disappeared_pauses():
    h = FailureHandler(max_retries=3)
    a = h.handle("window_disappeared", {"worker_id": "w1"})
    assert a == RecoveryAction.PAUSE_ALL
