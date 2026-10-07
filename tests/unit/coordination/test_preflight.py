import numpy as np
import pytest

from rok_assistant.coordination import preflight as PF
from rok_assistant.infra.config import RootConfig

CFG = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe",
            "screen_width": 1920, "screen_height": 1080},
    "instances": [
        {"id": "mumu0", "name": "如愿", "mumu_index": 0,
         "characters": [{"id": "c0", "name": "车头", "role": "leader",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"]}]},
        {"id": "mumu1", "name": "阑珊填1", "mumu_index": 1,
         "characters": [{"id": "c1", "name": "填兵", "role": "member",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"],
                         "fill_target_leaders": [{"instance": "mumu0",
                                                  "name": "车头"}]}]},
    ],
}


class _FakeHandle:
    def __init__(self, frame=None, error=None):
        self._frame = frame
        self._error = error

    def capture(self):
        if self._error is not None:
            raise self._error
        return self._frame

    def click(self, x, y, anchor=None, rapid=False):
        pass


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(PF.time, "sleep", lambda _s: None)


def _cfg():
    return RootConfig.model_validate(CFG)


def test_preflight_returns_handles_for_all_instances(monkeypatch):
    frames = {"mumu0": _FakeHandle(np.zeros((1080, 1920, 3), dtype=np.uint8)),
              "mumu1": _FakeHandle(np.zeros((1080, 1920, 3), dtype=np.uint8))}
    monkeypatch.setattr(PF, "create_handle_source",
                        lambda **kw: frames[f"mumu{kw['mumu_index']}"])
    handles = PF.preflight(_cfg().instances, _cfg().app)
    assert set(handles) == {"mumu0", "mumu1"}


def test_preflight_retries_then_names_the_instance(monkeypatch):
    calls = []

    def _factory(**kw):
        calls.append(kw["mumu_index"])
        return _FakeHandle(error=RuntimeError("device not found"))

    monkeypatch.setattr(PF, "create_handle_source", _factory)
    with pytest.raises(RuntimeError) as ei:
        PF.preflight(_cfg().instances, _cfg().app)
    msg = str(ei.value)
    assert "如愿" in msg and "mumu0" in msg and "MuMu 编号 0" in msg
    assert "device not found" in msg
    assert len(calls) == 3          # 最多尝试 3 次


def test_preflight_rejects_wrong_frame_shape(monkeypatch):
    monkeypatch.setattr(
        PF, "create_handle_source",
        lambda **kw: _FakeHandle(np.zeros((1920, 1080, 3), dtype=np.uint8)))
    with pytest.raises(RuntimeError) as ei:
        PF.preflight(_cfg().instances, _cfg().app)
    assert "(1920, 1080, 3)" in str(ei.value)


def test_preflight_succeeds_after_a_transient_failure(monkeypatch):
    state = {"n": 0}

    def _factory(**kw):
        state["n"] += 1
        if state["n"] == 1:
            return _FakeHandle(error=RuntimeError("adb: device offline"))
        return _FakeHandle(np.zeros((1080, 1920, 3), dtype=np.uint8))

    monkeypatch.setattr(PF, "create_handle_source", _factory)
    handles = PF.preflight(_cfg().instances, _cfg().app)
    assert set(handles) == {"mumu0", "mumu1"}
