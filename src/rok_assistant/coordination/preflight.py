from __future__ import annotations

import time

from ..core.handle_source import create_handle_source
from ..infra.logger import get_logger

logger = get_logger(__name__)

# 每台模拟器最多尝试几次（首次 + 重试）。断线是常态而非异常：adb server
# 重启、模拟器刚唤醒都会让首次 capture 失败，重试通常就好了。
ATTEMPTS = 3
RETRY_BACKOFF = (1.0, 2.0)      # 第 2、3 次尝试前的等待（秒）


def _where(inst) -> str:
    """「这台模拟器怎么指认」的人类可读说法。

    与 runtime.start 里那段点名文案是同一套（2026-10-05：配了两台时裸异常
    只有「模拟器 1 可能没有启动」，用户不知道该去开哪个）。
    """
    if inst.mumu_index is not None:
        return f"MuMu 编号 {inst.mumu_index}"
    if inst.adb_address:
        return f"adb {inst.adb_address}"
    return f"窗口 {inst.window_title_pattern!r}"


def preflight(instances, app_config) -> dict:
    """逐台建句柄并真截一帧；失败点名抛 RuntimeError。

    返回 {instance_id: HandleSource}，供 RuntimeCoordinator.start() 复用——
    create_handle_source 走 mumu_index 时要调 MuMuManager（冻结包里实测
    0.67–1.11s，见 PROGRESS 已知问题 10），不该建两遍。

    为什么用 capture() 而不是 is_alive()：后者只查 `adb devices` 的状态字段
    （core/handle_source.py），而实机上真正会炸的是 screencap。

    为什么判定分辨率：竖屏/登录页/认错窗口会让门槛白等 900s（运行手册
    Step 1），与其静默烧 15 分钟，不如启动时就说清楚实际尺寸。
    """
    expected = (app_config.screen_height, app_config.screen_width, 3)
    handles: dict = {}
    for inst in instances:
        last: Exception | None = None
        t0 = time.monotonic()
        for attempt in range(ATTEMPTS):
            if attempt:
                time.sleep(RETRY_BACKOFF[attempt - 1])
            try:
                handle = create_handle_source(
                    mumu_index=inst.mumu_index,
                    mumu_manager_path=app_config.mumu_manager_path,
                    adb_address=inst.adb_address,
                    adb_path=app_config.adb_path,
                    window_title_pattern=inst.window_title_pattern)
                frame = handle.capture()
            except Exception as e:                  # noqa: BLE001 - 逐次重试
                last = e
                logger.warning("预检：模拟器「%s」第 %s/%s 次失败：%s",
                               inst.name, attempt + 1, ATTEMPTS, e)
                continue
            shape = getattr(frame, "shape", None)
            if shape != expected:
                last = RuntimeError(
                    f"截到的画面尺寸是 {shape}，期望 {expected}"
                    f"（竖屏 / 未进入地图界面 / 认错窗口）")
                logger.warning("预检：模拟器「%s」尺寸异常：%s", inst.name, shape)
                continue
            handles[inst.id] = handle
            break
        else:
            where = _where(inst)
            elapsed = time.monotonic() - t0
            # 这段**整个落在 worker 日志之外**：worker 还没起来，运行日志里
            # 一个字都没有（用户的 logs/ 里那次就是 0 字节）。所以这里既点名
            # 又写日志（同 runtime.start 的教训）。
            logger.error("模拟器「%s」（%s，%s）预检失败（耗时 %.1fs）：%s",
                         inst.name, inst.id, where, elapsed, last)
            raise RuntimeError(
                f"模拟器「{inst.name}」（{inst.id}，{where}）连不上"
                f"（已试 {ATTEMPTS} 次，耗时 {elapsed:.1f}s）：{last}")
    # 成功也要报一句，让用户知道连接**真的测过了**，而不是「没报错」。
    # 主线程 + 非 worker 线程名 → QtLogHandler 的 char_id 为空 →
    # MainWindow._on_log_line 直接落到状态栏（log_handler.py:60-61）。
    logger.info("预检通过：%s 台模拟器", len(handles))
    return handles
