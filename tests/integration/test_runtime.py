import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
from contextlib import contextmanager

import numpy as np
from unittest.mock import patch

from rok_assistant.coordination.runtime import RuntimeCoordinator
from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.core.handle_source import MockHandleSource
from rok_assistant.infra.config import load_config


VALID = """
app:
  mumu_manager_path: ""
  adb_path: "adb"
instances:
  - id: inst0
    name: a
    adb_address: "127.0.0.1:5555"
    characters:
      - id: boss
        name: 车头
        role: leader
        target_level: 7
        march_preset: 1
        march_troop_types: [cavalry]
  - id: inst1
    name: b
    adb_address: "127.0.0.1:5556"
    characters:
      - id: worker
        name: 成员
        role: member
        target_level: 7
        march_preset: 1
        march_troop_types: [cavalry]
        fill_target_leaders:
          - { instance: inst0, name: 车头 }
"""

# 空模板清单：Registry 加载成功但 recognizers 为空，避免依赖真实 templates/
EMPTY_MANIFEST = "templates: []\n"


def _write_config(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(VALID, encoding="utf-8")
    return load_config(p)


@contextmanager
def _running_coordinator(tmp_path):
    """启动一个用 MockHandleSource + 空模板清单的 coordinator，结束即停。"""
    cfg = _write_config(tmp_path)
    (tmp_path / "manifest.yaml").write_text(EMPTY_MANIFEST, encoding="utf-8")
    bus = EventBus()
    fake_handle = MockHandleSource(screenshot=np.zeros((100, 100, 3), dtype=np.uint8))
    with patch("rok_assistant.coordination.runtime.create_handle_source",
               return_value=fake_handle):
        coord = RuntimeCoordinator(cfg, event_bus=bus, template_dir=tmp_path)
        coord.start()
        try:
            yield coord
        finally:
            coord.stop()


def test_coordinator_builds_one_runner_per_first_character(tmp_path):
    with _running_coordinator(tmp_path) as coord:
        assert set(coord.runners) == {"inst0:boss", "inst1:worker"}


def test_coordinator_routes_rally_to_member_runner(tmp_path):
    with _running_coordinator(tmp_path) as coord:
        member_sm = coord.runners["inst1:worker"].sm
        coord._bus.publish("rally_launched", {"rally_id": "r9"})
        # 线程在跑，消费时机不定：轮询等待成员 SM 留存的事件（last_event
        # 在 _consume_event 后持久保留，_pending_event 则被清空）
        deadline = time.time() + 5.0
        while member_sm.last_event is None and time.time() < deadline:
            time.sleep(0.05)
        assert member_sm.last_event == {"rally_id": "r9"}


def test_coordinator_snapshot_returns_jpeg_bytes(tmp_path):
    with _running_coordinator(tmp_path) as coord:
        # 无帧时返回 None
        assert coord.snapshot("unknown") is None
        # 注入一帧后返回以 JPEG magic 开头的非空 bytes
        coord.runners["inst0:boss"].sm.last_image = np.zeros((4, 4, 3), np.uint8)
        data = coord.snapshot("boss")
        assert data is not None
        assert data[:2] == b"\xff\xd8"
