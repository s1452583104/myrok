from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np

@dataclass
class ReplayFrame:
    index: int
    file: str
    ts: float

class ReplaySession:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        manifest = json.loads((session_dir / "manifest.json").read_text())
        self.frames = [ReplayFrame(**f) for f in manifest["frames"]]

class ReplayHandleSource:
    """HandleSource that returns recorded frames in sequence."""
    def __init__(self, session: ReplaySession):
        self._session = session
        self.current_index = 0
        self.clicks: list = []

    def capture(self) -> np.ndarray:
        if self.current_index >= len(self._session.frames):
            idx = len(self._session.frames) - 1
        else:
            idx = self.current_index
            self.current_index += 1
        path = self._session.session_dir / self._session.frames[idx].file
        return cv2.imread(str(path))

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))

    def is_alive(self) -> bool:
        return True

    def swipe(self, *args, **kwargs) -> None:
        pass
