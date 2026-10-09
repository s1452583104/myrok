import threading
import time
from unittest.mock import MagicMock

from rok_assistant.coordination.event_bus import EventBus
from rok_assistant.coordination.runtime import RuntimeCoordinator
from rok_assistant.infra.config import RootConfig

CFG = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe"},
    "instances": [
        {"id": "mumu0", "mumu_index": 0,
         "characters": [{"id": "c0", "name": "车头", "role": "leader",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"]}]},
        {"id": "mumu1", "mumu_index": 1,
         "characters": [{"id": "c1", "name": "填兵", "role": "member",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"],
                         "fill_target_leaders": [{"instance": "mumu0",
                                                  "name": "车头"}]}]},
    ],
}


def _coord(bus):
    coord = RuntimeCoordinator(RootConfig.model_validate(CFG), event_bus=bus)
    # 不真启动：只放两个占位 runner，测汇总逻辑。必须是 MagicMock ——
    # 车头收工时协调器会真的调成员 runner 的 stop()（2026-10-09）
    coord.runners = {"mumu0:c0": MagicMock(), "mumu1:c1": MagicMock()}
    return coord


# 两个车头 + 一个成员：并发收工回归用（两个车头都会走「收尾」分支）。
CFG_TWO_LEADERS = {
    "app": {"mumu_manager_path": "M.exe", "adb_path": "adb.exe"},
    "instances": [
        {"id": "mumu0", "mumu_index": 0,
         "characters": [{"id": "c0", "name": "头0", "role": "leader",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"]}]},
        {"id": "mumu1", "mumu_index": 1,
         "characters": [{"id": "c1", "name": "头1", "role": "leader",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"]}]},
        {"id": "mumu2", "mumu_index": 2,
         "characters": [{"id": "c2", "name": "填兵", "role": "member",
                         "target_levels": [5], "march_preset": 1,
                         "march_troop_types": ["cavalry"],
                         "fill_target_leaders": [{"instance": "mumu0",
                                                  "name": "头0"}]}]},
    ],
}


def test_leaders_finishing_stops_members_and_fires_all_workers_done():
    """车头全收工 → 成员被协调器停掉 → 发 all_workers_done。

    波次模式下成员永不进终态（不记轮次），「全部上报」这个条件永远不成立，
    所以收工判据改成「全部 leader/either 上报」（2026-10-09）。
    """
    bus = EventBus()
    done = []
    bus.subscribe("all_workers_done", done.append)
    coord = _coord(bus)
    member_runner = coord.runners["mumu1:c1"]

    bus.publish("worker_finished", {"instance_id": "mumu0", "char_id": "c0",
                                    "stopped_reason": "已完成 10 轮，达到轮数上限"})
    assert len(done) == 1
    assert done[0]["reasons"]["mumu0:c0"] == "已完成 10 轮，达到轮数上限"
    assert "mumu1:c1" in done[0]["reasons"]        # 成员由协调器代记
    member_runner.stop.assert_called_once()


def test_member_finishing_first_does_not_fire():
    """成员先收工（异常停机）不算全部收工：车头还在跑。"""
    bus = EventBus()
    done = []
    bus.subscribe("all_workers_done", done.append)
    _coord(bus)
    bus.publish("worker_finished", {"instance_id": "mumu1", "char_id": "c1",
                                    "stopped_reason": "连续 6 次 step 异常"})
    assert done == []


def test_all_workers_done_not_published_for_unknown_runner():
    bus = EventBus()
    done = []
    bus.subscribe("all_workers_done", done.append)
    _coord(bus)
    bus.publish("worker_finished", {"instance_id": "mumu9", "char_id": "x",
                                    "stopped_reason": "r"})
    assert done == []      # 不在 self.runners 里的事件不能凑数


def test_already_stopped_member_is_not_stopped_twice():
    """成员已经自然收工过（异常停机），协调器不再对它调 stop。"""
    bus = EventBus()
    bus.subscribe("all_workers_done", lambda _p: None)
    coord = _coord(bus)
    member_runner = coord.runners["mumu1:c1"]
    bus.publish("worker_finished", {"instance_id": "mumu1", "char_id": "c1",
                                    "stopped_reason": "r"})
    bus.publish("worker_finished", {"instance_id": "mumu0", "char_id": "c0",
                                    "stopped_reason": "r"})
    member_runner.stop.assert_not_called()


def test_old_coordinator_does_not_refire_after_natural_finish():
    # 旧 coordinator 自然收工后必须从 bus 上退订（Critical 回归）：否则同一根
    # bus 上新起一轮时，旧 coordinator 的满员状态会立刻再发一次
    # all_workers_done，把运行中的 Stop 按钮禁掉。
    bus = EventBus()
    done = []
    bus.subscribe("all_workers_done", done.append)
    coord = _coord(bus)
    bus.publish("worker_finished", {"instance_id": "mumu0", "char_id": "c0",
                                    "stopped_reason": "r"})
    assert len(done) == 1                  # 车头收工即触发（成员由协调器停）

    # 旧 coordinator 已退订：把 runner 再挂回去（模拟同一根 bus 上下一轮又被
    # 挂上），再投一次也不该有第二次。必须重新挂回——_on_worker_finished 末尾的
    # runners.clear() 会替退订挡住第二次，只有挂回去才能单独钉住「退订」本身。
    coord.runners["mumu0:c0"] = MagicMock()
    coord.runners["mumu1:c1"] = MagicMock()
    bus.publish("worker_finished", {"instance_id": "mumu0", "char_id": "c0",
                                    "stopped_reason": "r"})
    assert len(done) == 1                  # 没有第二次 all_workers_done


def test_concurrent_finishes_are_safe_and_publish_exactly_once():
    """两个车头近同时收工：并发跑 _on_worker_finished 不得抛异常，且
    all_workers_done 恰好发一次（回归 Important）。

    EventBus.publish 是同步的——处理器就在发布事件的 worker 线程里跑，两个
    车头近同时收工就会并发跑这里。修复前 `_leaders_done` 迭代 self.runners 时
    另一线程 `runners.clear()` → RuntimeError（被 EventBus 吞掉 → 发不出
    all_workers_done、GUI 按钮不复位）；`_stop_members` 也会在 clear 后
    `self.runners[key]` 抛 KeyError。修复后顶部拍一次 runners 快照即可安全。

    两个钩子把并发窗口拉出来（都只用**跨版本稳定**的签名，不碰内部实现）：
    - `_leaders_done` 进门前加一道 Barrier，逼两个线程同时停在处理器里；
    - `_role_of` 首次遇到成员 key 时阻塞一下，让另一线程先跑完并 clear。
    修复前滞留线程恢复后继续迭代已被清空的 dict → RuntimeError 逃逸；
    修复后无异常且只发一次。
    """
    bus = EventBus()
    done: list = []
    bus.subscribe("all_workers_done", done.append)
    coord = RuntimeCoordinator(RootConfig.model_validate(CFG_TWO_LEADERS),
                               event_bus=bus)
    coord.runners = {"mumu0:c0": MagicMock(), "mumu1:c1": MagicMock(),
                     "mumu2:c2": MagicMock()}

    real_leaders_done = coord._leaders_done
    real_role_of = coord._role_of
    barrier = threading.Barrier(2)      # 逼两个线程同时进处理器
    stall_token = {"open": True}        # 原子认领：只让一个线程滞留

    def synced_leaders_done(*args, **kwargs):
        barrier.wait(timeout=5)
        return real_leaders_done(*args, **kwargs)

    def slow_role_of(key):
        if key == "mumu2:c2" and stall_token.pop("open", None) is not None:
            time.sleep(0.5)             # 让另一线程先跑完并 clear
        return real_role_of(key)

    coord._leaders_done = synced_leaders_done
    coord._role_of = slow_role_of

    errors: list = []

    def finish(inst: str, cid: str) -> None:
        try:
            coord._on_worker_finished({"instance_id": inst, "char_id": cid,
                                       "stopped_reason": "r"})
        except Exception as e:          # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=finish, args=("mumu0", "c0"))   # 车头
    t2 = threading.Thread(target=finish, args=("mumu1", "c1"))   # 车头
    t1.start(); t2.start(); t1.join(); t2.join()

    assert errors == []                 # 无异常逃逸（修复前是 RuntimeError）
    assert len(done) == 1               # all_workers_done 恰好一次
