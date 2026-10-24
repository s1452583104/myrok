from __future__ import annotations
import threading
from datetime import datetime
from pathlib import Path

from ..infra.logger import get_logger
from ..infra.anti_detection import AntiDetectionConfig, HumanProfile
from .state_machine import NORMALIZE_STUCK_REASON

logger = get_logger(__name__)

# 状态 → 中文提示（日志用）。未收录的状态如实打印原值，新增状态无需注册。
_STATE_ZH = {
    # Runner 自身生命周期（小写）
    "idle": "已启动，状态机就绪",
    "paused": "已暂停：模拟器窗口失联，等待恢复",
    "cooldown": "本轮结束，冷却后自动开始下一轮",
    "error": "出现异常，已截图记录，退避后自动重试",
    # 通用 SM 状态
    "IDLE": "待机",
    "END": "本轮结束",
    # 车头阶段（LEADER: 前缀）
    "LEADER:IDLE": "车头·待机",
    "LEADER:NORMALIZE": "车头·回到地图视图",
    "LEADER:SEARCH_FORTRESS": "车头·打开搜索面板",
    "LEADER:SELECT_LEVEL": "车头·设置城寨等级",
    "LEADER:CONFIRM_SEARCH": "车头·点击搜索",
    "LEADER:CHECK_RESULT": "车头·检查搜索结果",
    "LEADER:CLICK_RED_RALLY": "车头·点击城寨红色集结按钮",
    "LEADER:VERIFY_UNLOCKED": "车头·确认城寨未被锁定",
    "LEADER:SELECT_RALLY_TIME": "车头·发起集结进攻",
    "LEADER:FORM_TROOP": "车头·创建部队（预设槽+兵种）",
    "LEADER:LAUNCH": "车头·点击行军，集结出发",
    "LEADER:WAIT_MEMBERS": "车头·等待成员填兵",
    # 成员阶段（MEMBER: 前缀）
    "MEMBER:IDLE": "成员·待机",
    "MEMBER:WAIT_LAUNCH_EVENT": "成员·等待车头的发车事件",
    "MEMBER:SWITCH_TO_SELF": "成员·切换到自己视图",
    "MEMBER:NORMALIZE": "成员·回到地图视图",
    "MEMBER:OPEN_ALLIANCE": "成员·打开联盟面板",
    "MEMBER:OPEN_WAR": "成员·打开联盟战争列表",
    "MEMBER:SORT_BY_NEAREST": "成员·按距离排序集结列表",
    "MEMBER:FILTER": "成员·筛选可加入的集结",
    "MEMBER:CLICK_JOIN": "成员·点击加入集结",
    "MEMBER:VERIFY_JOINED": "成员·确认加入结果",
    "MEMBER:JOIN_CHECKED": "成员·加入校验完成",
    "MEMBER:FORM_TROOP": "成员·创建部队填兵",
    "MEMBER:LAUNCH": "成员·点击行军，填兵出发",
    "MEMBER:SWITCH_BACK": "成员·返回自己城市",
    # either 角色返城等待
    "WAIT_RETURN": "等待集结部队返城",
    # 答题模式（不登记裸 NORMALIZE：寨多多的车头/成员 SM 也用它当裸状态名，
    # 加一条会连带改掉那边的日志；答题的 NORMALIZE 由 gui/labels.py 兜住）
    "OPEN_QUIZ": "打开答题活动",
    "READ": "读题",
    "ANSWER": "作答",
    "VERIFY": "确认绿色高亮",
    "LEARN": "写入学习题库",
    "ADVANCE": "等下一题",
    "COOLDOWN": "本轮结束，冷却中",
    # Runner 结束态
    "done": "已达停止条件，收工",
}

def _zh(state: str) -> str:
    return _STATE_ZH.get(state, state)


# 环境类失败原因：**不计入连续失败数**。语义是「这不是代码或配置的错，
# 别记失败」——行动力不足、弹窗关不掉、目标城寨过期、画面停在收拾不掉的
# 视图上，都属于「等一会儿/换个目标就好」。
#
# 为什么单独拎出来（2026-10-12 用户报「一直重试，最后失败退出程序」）：
# `_check_stop_conditions` 连续 `_max_fail_streak`(=3) 轮失败就收工。这些
# 原因本身都**会在下一轮自愈**——重建 SM 后 NORMALIZE 会再收一次弹窗，寨子
# 也会随时间消失——所以把它们算成「连续失败」等于把一次弹窗卡顿升级成收工。
# 不计入连续失败、冷却后接着跑；每轮照常打警告日志，fail_reason 也随
# status_update 带给 GUI，用户看得见。
#
# 宝石模式新增 5 条，逐条说明为什么算环境类：
#   queue_unknown        —— manifest 少配了 queue_*_icon，是配置缺口
#   radial_menu_missing  —— 长按没唤出环形菜单（点偏了 / 菜单改版）
#   resource_view_failed —— 点了「资源」但画面没进缩放视角（游戏改了入口）
#   gem_confirm_failed   —— 连续 3 个候选都确认不了：地图上噪声多，是画面问题
#   gem_ocr_missing      —— manifest 少配了 gem_dialog_title，是配置缺口
# 反例（**必须留在名单外**）：march_rejected / collect_rejected /
# form_missing —— 点了按钮没生效，那是真出问题了，得攒够失败停下来喊人。
#
# 答题模式新增 3 条环境类：
#   quiz_entry_missing —— 找不到答题入口 / 活动没开（游戏界面改版或不在活动期）
#   quiz_screen_lost   —— 答题页被弹窗/断线盖住，看不见题
#   quiz_parse_failed  —— 一题没答就连续读不出题目（分辨率/识别问题）
# 反例（**必须留在名单外**）：answer_not_accepted —— 点了选项画面不动，
# 那是真的出了问题（点击被吞 / 游戏拒绝），得攒够失败停下来喊人。
_ENV_FAIL_REASONS = frozenset({
    "no_action_points", "ap_dialog_stuck", "stale_fortress_target",
    NORMALIZE_STUCK_REASON,
    "queue_unknown", "radial_menu_missing", "resource_view_failed",
    "gem_confirm_failed", "gem_ocr_missing",
    "quiz_entry_missing", "quiz_screen_lost", "quiz_parse_failed",
})

# 体力不足要靠**自然恢复**（道具吃完了就只能等），不是等 30s 冷却：一轮搜完
# 才发现体力不够，等几分钟再试才有意义。其余环境原因用正常冷却——下一轮的
# NORMALIZE 立刻就能重收弹窗，没必要干等。
_NO_AP_REASON = "no_action_points"
_NO_AP_COOLDOWN = 300.0


class WorkerRunner:
    """每角色一个线程：循环 step 状态机、发布状态、异常截图、终态冷却重建。

    状态经 EventBus 的 "status_update" 发布（仅变化时）：
    payload = {"instance_id", "char_id", "char_name", "state", "ts",
    "fail_reason"}。fail_reason 取自 sm.fail_reason（give-up/exhausted
    出口写入，未失败为 None）——现有消费方只读各自关心的键，新增键向后兼容。
    state 值域约定：小写 = Runner 自身生命周期状态（"idle" 哨兵、
    "paused"/"cooldown"/"error"）；大写 = SM 当前状态（如 "IDLE"/"END"），
    如实转发。首轮发布的大写 "IDLE" 表示工作线程已启动且 SM 就绪。
    Task 8 的 GUI 映射负责大小写呈现。

    线程安全：status / reached_terminal / sm 均为跨线程读的普通属性
    （CPython 下属性读写原子，安全）。sm 会被工作线程在终态冷却后整体
    替换 —— 外部（RuntimeCoordinator）读 runner.sm.current / 调
    on_rally_launched 是无锁快照读，极小概率读到刚重建的新 SM，可接受
    （事件路由由 Task 8 在 IDLE/WAIT_LAUNCH_EVENT 状态判断）。

    建议调用方显式传入 screenshot_dir；默认的 CWD 相对 "recordings"
    仅为兜底便利。
    """

    def __init__(self, instance_id: str, char_id: str, char_name: str,
                 sm_factory, handle_source, event_bus=None,
                 poll_interval: float = 2.0, restart_cooldown: float = 30.0,
                 error_backoff: float = 10.0, pause_poll: float = 5.0,
                 screenshot_dir: Path | None = None,
                 max_rounds: int | None = None,
                 max_consecutive_failures: int = 3,
                 human: HumanProfile | None = None):
        self.instance_id = instance_id
        self.char_id = char_id
        self.char_name = char_name
        self._sm_factory = sm_factory
        self.sm = sm_factory()
        self._handle = handle_source
        self._bus = event_bus
        self._poll = poll_interval
        self._cooldown = restart_cooldown
        # 冷却/轮询等待经此 profile 抖动（反检测：精确恒定的间隔是机器特征）。
        # 未注入时用确定性 profile，行为与改动前逐字相同。
        self._human = human if human is not None else HumanProfile(
            AntiDetectionConfig(debug_no_jitter=True))
        self._error_backoff = error_backoff
        self._pause_poll = pause_poll
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else Path("recordings")
        # 轮次与停止条件（2026-09-11 验收目标：跑满 N 轮或连续失败即收工）。
        # 环境/资源类中止（_ENV_FAIL_REASONS）不计入连续失败——见常量注释
        self._max_rounds = max_rounds
        self._max_fail_streak = max_consecutive_failures
        self._max_error_streak = max_consecutive_failures * 2
        self.rounds_done = 0          # 已完成的轮数（成功+失败都算）
        # 轮次按结局分开计数（GUI 统计条的「完成/失败/中止」读这三个）。
        # 只有 rounds_done 时界面拿不到「打成了几个」，而它把三种结局混在
        # 一起，当「完成个数」显示会虚高。三者之和恒等于 rounds_done。
        self.rounds_ok = 0            # 正常收尾（fail_reason 为 None）
        self.rounds_failed = 0        # 真失败（附近没寨子/寨子已锁/没找到集结）
        self.rounds_env = 0           # 环境类中止（_ENV_FAIL_REASONS）
        self._fail_streak = 0         # 连续失败终态计数（成功清零）
        self._error_streak = 0        # 连续 step 异常计数（成功 step 清零）
        self.stopped_reason: str | None = None   # 非 None = 主循环已退出
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "idle"
        self._reached_terminal = False

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return   # 重复 start 忽略，防止双线程驱同一状态机
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"worker:{self.instance_id}:{self.char_id}")
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ---- 查询 ----
    @property
    def status(self) -> str:
        return self._status

    @property
    def last_frame(self):
        return getattr(self.sm, "last_image", None)

    def reached_terminal(self) -> bool:
        return self._reached_terminal

    # ---- 主循环 ----
    def _run(self) -> None:
        # 主循环永不主动退出（除非 stop）：任何异常都被捕获，线程不死。
        while not self._stop_event.is_set():
            try:
                if not self._handle.is_alive():
                    self._set_status("paused")   # §3.5：窗口消失 → 暂停
                    self._stop_event.wait(self._pause_poll)
                    continue
                if self.sm.is_terminal():
                    self._reached_terminal = True
                    reason = getattr(self.sm, "fail_reason", None)
                    self.rounds_done += 1
                    if reason in _ENV_FAIL_REASONS:
                        # 环境/资源挡路（见 _ENV_FAIL_REASONS）：不算失败，
                        # 冷却后接着跑，别把它升级成「连续 N 轮失败，收工」
                        self.rounds_env += 1
                        self._fail_streak = 0
                        logger.warning("worker %s/%s[%s] 第 %s 轮中止：%s"
                                       "（环境/资源问题，不计入连续失败）",
                                       self.instance_id, self.char_id,
                                       self.char_name, self.rounds_done, reason)
                    elif reason:
                        self.rounds_failed += 1
                        self._fail_streak += 1
                        logger.warning("worker %s/%s[%s] 第 %s 轮失败结束：%s"
                                       "（连续失败 %s/%s）",
                                       self.instance_id, self.char_id,
                                       self.char_name, self.rounds_done, reason,
                                       self._fail_streak, self._max_fail_streak)
                    else:
                        self.rounds_ok += 1
                        self._fail_streak = 0
                        logger.info("worker %s/%s[%s] 第 %s/%s 轮完成",
                                    self.instance_id, self.char_id,
                                    self.char_name, self.rounds_done,
                                    self._max_rounds)
                    stop = self._check_stop_conditions()
                    if stop:
                        break
                    self._set_status("cooldown")
                    cooldown = (_NO_AP_COOLDOWN if reason == _NO_AP_REASON
                                else self._cooldown)
                    self._stop_event.wait(self._human.jitter(cooldown))
                    if self._stop_event.is_set():
                        break
                    self.sm = self._sm_factory()   # 冷却后重建，进入下一轮
                    self._set_status(self.sm.current)
                    continue
                self.sm.step()
                self._error_streak = 0
                self._set_status(self.sm.current)
            except Exception as e:   # 任何异常：截图 + 记录 + 退避后继续（不杀线程）
                # 计数先加再记：`_set_status` 对相同状态去重，第 2–6 次连续
                # 异常在状态流/GUI 里看不见（只留 `error` 这一个值），
                # 「还剩几次就停机」只有这里能留痕——2026-10-15 实机复盘时
                # 4 次连击在日志里完全读不出进度。
                self._error_streak += 1
                logger.exception("worker %s/%s step failed（连续 %s/%s 次，"
                                 "达上限即停机）: %s",
                                 self.instance_id, self.char_id,
                                 self._error_streak, self._max_error_streak, e)
                self._save_failure_screenshot()
                self._set_status("error")
                if self._error_streak >= self._max_error_streak:
                    self.stopped_reason = (
                        f"连续 {self._error_streak} 次 step 异常（疑似体力耗尽"
                        "或环境异常），停止")
                    logger.warning("worker %s/%s[%s] %s", self.instance_id,
                                   self.char_id, self.char_name,
                                   self.stopped_reason)
                    self._set_status("done")
                    break
                self._stop_event.wait(self._error_backoff)
                continue   # 退避即全部恢复延时，不再叠加 poll 等待
            self._stop_event.wait(self._human.jitter(self._poll))

        # 主循环退出（三个 break 出口统一走到这里）。stopped_reason 非 None
        # 才算「自然收工」——用户点 Stop 时它保持 None，不能触发 GUI 复位。
        if self.stopped_reason is not None and self._bus:
            self._bus.publish("worker_finished", {
                "instance_id": self.instance_id, "char_id": self.char_id,
                "char_name": self.char_name,
                "stopped_reason": self.stopped_reason,
                "rounds_done": self.rounds_done,
                "ts": datetime.now().isoformat(timespec="seconds"),
            })

    def _check_stop_conditions(self) -> bool:
        """终态后的停止条件检查（2026-09-11 验收目标：跑满 N 轮或连续失败
        即收工）。命中时置 stopped_reason、发 "done" 状态并让主循环退出。"""
        if self._max_rounds is not None and self.rounds_done >= self._max_rounds:
            self.stopped_reason = f"已完成 {self.rounds_done} 轮，达到轮数上限"
        elif self._fail_streak >= self._max_fail_streak:
            # 只统计真失败；体力/弹窗类中止已在 _run 里排除（见
            # _ENV_FAIL_REASONS），不会走到这里。文案必须模式中性——
            # 寨多多/宝石/答题（如 answer_not_accepted）共用这条出口。
            last = getattr(self.sm, "fail_reason", None) or "未知原因"
            self.stopped_reason = (f"连续 {self._fail_streak} 轮失败"
                                   f"（最后一次：{last}），停止")
        if self.stopped_reason is None:
            return False
        logger.info("worker %s/%s[%s] %s", self.instance_id, self.char_id,
                    self.char_name, self.stopped_reason)
        self._set_status("done")
        return True

    def _set_status(self, state: str) -> None:
        if state == self._status:
            return
        self._status = state
        logger.info("worker %s/%s[%s] -> %s", self.instance_id, self.char_id,
                    self.char_name, _zh(state))
        if self._bus:
            self._bus.publish("status_update", {
                "instance_id": self.instance_id, "char_id": self.char_id,
                "char_name": self.char_name, "state": state,
                "fail_reason": getattr(self.sm, "fail_reason", None),
                "ts": datetime.now().isoformat(timespec="seconds"),
            })

    def _save_failure_screenshot(self) -> None:
        img = self.last_frame
        if img is None:
            return
        try:
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)
            name = f"failure_{self.instance_id}_{self.char_id}_{datetime.now():%Y%m%d_%H%M%S}.png"
            path = self._screenshot_dir / name
            # Windows 下 cv2.imwrite 对非 ASCII 路径静默返回 False，
            # 改用 imencode + write_bytes 保证写入可靠。
            import cv2
            ok, buf = cv2.imencode(".png", img)
            if not ok:
                logger.error("失败截图编码出错: %s", path)
                return
            path.write_bytes(buf.tobytes())
        except Exception:
            logger.exception("保存失败截图出错")
