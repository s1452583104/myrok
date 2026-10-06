from __future__ import annotations
from .state_machine import StateMachine
from ..core.recognizers.view_probe import View, ViewProbe
from ..infra.logger import get_logger

logger = get_logger(__name__)

# 战争列表检索/加入的重试上限：列表开着原地轮询（每轮 ~4-6s）。联盟
# 集结准备窗最长 10 分钟（默认 5 分钟发车）：成员轮询窗口必须能覆盖
# 「车头还在开下一轮集结」的整段时间 —— 2026-09-12 实机教训：10 次
# (~50s) 就放弃，车头 8 分钟后开出集结时已没人填，solo 出发白跑。
# 60 次 ~5-6 分钟，与准备窗对齐；耗尽仍放弃本轮走 runner 冷却重试。
_JOIN_POLL_TIMEOUT = 3.0
_JOIN_MAX_ATTEMPTS = 60
_PANEL_MAX_ATTEMPTS = 10

# 战争列表固定几何（1920x1080 实机测量）：「+加入」按钮列横坐标固定；
# 名字行中心到同行「+」按钮中心的纵向偏移（两行实测 112/110px）。
_PLUS_X = 1335
_NAME_TO_PLUS_DY = 111

# 派遣队列侧栏展开态会盖掉整个底部栏（含联盟旗帜/map_btn，2026-09-11
# 实机验收 mumu1 卡死态）：点侧栏外空地收起侧栏与「创建部队」引导气泡。
_QUEUE_SIDEBAR_DISMISS = (1550, 320)


class MemberStateMachine(StateMachine):
    """成员填兵（2026-09-11 实机验证的真实链路）：

    地图右下角联盟旗帜 -> 战争列表（直接落在列表，无需再点战争页签）
    -> 点目标行的绿色「+加入」-> 「创建部队」弹窗 -> 点行军出发
    （用户实机确认 2026-09-11：加入仍需 创建部队→行军 两步）。

    关键实机事实：
    - 创建部队弹窗不点预设槽位、不点兵种图标，直接点行军 —— 使用游戏
      默认兵队，满足「填兵不使用预设操作，直接使用默认的」（用户要求
      2026-09-09）；行军按钮与车头链路共用 march_btn 模板。
    - 行内按钮三态：绿「+加入」=可加入；橙「替换」=已加入；
      红「X取消」=自己开的集结（不可加入自己）。
    - 战争列表排序（距离最近/最新发起）面板会记住上次选择，v1 不主动切。
    - 搜索面板开着时右下角旗帜被底部搜索栏替换（搜索模式专属底栏），
      归一化需先退搜索（search_back）。

    填兵指向：只填 fill_target_leaders 里点名的车头 —— 名字模板
    （manifest id 为 fill_<车头名>，如 fill_Jy丶阑珊）在战争列表名字列
    匹配出目标行，再按固定几何点该行的「+」。列表里他人的集结一律不填
    （兵出去填陌生人会错过车头的下一轮集结）。
    """

    def __init__(self, handle_source, recognizers: dict, fill_target_leaders,
                 char_id: str = "?", ledger=None, human=None):
        self._handle = handle_source
        self._rec = recognizers
        # 归一化：config 侧是 FillLeader pydantic 对象，测试/事件侧是 dict
        self._fill_targets = [
            {"instance": t["instance"], "name": t["name"]} if isinstance(t, dict)
            else {"instance": t.instance, "name": t.name}
            for t in fill_target_leaders
        ]
        missing = [t["name"] for t in self._fill_targets
                   if self._target_rec_id(t) not in recognizers]
        if missing:
            logger.warning("成员·填兵目标缺少名字模板: %s "
                           "（templates/manifest.yaml 需有 fill_<名字> 项）", missing)
        self._char_id = char_id
        # 进程级动作账本（runtime 注入）：填兵确认后记「部队在外」+ 填兵
        # 时刻，供集结门槛的 L0 判据用。未注入 = 不记账 = 旧行为
        self._ledger = ledger
        # 视图判定探针（2026-09-30）：只做「额外的成功信号」与「失败归因」，
        # 不取代 _normalize_view 的残留面板清理清单
        self._view_probe = ViewProbe(recognizers)
        self._pending_event = None
        self.last_event = None  # 消费后的 launch 事件留存（供调用方/测试断言）
        super().__init__(initial="IDLE", human=human)

    @staticmethod
    def _target_rec_id(target: dict) -> str:
        return f"fill_{target['name']}"

    def _setup(self):
        self.add_transition("IDLE", "WAIT_LAUNCH_EVENT", self._consume_event,
                            guard=lambda ctx: self._pending_event is not None)
        self.add_transition("WAIT_LAUNCH_EVENT", "SWITCH_TO_SELF", self._switch_to_self)
        self.add_transition("SWITCH_TO_SELF", "NORMALIZE", self._normalize_view)
        self.add_transition("NORMALIZE", "OPEN_WAR", self._open_war)
        # 耗尽出口必须注册在对应重试边之前：StateMachine.step 按注册顺序
        # 取第一个 from_state 匹配且 guard 通过的转移。
        self.add_transition("OPEN_WAR", "END", self._exhausted,
                            guard=lambda ctx: ctx.get("war_attempts", 0) > _PANEL_MAX_ATTEMPTS)
        self.add_transition("OPEN_WAR", "OPEN_WAR", self._open_war,
                            guard=lambda ctx: not ctx.get("panel_open"))
        self.add_transition("OPEN_WAR", "FIND_JOIN", lambda ctx: None,
                            guard=lambda ctx: ctx.get("panel_open"))
        self.add_transition("FIND_JOIN", "CLICK_JOIN", self._click_join,
                            guard=lambda ctx: ctx.get("join_found"))
        self.add_transition("FIND_JOIN", "END", self._exhausted,
                            guard=lambda ctx: ctx.get("join_attempts", 0) > _JOIN_MAX_ATTEMPTS)
        self.add_transition("FIND_JOIN", "FIND_JOIN", self._poll_join,
                            guard=lambda ctx: not ctx.get("join_found"))
        # guard 先于 action 求值：每步的副作用都放在入口 action 里完成，
        # 结果写进 ctx 供下一条边 guard 使用。点击「+」后仍要经过
        # 「创建部队」「行军」两步（2026-09-11 用户实机确认）。
        # 已加入快速通道必须注册在 FORM_TROOP→LAUNCH 之前（注册序匹配）
        self.add_transition("CLICK_JOIN", "FORM_TROOP", self._form_troop)
        self.add_transition("FORM_TROOP", "VERIFY_JOINED", lambda ctx: None,
                            guard=lambda ctx: ctx.get("already_joined"))
        self.add_transition("FORM_TROOP", "LAUNCH", lambda ctx: None,
                            guard=lambda ctx: ctx.get("form_open"))
        self.add_transition("FORM_TROOP", "OPEN_WAR", self._join_missed,
                            guard=lambda ctx: not ctx.get("form_open"))
        self.add_transition("LAUNCH", "VERIFY_JOINED", self._launch)
        self.add_transition("VERIFY_JOINED", "JOIN_CHECKED", self._verify_join)
        self.add_transition("JOIN_CHECKED", "END", lambda ctx: None,
                            guard=lambda ctx: ctx.get("joined"))
        self.add_transition("JOIN_CHECKED", "OPEN_WAR", self._join_missed,
                            guard=lambda ctx: not ctx.get("joined"))

    def on_rally_launched(self, event: dict) -> None:
        self._pending_event = event

    def _consume_event(self, ctx):
        self.last_event = self._pending_event
        self._pending_event = None

    def _switch_to_self(self, ctx):
        # v1: 每个实例单角色，无需切换（多角色切换是 v2）
        pass

    def _normalize_view(self, ctx):
        # 地图视图的标志是右下角联盟旗帜可见。战争列表开着（上一轮残留）
        # 会盖住左下角按钮：先点右上角 X（固定几何 1671,64）关掉；派遣队列
        # 侧栏展开态则点空地收起（见 _QUEUE_SIDEBAR_DISMISS 注释）。搜索面板
        # 开着时底部栏变成搜索目标栏、旗帜不可见（2026-09-11 实机），先退
        # 搜索；城市视图则点 map_btn 回地图。
        if self._find("alliance_btn"):
            return
        if self._find("war_title"):
            # 战争面板盖住底部栏与左缘旗帜（成员轮空放弃后面板常残留，
            # 2026-09-18 实机 run6 03:46：点完 X 不等过渡动画，后续检查
            # 全在淡出里落空 → 归一化超时抛异常连续计败）。先关面板，
            # 放大镜现形（地图视图确认）即归一化成功
            self._handle.click(1671, 64)
            if self._wait_for("search_icon", timeout=6.0):
                return
        if self._find("alliance_btn"):
            return
        if self._find("queue_panel"):
            self._handle.click(*_QUEUE_SIDEBAR_DISMISS)
        if self._find("rally_attack_popup"):
            # 集结进攻弹窗残留（either 角色上轮被杀在选时间步）：模态弹窗
            # 压住 HUD，点空地关闭后再继续归一化
            self._handle.click(960, 540)
        if self._find("ap_refill"):
            # 行动力不足弹窗（加入行军点击时行动力 < 消耗弹出，2026-09-18
            # 实机 run9 86/140 实锤）：补体力（每日免费 500 + 初级恢复 100）
            # 而非关弹窗 —— 关掉只会让加入继续失败，10 轮目标必须吃道具
            if not self._refill_ap():
                self._handle.click(1638, 120)
        if self._find("form_title"):
            # 创建部队表单残留（上轮进程被杀在 FORM_TROOP，2026-09-12 实机
            # mumu0）：全屏模态盖住一切，点右上角 X 关闭再归一化。
            # 2026-09-18 实机 run7 04:24（失败截图 form_title=1.000）：点 X
            # 不等淡出就往下走，后续检查全在模态底下落空 → 归一化死路。
            # 与 war_title 同款：关一次确认一次（放大镜现形=地图视图），
            # 表单还开着才补点 X（最多 3 次），关了但地图未就绪交给末尾判据
            for _ in range(3):
                self._handle.click(1671, 64)
                if self._wait_for("search_icon", timeout=6.0):
                    return
                if not self._find("form_title"):
                    break
        if self._find("replace_popup"):
            # 部队替换确认弹窗残留（部队已在集结中又点「+」，2026-09-13
            # 实机 mumu0）：不替换（被替换部队白回城），点弹窗右上角 X
            self._handle.click(1500, 170)
        if self._find("menu_expanded"):
            # 底部快捷菜单展开态（战役/道具/联盟/统帅/邮件，2026-09-15 实机
            # mumu0 00:20 六连异常收工）：展开时联盟旗帜按钮被整体隐藏。
            # 再点一次右下角 ☰ 即收起（2026-09-16 实机验证），收起后本就在
            # 地图视图，旗帜立即可见
            self._handle.click(1845, 1010)
        if self._find("warning_panel"):
            # 「预警」面板（增援/来攻警报触发时游戏自动弹出，2026-09-15
            # 实机 mumu1 00:09 六连异常收工）：全屏模态盖住一切，点右上角
            # X（与战争列表同位）关闭再继续归一化
            self._handle.click(1671, 64)
        if self._find("alliance_btn"):
            return
        if self._find("search_back"):
            self._click("search_back")
        elif self._find("map_btn"):
            self._click("map_btn")
        if not (self._wait_for("alliance_btn", timeout=8.0)
                or self._wait_for("search_icon", timeout=2.0)):
            # 2026-09-18 实机：简化模式下联盟快捷键整体不显示，城市视图
            # 归一化在此处误抛异常连续计败。放大镜与旗帜同为地图视图专属
            # UI，任一可见即归一化成功。都不见时用探针说清卡在哪
            view = self._view_probe.probe(self._handle.capture()).view
            raise RuntimeError(f"归一化失败：卡在[{view.value}]视图"
                               "（联盟旗帜与放大镜均不可见）")

    def _open_war(self, ctx):
        ctx["war_attempts"] = ctx.get("war_attempts", 0) + 1
        # 已在战争列表（来自 VERIFY_JOINED 的重试回流）就不必再点旗帜：
        # 面板开着时旗帜被遮住/点空，反而把面板点没了
        if self._find("war_title"):
            ctx["panel_open"] = True
            return
        if not self._click_retry("alliance_btn"):
            logger.info("成员·联盟旗帜不可见，重试 (%s/%s)",
                        ctx["war_attempts"], _PANEL_MAX_ATTEMPTS)
            ctx["panel_open"] = False
            return
        ctx["panel_open"] = self._wait_for("war_title", timeout=6.0)
        if ctx["panel_open"]:
            logger.info("成员·战争列表已打开")

    def _poll_join(self, ctx):
        # 原地轮询点名车头的集结：名字模板在名字列匹配出目标行，记录该行
        # 「+」按钮的固定几何位置。联盟集结每隔几分钟才开一轮，暂时没有
        # 就继续等；他人的集结一律不填（见类注释）
        ctx["join_attempts"] = ctx.get("join_attempts", 0) + 1
        n, cap = ctx["join_attempts"], _JOIN_MAX_ATTEMPTS
        # 列表中途被游戏关掉（自己参与的集结发车/弹窗顶掉等，2026-09-18
        # 实机 run8：面板关闭后 60 次轮询全在地图上空找，烧完整个加入
        # 窗口）——每拍先确认战争列表还开着，没了就重开再找
        if not self._find("war_title"):
            if not self._click_retry("alliance_btn", attempts=2):
                logger.info("成员·战争列表被关闭且联盟旗帜不可见，下拍重试")
                ctx["join_found"] = False
                return
        for t in self._fill_targets:
            r = self._wait_for_result(self._target_rec_id(t),
                                      timeout=_JOIN_POLL_TIMEOUT)
            if r is None:
                continue
            _, cy = r.bbox.center()
            ctx["target_click"] = (_PLUS_X, cy + _NAME_TO_PLUS_DY)
            ctx["join_found"] = True
            logger.info("成员·找到车头 %s 的集结，准备加入", t["name"])
            return
        ctx["join_found"] = False
        logger.info("成员·暂无指定车头的可加入集结，继续等 (%s/%s)", n, cap)

    def _click_join(self, ctx):
        # 点目标行的「+」-> 打开「创建部队」弹窗（用户实机确认 2026-09-11：
        # 加入仍需 创建部队→行军 两步）
        if ctx.get("target_click"):
            self._handle.click(*ctx["target_click"])
            logger.info("成员·点击加入集结")

    def _form_troop(self, ctx):
        # 部队已在目标集结中：点「+」弹的是「部队替换」确认而非创建部队
        # （2026-09-13 实机 mumu0）。不替换 —— 被替换部队会白回城还多烧
        # 一次行动力，直接视为已加入，走 VERIFY_JOINED 回读橙「替换」确认
        if self._find("replace_popup"):
            self._handle.click(1500, 170)
            ctx["already_joined"] = True
            logger.info("成员·部队已在目标集结中，跳过重复加入")
            return
        # 「+」点击后（面板关闭、地图跳转）出现的是派遣队列侧栏展开态 +
        # 「创建部队」引导气泡（2026-09-12 实机连拍实锤）：真正的创建部队
        # 表单要点气泡里的蓝色「创建部队」按钮才出现，之后才能点行军。
        # 气泡不在（游戏某些入口直接给表单）就只浪费 ~2s 重试，不影响。
        if self._click_retry("join_create_btn", attempts=2):
            logger.info("成员·点击「创建部队」气泡按钮")
        # 只等待创建部队弹窗的行军按钮出现；不点预设槽位、不点兵种
        # 图标 —— 使用游戏默认兵队（用户要求 2026-09-09）
        ctx["form_open"] = self._wait_for("march_btn", timeout=15.0)
        if ctx["form_open"]:
            logger.info("成员·创建部队弹窗已打开")

    def _launch(self, ctx):
        # 点行军，默认部队填兵出发；成功标志是目标行按钮从绿「+」变成
        # 橙「替换」
        ctx["marched"] = self._click_retry("march_btn", attempts=3)
        if ctx["marched"]:
            logger.info("成员·点击行军，填兵出发")

    def _verify_join(self, ctx):
        # 行军点击后创建部队弹窗关闭、战争列表也已关（「+」点击会关面板）：
        # 先重开列表再看目标行按钮是否变成橙「替换」——面板不开 swap_btn
        # 永远不可见，会把成功误判为失败
        if self._find("ap_refill"):
            # 行军点击弹出「行动力补充」（2026-09-18 实机 run9 86/140）：
            # 行军根本没发出去，补体力后本轮按加入未生效回流重试
            if not self._refill_ap():
                self._handle.click(1638, 120)
        if not self._find("war_title"):
            self._click_retry("alliance_btn")
        ctx["joined"] = self._wait_for("swap_btn", timeout=6.0)
        # 账本写入点：橙「替换」出现 = 填兵确实发出去了。上面的
        # ap_refill 分支是「行军根本没发出去」，不写账本
        if ctx["joined"] and self._ledger is not None:
            self._ledger.mark_troops_out(self._char_id)
            self._ledger.mark_fill_done(self._char_id)

    def _join_missed(self, ctx):
        # 「+」/行军点击未生效或表单没出来：重开列表再找。必须清掉上一轮
        # 的匹配结果——FIND_JOIN 的 CLICK_JOIN 边 guard 只看 join_found，
        # 不清就会带陈旧 target_click 无限点击（2026-09-11 实机事故：
        # 两台各空转 40+ 轮、计数器全部冻结、永不重算）；顺手点一下空地，
        # 关掉可能残留的弹窗/地图选中，避免遮挡后续的联盟旗帜。
        ctx["join_found"] = False
        ctx["target_click"] = None
        ctx["panel_open"] = False   # 面板可能已被「+」点击带走，回 _open_war 重查
        self._handle.click(960, 300)
        logger.warning("成员·加入未生效，重开战争列表重试")

    def _exhausted(self, ctx):
        # 重试耗尽：置失败标记。fail_reason 由 WorkerRunner 在终态的
        # status_update payload 中带出；冷却重建后的 SM 自动重试新一轮。
        ctx["failed"] = True
        ctx["fail_reason"] = "no_rally_found"
        logger.warning("成员·重试耗尽，本轮放弃填兵")

    def is_terminal(self) -> bool:
        return self.current == "END"
