import json
from pathlib import Path
import numpy as np
import cv2
import pytest
from rok_assistant.coordination.replay import ReplaySession, ReplayHandleSource

@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "session_test"
    d.mkdir()
    for i in range(3):
        cv2.imwrite(str(d / f"frame_{i:05d}.png"), np.zeros((10, 10, 3), dtype=np.uint8))
    (d / "manifest.json").write_text(json.dumps({
        "account": "test", "frames": [
            {"index": 0, "file": "frame_00000.png", "ts": 0.0},
            {"index": 1, "file": "frame_00001.png", "ts": 0.5},
            {"index": 2, "file": "frame_00002.png", "ts": 1.0},
        ]
    }))
    return d

def test_replay_loads_manifest(session_dir):
    s = ReplaySession(session_dir)
    assert len(s.frames) == 3

def test_replay_handle_capture_returns_frame(session_dir):
    s = ReplaySession(session_dir)
    h = ReplayHandleSource(s)
    img = h.capture()
    assert img.shape == (10, 10, 3)

def test_replay_handle_advance(session_dir):
    s = ReplaySession(session_dir)
    h = ReplayHandleSource(s)
    h.capture()  # frame 0
    h.capture()  # frame 1
    h.capture()  # frame 2
    h.capture()  # past end, returns last
    assert h.current_index == 3
