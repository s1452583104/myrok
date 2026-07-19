import numpy as np
from rok_assistant.core.handle_source import MockHandleSource

def test_mock_returns_configured_screenshot():
    img = np.full((100, 200, 3), 128, dtype=np.uint8)
    m = MockHandleSource(screenshot=img)
    captured = m.capture()
    assert captured.shape == (100, 200, 3)
    assert (captured == 128).all()

def test_mock_records_clicks():
    m = MockHandleSource(screenshot=np.zeros((10, 10, 3), dtype=np.uint8))
    m.click(50, 60)
    m.click(100, 200)
    assert m.clicks == [(50, 60), (100, 200)]

def test_mock_is_alive_default_true():
    m = MockHandleSource(screenshot=np.zeros((10, 10, 3), dtype=np.uint8))
    assert m.is_alive() is True

def test_mock_is_alive_can_be_toggled():
    m = MockHandleSource(screenshot=np.zeros((10, 10, 3), dtype=np.uint8),
                         alive=False)
    assert m.is_alive() is False

def test_mock_swipe_recorded():
    m = MockHandleSource(screenshot=np.zeros((10, 10, 3), dtype=np.uint8))
    m.swipe(1, 2, 3, 4, duration_ms=500)
    assert m.swipes == [(1, 2, 3, 4, 500)]
