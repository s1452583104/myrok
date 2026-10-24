"""宝石模式状态机（spec docs/superpowers/specs/2026-10-17-宝石模式-design.md §6）。

一轮 = 从 IDLE 到 ROUND_DONE 的整条链，两个出口：
  (a) 螺旋扫完 scan_rings 圈没找到宝石 → 本轮结束（spec §7.1「扫空算正常结束」）
  (b) 队列满（图标数 >= queue_limit）→ 等 idle_wait_min..max 分钟；等完还满 → 本轮结束
每次成功派兵后回 COUNT_QUEUES 重数（spec §6.1）。

**本模块绝不抛异常**：所有失败都写成 `ctx["fail_reason"] = <常量>` + 走到 END 边。
理由见模块顶部 Global Constraints 与 PROGRESS 已知问题 8 / 14。
"""
from __future__ import annotations

import random
import time

import cv2

from ..infra.logger import get_logger
from .state_machine import NORMALIZE_STUCK_REASON, StateMachine

logger = get_logger(__name__)

# ---- 失败原因常量 ----------------------------------------------------------
# 定义成模块常量而不是散落的字面量：runner 的 `_ENV_FAIL_REASONS` 按值查表，
# 两边靠字符串对齐，改名不会有编译期错误（见 tests/unit/workers/test_runner.py
# 的 test_env_fail_reasons_cover_every_abort_reason 哨兵）。

# 环境类：不计入连续失败
QUEUE_UNKNOWN_REASON = "queue_unknown"
RADIAL_MENU_MISSING_REASON = "radial_menu_missing"
RESOURCE_VIEW_FAILED_REASON = "resource_view_failed"
GEM_CONFIRM_FAILED_REASON = "gem_confirm_failed"
# 双确认缺了 OCR 那条腿（manifest 没配 `gem_dialog_title` 或 OCR 被关掉）：
# 这是**配置问题**，不是画面问题。宁可烧一轮也要让操作者看见，绝不静默
# 降级成「只看图标」（那等于把用户选定的双确认变成单确认，日志里还无痕）。
GEM_OCR_MISSING_REASON = "gem_ocr_missing"
# 真失败：计入连续失败
MARCH_REJECTED_REASON = "march_rejected"
COLLECT_REJECTED_REASON = "collect_rejected"
FORM_MISSING_REASON = "form_missing"

# 右侧队列栏里「在外」的队列图标（spec §6.2）。数图标是**主判据**；
# queue_badge 的 N/M 文本只在日志里做交叉验证，不参与裁决。
QUEUE_ICON_IDS = ("queue_gather_icon", "queue_march_icon", "queue_flag_icon",
                  "queue_battle_icon", "queue_return_icon")

# 连续多少个宝石候选都确认不了就干净中止本轮（spec §7）
_GEM_CONFIRM_MAX = 3
# 一轮里最多等「队列空出来」几次（spec §6.4）
_WAIT_PER_ROUND = 1
# 长按时长（ms）：实测 <600ms 会被当成点击
_LONG_PRESS_MS = 800

# 长按目标 = 左下角城堡/地图按钮，落点在 manifest 的 map_btn ROI [0,900,250,1080] 内
_MAP_BTN = (95, 990)
# 拖动起点取地图正中偏左（避开 HUD 与右侧队列栏）
_DRAG_CENTER = (900, 520)

# 归一化最多收拾几拍
_NORMALIZE_ATTEMPTS = 5

# 各步超时（秒）
_RADIAL_SETTLE = 1.2
_VIEW_TIMEOUT = 8.0
_SCAN_SETTLE = 1.0
_ZOOM_SETTLE = 1.5
_ZOOM_TIMEOUT = 6.0
_DIALOG_TIMEOUT = 8.0
_DIALOG_SETTLE = 1.2
_CREATE_TIMEOUT = 15.0       # 与 member_sm._form_troop 的 15.0 对齐
_LAUNCH_TIMEOUT = 10.0
_MARCH_SETTLE = 2.0         # 行军动画：队列图标不会立刻出现在队列栏里

# 资源视角判据（spec §8.2.1）：地图主体的 Canny 边缘像素占比。
# ROI 避开顶部 HUD、底部按钮栏、右侧队列栏。
_VIEW_ROI = (300, 200, 1620, 880)
_VIEW_EDGE_RATIO = 1.5

# 螺旋每一步的位移方向（屏幕坐标，y 向下）。段长 1,1,2,2,3,3…，方向按
# 右→下→左→上 循环——展开就是一圈圈扩大的方框（用户说的「回字形」）。
_SPIRAL_DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))


def _scan_total_steps(rings: int) -> int:
    """N 圈的螺旋总步数：段长 1,1,2,2,…,N,N 之和 = N(N+1)。"""
    return max(0, int(rings)) * (max(0, int(rings)) + 1)


def _scan_vector(k: int) -> tuple[int, int]:
    """螺旋第 k 步（k 从 1 起）的方向，单位是「格」。

    直接循环求段号。闭式公式在段号奇偶上极易写错（本函数第一版就错在
    k=5 落在了「左」而不是「上」），而段数最多 scan_rings 段，循环成本
    可以忽略——**这里选好读好验的那个**，`test_scan_vector_follows_square_spiral`
    是它的哨兵。
    """
    leg, remaining = 0, int(k)
    while True:
        length = leg // 2 + 1
        if remaining <= length:
            break
        remaining -= length
        leg += 1
    return _SPIRAL_DIRS[leg % 4]


class GemStateMachine(StateMachine):
    """宝石模式：扫图找宝石 → 确认 → 派兵采集 → 队列满了就等。"""

    def __init__(self, handle_source, recognizers, *, queue_limit=5,
                 scan_rings=3, scan_drag_px=800, scan_drag_ms=500,
                 idle_wait_min=20.0, idle_wait_max=30.0, char_id="?",
                 human=None, rng=None, clock=time.time, sleeper=time.sleep):
        self._handle = handle_source
        self._rec = recognizers
        self._queue_limit = int(queue_limit)
        self._scan_rings = int(scan_rings)
        self._scan_drag_px = int(scan_drag_px)
        self._scan_drag_ms = int(scan_drag_ms)
        self._idle_wait_min = float(idle_wait_min) * 60.0
        self._idle_wait_max = float(idle_wait_max) * 60.0
        # char_id 只用于日志前缀：一台模拟器一个号，队列/宝石都是本机的
        # 事实，不需要跨实例归属（寨子模式的账本才需要按 char_id 归属）
        self._char_id = char_id
        # clock / sleeper 可注入：单测换成虚拟时钟，不烧真实的 20~30 分钟
        self._clock = clock
        self._sleep = sleeper
        self._rng = rng if rng is not None else random.Random()
        self._wait_deadline = 0.0
        self._scan_index = 0
        self._tried_gems: set[tuple[int, int]] = set()
        self._gem_fail_streak = 0
        self._pending_gem: tuple[float, float] | None = None
        super().__init__(initial="IDLE", human=human)
        self.last_image = None

    # ---- 转移表 ----

    def _setup(self):
        self.add_transition("IDLE", "NORMALIZE", self._normalize_view)
        self.add_transition("NORMALIZE", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            == NORMALIZE_STUCK_REASON)
        self.add_transition("NORMALIZE", "COUNT_QUEUES", self._count_queues)
        # 队列满 → 先等一次；等过还满 → 收本轮（正常收尾，不是失败）。
        # **等待边必须先于收轮边注册**：StateMachine 按注册顺序取第一条
        # guard 通过的转移
        self.add_transition("COUNT_QUEUES", "WAIT", self._wait_slot,
                            guard=lambda ctx: ctx.get("queues_full")
                            and ctx.get("waits_used", 0) < _WAIT_PER_ROUND)
        self.add_transition("COUNT_QUEUES", "ROUND_DONE", self._end_round,
                            guard=lambda ctx: ctx.get("queues_full"))
        self.add_transition("COUNT_QUEUES", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            == QUEUE_UNKNOWN_REASON)
        self.add_transition("WAIT", "COUNT_QUEUES", self._end_wait)
        # 本轮正常收尾的唯一出口。action 是空 lambda：收尾要做的事
        # （留日志）已经在 _end_round 里做过了
        self.add_transition("ROUND_DONE", "END", lambda ctx: None)
        # 队列没满 → 进资源查看视角找宝石。**这条边没有 guard，必须排在
        # COUNT_QUEUES 的另外三条边之后**：StateMachine 取第一条 guard 通过
        # 的转移，放前面会把 WAIT / ROUND_DONE / END 全部吞掉。
        self.add_transition("COUNT_QUEUES", "OPEN_RESOURCE_VIEW",
                            self._open_resource_view)
        self.add_transition("OPEN_RESOURCE_VIEW", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            in (RADIAL_MENU_MISSING_REASON,
                                RESOURCE_VIEW_FAILED_REASON))
        # 交接边的 action 是 `_reset_scan`（不是 `_scan_step`）：进视角本身
        # 不消耗螺旋的一格，螺旋那一步属于 SCAN 自己（Ruling 33）。
        self.add_transition("OPEN_RESOURCE_VIEW", "SCAN", self._reset_scan)
        # SCAN 自环：一步一步往外扫。三条边的 guard 在 scan_verdict 上互斥
        # （continue / gem / exhausted），**这里的注册顺序不吃紧**；真正吃顺序的
        # 是 COUNT_QUEUES 那条无 guard 边（必须排最后）和 OPEN_RESOURCE_VIEW 的
        # END-before-SCAN。
        self.add_transition("SCAN", "SCAN", self._scan_step,
                            guard=lambda ctx: ctx.get("scan_verdict") == "continue")
        self.add_transition("SCAN", "ZOOM_CONFIRM", self._zoom_confirm,
                            guard=lambda ctx: ctx.get("scan_verdict") == "gem")
        self.add_transition("SCAN", "ROUND_DONE", self._end_round,
                            guard=lambda ctx: ctx.get("scan_verdict") == "exhausted")
        # ZOOM_CONFIRM：放弃边**先注册**。连续失败到上限、或确认策略缺
        # OCR 腿时，即使 zoom_verdict 是 retry 也要走 END，不能被「回 SCAN」
        # 那条边抢走
        self.add_transition("ZOOM_CONFIRM", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            in (GEM_CONFIRM_FAILED_REASON,
                                GEM_OCR_MISSING_REASON))
        self.add_transition("ZOOM_CONFIRM", "SCAN", self._scan_step,
                            guard=lambda ctx: ctx.get("zoom_verdict") == "retry")
        self.add_transition("ZOOM_CONFIRM", "COLLECT_DIALOG",
                            self._open_collect_dialog,
                            guard=lambda ctx: ctx.get("zoom_verdict") == "confirmed")
        # COLLECT_DIALOG：同样先注册放弃边
        self.add_transition("COLLECT_DIALOG", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            in (GEM_CONFIRM_FAILED_REASON,
                                GEM_OCR_MISSING_REASON))
        self.add_transition("COLLECT_DIALOG", "SCAN", self._scan_step,
                            guard=lambda ctx: ctx.get("dialog_verdict") == "retry")
        # 前进边写在回退边之后：两条 guard 互斥（dialog_verdict 只能是
        # "gem" 或 "retry"），顺序不影响行为——「先回退、再前进」是本仓库
        # 既有的阅读习惯（leader_sm 全篇如此）
        self.add_transition("COLLECT_DIALOG", "CLICK_COLLECT",
                            self._click_collect,
                            guard=lambda ctx: ctx.get("dialog_verdict") == "gem")
        self.add_transition("CLICK_COLLECT", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            == COLLECT_REJECTED_REASON)
        self.add_transition("CLICK_COLLECT", "CREATE_TROOP", self._create_troop)
        self.add_transition("CREATE_TROOP", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            == FORM_MISSING_REASON)
        self.add_transition("CREATE_TROOP", "FILL_FORM", self._fill_form)
        self.add_transition("FILL_FORM", "END", self._abort_round,
                            guard=lambda ctx: ctx.get("fail_reason")
                            == MARCH_REJECTED_REASON)
        self.add_transition("FILL_FORM", "COUNT_QUEUES", self._count_queues)

    # ---- step 覆写：WAIT 不阻塞线程 ----

    def step(self, context: dict | None = None) -> None:
        """WAIT 状态**不阻塞线程**：每拍只看一眼 deadline，没到就原地空转。

        在 action 里 sleep(20~30 分钟) 也能「实现等待」，但那样
        `WorkerRunner.stop()` 要等这个 sleep 跑完才 join 得上——用户点停止
        会卡住最长半小时（`_STOP_TIMEOUT` 只有 2s）。改成轮询 deadline，
        与 either_sm 的 WAIT_RETURN 同一套路。
        """
        if self.current == "WAIT" and self._clock() < self._wait_deadline:
            return
        super().step(context)

    def is_terminal(self) -> bool:
        return self.current == "END"

    # ---- IDLE → NORMALIZE ----

    def _normalize_view(self, ctx):
        """把画面收拾到「地图视图」。

        与寨子模式不同：宝石模式**只认地图视图**（`alliance_btn` 可见）。
        城市视图、战争列表、搜索面板、残留表单都收拾掉；收拾不掉就写
        `normalize_stuck` 干净中止本轮（**不抛异常**）。
        """
        for _ in range(_NORMALIZE_ATTEMPTS):
            if self._find("net_error_confirm") is not None:
                self._click_net_error()             # 断网弹框的确认（有界重试）
                continue
            if self._find("alliance_btn") is not None:
                ctx.pop("fail_reason", None)
                return
            if self._find("form_title") is not None:
                self._handle.click(1716, 69)        # 创建部队表单的 X
                continue
            if self._find("war_title") is not None:
                self._handle.click(1671, 64)        # 战争列表的 X
                continue
            if self._find("queue_panel") is not None:
                self._handle.click(1550, 320)       # 点空地收起队列侧栏
                continue
            if self._find("map_btn") is not None:
                self._click("map_btn")              # 城市视图 → 回地图
                continue
            self._sleep(self._pause(None))
        ctx["fail_reason"] = NORMALIZE_STUCK_REASON
        logger.warning("[宝石] 归一化收拾不出地图视图，本轮中止")

    # ---- 收尾出口 ----

    def _abort_round(self, ctx):
        """干净中止本轮：fail_reason 已由上游写好，这里只留日志。"""
        logger.warning("[宝石 %s] 本轮中止：%s", self._char_id,
                       ctx.get("fail_reason"))

    def _end_round(self, ctx):
        """本轮正常结束（**不是失败**）。

        两种来源：螺旋扫空，或队列满了且本轮已经等过一次。都不写
        fail_reason —— runner 据此记 rounds_ok；写了会被记成失败。
        """
        logger.info("[宝石 %s] 本轮结束（队列 %s/%s，扫了 %s 格）",
                    self._char_id, ctx.get("queue_count"), self._queue_limit,
                    self._scan_index)

    # ---- NORMALIZE → COUNT_QUEUES ----

    def _count_queues(self, ctx):
        """数右侧队列栏里在外的队列图标（主判据，spec §6.2）。

        已知局限（spec §12）：数的是**不同图标类型的命中数**，所以同一类型
        的两支队列（例如两支采集）会被算成 1 支。后果是低估 → 以为还能派
        → 点行军被游戏拒绝 → `march_rejected` 干净中止本轮。**方向安全**
        （只会白烧一轮，不会误等）。Stage 0 待验项 6 若证明游戏确实合并
        同类图标，这条局限就不存在；若证明是分行显示，改成按行计数。
        """
        ctx.setdefault("waits_used", 0)
        if self._find("net_error_confirm") is not None:
            self._click_net_error()             # 断网弹框盖住队列栏
            if self._find("net_error_confirm") is not None:
                # 关不掉：队列栏被弹框盖住，这一拍的读数是**未知**的，绝不能
                # 当成「队列没满」放行——Task 3.4 起 COUNT_QUEUES 有一条无
                # guard 的放行边，误放行会去派兵 → march_rejected（真失败，
                # 计入连续失败）。queue_unknown 是环境类，本轮干净中止
                ctx["fail_reason"] = QUEUE_UNKNOWN_REASON
                ctx["queues_full"] = False
                logger.warning("[宝石] 断网弹框关不掉（点了 %s 次仍在场），"
                               "队列栏被盖住、读数未知，本轮中止",
                               self._NET_ERROR_MAX_CLICKS)
                return
            logger.info("[宝石] 断网弹框已关掉，就地重数队列")
        count = self._count_queue_icons()
        if count < 0:
            ctx["fail_reason"] = QUEUE_UNKNOWN_REASON
            ctx["queues_full"] = False
            logger.warning("[宝石] 没有可用的队列图标判据（manifest 缺 "
                           "queue_*_icon），本轮中止")
            return
        ctx["queue_count"] = count
        ctx["queues_full"] = count >= self._queue_limit
        # 徽标只在日志里做交叉验证，**不参与裁决**（spec §6.2）：小地图与它
        # 的 ROI 重叠，世界地图上读出来的 N/M 不可信
        badge = self._find("queue_badge")
        logger.info("[宝石] 队列图标 %s/%s（满=%s，徽标%s）", count,
                    self._queue_limit, ctx["queues_full"],
                    "在场" if badge is not None else "不可见")

    def _count_queue_icons(self) -> int:
        """一帧里数命中的队列图标识别器个数。**一个识别器都不在 = -1**。

        -1 与 0 必须分开：0 是「数出来队列空着」（可以继续派兵），-1 是
        「根本没有判据」（manifest 没配、或装配失败）。
        """
        available = [rid for rid in QUEUE_ICON_IDS if self._rec.get(rid)]
        if not available:
            return -1
        img = self._handle.capture()
        self.last_image = img
        return sum(1 for rid in available
                   if self._rec[rid].recognize(img).matched)

    # ---- COUNT_QUEUES → WAIT ----

    def _wait_slot(self, ctx):
        """起一个等待窗口。**不 sleep** —— 见 step() 的注释。"""
        ctx["waits_used"] = ctx.get("waits_used", 0) + 1
        span = self._rng.uniform(self._idle_wait_min, self._idle_wait_max)
        self._wait_deadline = self._clock() + span
        logger.info("[宝石] 队列已满（%s/%s），等 %.0f 分钟后重数",
                    ctx.get("queue_count"), self._queue_limit, span / 60.0)

    def _end_wait(self, ctx):
        """等待结束 → **就地重数一次**，再落回 COUNT_QUEUES。

        必须在这里重数，不能只落回 COUNT_QUEUES 就完事：`COUNT_QUEUES` 的
        出口 guard 读的是 ctx 里的 `queues_full`，而那个值是等之前数的、
        已经过期——不重数就会拿 20~30 分钟前的旧读数直接收本轮（等价于
        「等完就结束」，等待毫无意义）。
        """
        logger.info("[宝石] 等待结束，重新数队列")
        self._count_queues(ctx)

    # ---- COUNT_QUEUES → OPEN_RESOURCE_VIEW ----

    def _open_resource_view(self, ctx):
        """长按地图按钮唤起环形菜单 → 点「资源」→ 确认进了资源查看视角。

        判据是**相对边缘密度**（spec §8.2.1）：进视角后城堡/资源/野怪都缩成
        小图标，同样面积里 Canny 边缘像素显著变多。取比值而不是绝对阈值——
        绝对阈值会被地形（山/海）和昼夜光照带跑。
        """
        before = self._edge_density()
        self._long_press(_MAP_BTN)
        if not self._wait_for("view_radial_menu", _VIEW_TIMEOUT):
            ctx["fail_reason"] = RADIAL_MENU_MISSING_REASON
            logger.warning("[宝石] 长按 %s 未唤出环形菜单（菜单没出来或点偏了）",
                           _MAP_BTN)
            return
        if not self._click("view_btn_resource"):
            ctx["fail_reason"] = RADIAL_MENU_MISSING_REASON
            logger.warning("[宝石] 环形菜单在场但「资源」按钮没认出来")
            return
        self._sleep(_RADIAL_SETTLE)
        after = self._edge_density()
        if after < before * _VIEW_EDGE_RATIO:
            ctx["fail_reason"] = RESOURCE_VIEW_FAILED_REASON
            logger.warning("[宝石] 点「资源」后边缘密度 %.4f → %.4f（未达 %.1f 倍），"
                           "判为没进资源查看视角", before, after, _VIEW_EDGE_RATIO)
            return
        logger.info("[宝石] 已进资源查看视角（边缘密度 %.4f → %.4f）", before, after)
        # 螺旋归零交给交接边 OPEN_RESOURCE_VIEW → SCAN 的 action（Ruling 33）：
        # 成功路径上那条边没有 guard，必然紧接着执行。

    def _reset_scan(self, ctx):
        """螺旋归零。**`_tried_gems` 每轮清一次**：上一轮确认失败的那些点位
        在下一轮是新的（队列排空后资源会刷新），不清会越扫越早收工。"""
        self._scan_index = 0
        self._tried_gems.clear()
        self._gem_fail_streak = 0
        self._pending_gem = None
        ctx.pop("fail_reason", None)
        ctx["scan_verdict"] = "continue"

    def _long_press(self, xy, ms: int = _LONG_PRESS_MS):
        """原地 swipe 就是长按。

        `AdbHandleSource` 映射成 `input swipe x y x y 800`（真按住），
        `MockHandleSource` 只记录；**`Win32HandleSource` 不支持**——它无视
        `duration_ms`，把 swipe 回放成 5 次同点 click，游戏不会认成长按。
        Win32 只是没配 `mumu_index`/`adb_address` 时的回退路径，生产走 adb；
        真落到那条路上，径向菜单不出现 → `RADIAL_MENU_MISSING_REASON` 干净中止。
        """
        x, y = xy
        self._handle.swipe(int(x), int(y), int(x), int(y), int(ms))

    def _edge_density(self) -> float:
        """地图主体 ROI 的 Canny 边缘像素占比（spec §8.2.1）。

        ROI 刻意避开顶部 HUD、底部按钮栏、右侧队列栏——这三块是常驻的，
        算进去会把「进没进视角」这个信号淹掉。
        """
        img = self._handle.capture()
        self.last_image = img
        x1, y1, x2, y2 = _VIEW_ROI
        gray = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        return float(cv2.Canny(gray, 60, 160).mean() / 255.0)

    # ---- SCAN：回字形螺旋 ----

    _TRIED_GRID = 40        # 「同一颗宝石」的判定格：40px 内的命中算同一颗

    def _scan_step(self, ctx):
        """先看**当前**画面有没有宝石，没有就往外拖一格。

        顺序很关键：`_scan_index` 是「已经拖了几格」，所以每次进来先判断
        眼前这一屏，再决定拖不拖——否则第一屏会被整屏跳过。
        """
        ctx.pop("fail_reason", None)
        img = self._handle.capture()
        self.last_image = img
        hit = self._find_gem(img)
        if hit is not None and not self._is_tried(hit):
            self._pending_gem = hit
            ctx["scan_verdict"] = "gem"
            logger.info("[宝石] 第 %s 格发现候选 (%.0f,%.0f)",
                        self._scan_index, hit[0], hit[1])
            return
        if hit is not None:
            logger.info("[宝石] 第 %s 格的候选 (%.0f,%.0f) 之前确认失败过，跳过",
                        self._scan_index, hit[0], hit[1])
        if self._scan_index >= _scan_total_steps(self._scan_rings):
            ctx["scan_verdict"] = "exhausted"
            logger.info("[宝石] 螺旋扫完 %s 圈（%s 格）无新宝石",
                        self._scan_rings, self._scan_index)
            return
        self._scan_index += 1
        dx, dy = _scan_vector(self._scan_index)
        self._drag(dx * self._scan_drag_px, dy * self._scan_drag_px)
        self._sleep(_SCAN_SETTLE)
        ctx["scan_verdict"] = "continue"

    def _drag(self, dx: int, dy: int):
        """把画面往 (dx, dy) 方向挪：**手指反向拖**（手往左拖 = 看到右边）。

        起点固定在地图中心偏左：落在 HUD 或右侧队列栏上会变成「点击」，
        而点中地图上的资源会弹出详情面板，把整轮带偏。
        """
        x, y = _DRAG_CENTER
        self._handle.swipe(x, y, x - dx, y - dy, self._scan_drag_ms)

    def _find_gem(self, img):
        """在**已截好的一帧**里找宝石图标。返回中心坐标或 None。

        `gem_icon` 在 manifest 里是 `template_match` + YOLO 模型 → 装配成
        `RecognizerChain`（YOLO 腿在前），这里不需要知道是哪条腿命中的。
        """
        rec = self._rec.get("gem_icon")
        if rec is None:
            return None
        r = rec.recognize(img)
        return r.bbox.center() if r.matched else None

    def _gem_key(self, xy) -> tuple[int, int]:
        """把坐标量化成格：`gem_icon` 的检测框会随帧抖动几像素，不比格
        的话同一颗宝石会被当成新候选反复点开。"""
        return (int(xy[0]) // self._TRIED_GRID, int(xy[1]) // self._TRIED_GRID)

    def _is_tried(self, xy) -> bool:
        return self._gem_key(xy) in self._tried_gems

    # ---- SCAN → ZOOM_CONFIRM（Task 3.6 实现）----

    def _zoom_confirm(self, ctx):
        """点开候选宝石 → 放大 → 认出「放大的宝石图标」才算数。

        双确认的第一腿（spec §6.6）：扫描时的 `gem_icon` 是小图标，误检率
        天然高于放大后的 `gem_mine_zoom`——放大这一步把「地图上一小坨白色」
        变成「一个明确的宝石矿面板」，是**成本最低的消歧手段**（一次点击
        + 一次截图）。第二腿是 COLLECT_DIALOG 的 OCR 文字确认。
        """
        ctx.pop("fail_reason", None)
        if not self._rec.get("gem_dialog_title"):
            # 缺腿的确认策略不静默降级——见 GEM_OCR_MISSING_REASON 的注释。
            # 放在最前面：判据缺失是**配置问题**，不该等点开面板才发现
            ctx["fail_reason"] = GEM_OCR_MISSING_REASON
            ctx["zoom_verdict"] = "retry"
            logger.error("[宝石] manifest 里没有 `gem_dialog_title`（text_fields）"
                         "或 OCR 未启用，双确认缺 OCR 腿，本轮中止")
            return
        target = self._pending_gem
        if target is None:
            ctx["zoom_verdict"] = "retry"
            return
        self._click_xy(target[0], target[1], anchor="gem_icon")
        self._sleep(_ZOOM_SETTLE)
        if self._wait_for("gem_mine_zoom", _ZOOM_TIMEOUT):
            self._gem_fail_streak = 0
            ctx["zoom_verdict"] = "confirmed"
            logger.info("[宝石] 候选 (%.0f,%.0f) 放大后确认是宝石", *target)
            return
        self._give_up_candidate(ctx, target, "放大后认不出宝石", "zoom_verdict")

    # ---- ZOOM_CONFIRM → COLLECT_DIALOG ----

    def _open_collect_dialog(self, ctx):
        """在放大后的宝石画面上再点一下 → 采集框 → 双确认第二腿。

        `collect_dialog`（框在不在）+ `gem_dialog_title`（标题 OCR 读出
        「宝石」）。地图上「一小坨白色」既可能是宝石也可能是别的矿，只有
        图标腿会误派一支队伍去采 20 分钟。
        """
        ctx.pop("fail_reason", None)
        target = self._pending_gem
        if target is not None:
            self._click_xy(target[0], target[1], anchor="gem_mine_zoom")
        if self._wait_for("collect_dialog", _DIALOG_TIMEOUT):
            if self._find("gem_dialog_title") is not None:
                self._gem_fail_streak = 0
                ctx["dialog_verdict"] = "gem"
                logger.info("[宝石] 采集框 + 标题 OCR 双确认通过")
                return
            logger.info("[宝石] 采集框出来了但标题不是「宝石」（别的资源），跳过")
        else:
            logger.info("[宝石] 第二下没弹出采集框")
        self._give_up_candidate(ctx, target, "没拿到宝石采集框", "dialog_verdict")

    # ---- COLLECT_DIALOG → CLICK_COLLECT ----

    def _click_collect(self, ctx):
        """点蓝色「采集」按钮（spec §6.7）。

        **按钮点了没反应 = 游戏拒绝**：只看「点到了没有」会把静默拒绝记成
        成功派兵，而队列数纹丝不动 → 下一拍还是同一屏，白烧一整轮。所以
        这里用 `_wait_for_gone` 确认采集框真的关掉了。
        """
        ctx.pop("fail_reason", None)
        if not self._click("collect_btn"):
            ctx["fail_reason"] = COLLECT_REJECTED_REASON
            logger.warning("[宝石] 采集框在场但蓝色「采集」按钮认不出来")
            return
        self._sleep(_DIALOG_SETTLE)
        if not self._wait_for_gone("collect_dialog", _DIALOG_TIMEOUT):
            ctx["fail_reason"] = COLLECT_REJECTED_REASON
            logger.warning("[宝石] 点了「采集」但采集框仍在场（游戏拒绝了）")
            return
        logger.info("[宝石] 采集已受理，等创建部队表单")

    # ---- CLICK_COLLECT → CREATE_TROOP ----

    def _create_troop(self, ctx):
        """等「创建部队」表单出现（spec §6.8）。

        与成员填兵**逐字同一套动作**（`member_sm._form_troop`）：先点蓝色
        「创建部队」气泡按钮，再等 `march_btn`。气泡不在是正常的——游戏某些
        入口直接给表单，所以点击失败只当白费 ~2s 重试，不判失败。

        与 `leader_sm._form_troop` 的**唯一区别**：等不到表单时这里写
        `fail_reason` 走 END 边，而不是 `raise RuntimeError`。
        """
        ctx.pop("fail_reason", None)
        if self._click_retry("join_create_btn", attempts=2):
            logger.info("[宝石] 点了「创建部队」气泡按钮")
        if self._wait_for("march_btn", timeout=_CREATE_TIMEOUT):
            ctx["form_open"] = True
            logger.info("[宝石] 创建部队表单已打开")
            return
        ctx["form_open"] = False
        ctx["fail_reason"] = FORM_MISSING_REASON
        logger.warning("[宝石] 点了「采集」后 %.0fs 内没等到创建部队表单",
                       _CREATE_TIMEOUT)

    # ---- CREATE_TROOP → FILL_FORM ----

    def _fill_form(self, ctx):
        """点「行军」出发（spec §6.9）。

        **只点行军**：预设槽、兵种、队列数量一律用游戏默认——用户
        2026-10-17 明确要求（原方案「选最大队列再行军」被否掉）。与成员
        填兵同口径（`member_sm._launch`），也正是它一直以来的行为。

        成功标志 = 创建部队表单关闭。只确认「点到了按钮」是不够的：静默
        拒绝会被记成一次成功派兵，而队列数纹丝不动。
        """
        ctx.pop("fail_reason", None)
        if not self._click_retry("march_btn", attempts=3):
            ctx["fail_reason"] = MARCH_REJECTED_REASON
            logger.warning("[宝石] 行军按钮点不动（表单可能已经关了）")
            return
        logger.info("[宝石] 点行军，采集队出发")
        if not self._wait_for_gone("march_btn", timeout=_LAUNCH_TIMEOUT):
            ctx["fail_reason"] = MARCH_REJECTED_REASON
            logger.warning("[宝石] 点了行军但表单仍在场（游戏拒绝了这次派兵）")
            return
        self._sleep(_MARCH_SETTLE)

    def _give_up_candidate(self, ctx, target, why: str, verdict_key: str):
        """放弃一个候选：**必须记进 `_tried_gems`**，否则同一颗宝石会被
        反复点开、反复关掉，整轮卡死在原地。

        连续放弃到 `_GEM_CONFIRM_MAX` 个就写 `gem_confirm_failed` 干净中止
        本轮（不抛异常）。
        """
        if target is not None:
            self._tried_gems.add(self._gem_key(target))
        self._gem_fail_streak += 1
        self._close_detail()
        ctx[verdict_key] = "retry"
        logger.warning("[宝石] 候选 %s %s（第 %s 次），跳过继续扫",
                       ("(%.0f,%.0f)" % target) if target else "（未知位置）",
                       why, self._gem_fail_streak)
        if self._gem_fail_streak >= _GEM_CONFIRM_MAX:
            ctx["fail_reason"] = GEM_CONFIRM_FAILED_REASON
            logger.warning("[宝石] 连续 %s 个候选都确认不了，本轮中止",
                           self._gem_fail_streak)

    def _close_detail(self):
        """关掉放大后的详情面板，回资源查看视角。

        用 `back_from_detail`（详情面板右上角的返回），失配时兜底点一次
        面板外的空地——**不能只靠点空地**：点在地图上的资源上会再开一个
        面板，越关越乱。
        """
        if self._click("back_from_detail"):
            self._sleep(_ZOOM_SETTLE)
            return
        self._click_xy(200, 900)
        self._sleep(_ZOOM_SETTLE)
