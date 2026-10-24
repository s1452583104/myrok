from __future__ import annotations
from ..infra.config import CharacterConfig, RoleEnum
from .leader_sm import LeaderStateMachine
from .member_sm import MemberStateMachine
from .either_sm import EitherStateMachine
from .gem_sm import GemStateMachine
from .quiz_sm import QuizStateMachine
from .queue_gate import QueueGate


def create_state_machine(character: CharacterConfig, handle_source, recognizers: dict,
                         event_bus=None, rally_tracker=None, ledger=None,
                         human=None):
    """Build the state machine matching a character's configured role.

    rally_tracker：进程级集结事件登记簿（runtime 注入），either 车头
    让车/拒绝降级决策用；leader/member 角色不用。publisher_id 用
    character.id，让登记簿区分「自己/对方」的集结事件。
    ledger：进程级动作账本（runtime 注入），发车/填兵确认后写「部队
    在外」，供集结门槛的 L0 判据用；未注入 = 不记账 = 旧行为。
    human：反检测 HumanProfile（runtime 注入）；未注入时状态机用确定性
    默认 profile（debug_no_jitter），行为与改动前逐字相同。"""
    if character.role == RoleEnum.LEADER:
        # 集结前置门槛（2026-10-04 bug：纯车头不查队列，主将还在城外就
        # 开集结，「创建部队」载不出预设 → 卡在「预设槽 1 高亮未确认」）。
        # 门槛原先只接在 either 上，纯 leader 拿到的是裸状态机。账本未
        # 注入时特性关闭（与 ledger 参数的既有语义一致）。
        gate = QueueGate(ledger, character.id) if ledger is not None else None
        return LeaderStateMachine(handle_source, recognizers, character.target_levels,
                                  event_bus=event_bus,
                                  publisher_id=character.id, ledger=ledger,
                                  queue_gate=gate, human=human,
                                  march_presets=[(p.preset, list(p.troops))
                                                 for p in character.march_presets])
    if character.role == RoleEnum.MEMBER:
        # 填兵不使用预设/兵种选择（用户要求 2026-09-09），
        # 故不传 march_preset/march_troop_types
        # event_driven=True：一次信号填完所有点名车头，不记轮次（2026-10-09）
        return MemberStateMachine(handle_source, recognizers,
                                  character.fill_target_leaders,
                                  char_id=character.id, ledger=ledger,
                                  human=human, event_driven=True)
    if character.role == RoleEnum.EITHER:
        return EitherStateMachine(handle_source, recognizers, character.target_levels,
                                  character.march_preset, character.march_troop_types,
                                  character.fill_target_leaders, event_bus,
                                  char_id=character.id, rally_tracker=rally_tracker,
                                  ledger=ledger, human=human,
                                  march_presets=[(p.preset, list(p.troops))
                                                 for p in character.march_presets])
    raise ValueError(f"Unknown role: {character.role}")


def create_gem_state_machine(character, handle_source, recognizers, *,
                             queue_limit: int, scan_rings: int,
                             scan_drag_px: int, scan_drag_ms: int,
                             idle_wait_min: float, idle_wait_max: float,
                             human=None):
    """宝石模式的状态机工厂。

    与 `create_state_machine` 并列而不是合并：寨子那个按 `character.role`
    分三路，宝石模式**没有分工**（一个实例一个号，既不开车也不填兵），
    参数全来自 `GemConfig`。硬塞进同一个函数只会让两边都变难读。

    `ledger` / `rally_tracker` / `event_bus` 一个都不传：宝石模式一台机器
    一个号、各干各的，没有跨实例通信（spec §2）。
    """
    return GemStateMachine(
        handle_source, recognizers,
        queue_limit=queue_limit, scan_rings=scan_rings,
        scan_drag_px=scan_drag_px, scan_drag_ms=scan_drag_ms,
        idle_wait_min=idle_wait_min, idle_wait_max=idle_wait_max,
        char_id=character.id, human=human)


def create_quiz_state_machine(character, handle_source, recognizers, ocr, bank,
                              solver, *, verify_delay: float = 1.2,
                              min_green_ratio: float = 0.55,
                              parse_retries: int = 2, entry_taps=None,
                              auto_click: bool = True, human=None):
    """答题模式的状态机工厂。

    与宝石工厂并列而不是合并：答题的依赖比宝石多两个活对象（OCR 引擎、
    题库/求解器），而且它们**跨轮复用**（协调器建一次）。塞进
    `create_state_machine` 会让寨子那条路平白多两个必填参数。

    题量、轮次、冷却都不在参数里：题量按场次固定（`core.quiz.session`，
    星期几绑定）；轮次恒为 1（答题一天只能答一次，用户 2026-10-25 拍板），
    由协调器 `_max_rounds()` 收口，状态机内没有冷却状态。

    `event_bus` / `ledger` / `rally_tracker` 一个都不传：一台模拟器一个号，
    没有跨实例通信（spec §2）。
    """
    return QuizStateMachine(
        handle_source, ocr=ocr, bank=bank, solver=solver,
        recognizers=recognizers,
        verify_delay=verify_delay, min_green_ratio=min_green_ratio,
        parse_retries=parse_retries,
        entry_taps=[tuple(int(v) for v in tap) for tap in (entry_taps or [])],
        auto_click=auto_click, char_id=character.id, human=human)
