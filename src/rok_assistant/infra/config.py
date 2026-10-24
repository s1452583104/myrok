from __future__ import annotations
import re
from enum import Enum
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from .anti_detection import AntiDetectionConfig
from .logger import get_logger

logger = get_logger(__name__)


class RoleEnum(str, Enum):
    LEADER = "leader"
    MEMBER = "member"
    EITHER = "either"


class AppMode(str, Enum):
    """软件模式。值用于内部标识（ASCII），中文标签见 MODE_LABELS。"""
    ZHAIDUO = "zhaiduo"
    GEM = "gem"
    QUIZ = "quiz"


# 中文标签放这里而不是 gui/labels.py，跟 RAIDER_LABEL 走同一先例：它同时被
# GUI（导航项、页头）和协调器（拒绝启动的报错）用到，跨层共用的中文文案在
# 本仓库放 config.py。
MODE_LABELS = {
    AppMode.ZHAIDUO: "寨多多模式",
    AppMode.GEM: "宝石模式",
    AppMode.QUIZ: "答题模式",
}

# 已实现的模式。GuiController.start() 与 ModePage 都读它——**只有这一处**
# 决定「界面上哪些模式可点」。加模式时改这里 + MODE_LABELS，别去改按钮。
IMPLEMENTED_MODES = frozenset({AppMode.ZHAIDUO, AppMode.GEM, AppMode.QUIZ})


class FillLeader(BaseModel):
    instance: str
    name: str = Field(min_length=1)


# 搜索目标等级上限（2026-10-04 用户要求）：按**配置顺序**依次搜，每级
# 连搜 5 次无结果就换下一级，绕完一圈（回到第一个之前）放弃本轮。
# 为什么是 3：再多也不会用上——附近的城寨等级就那么几档，列表越长
# 一圈的代价越大（每级 5 次全量重搜 ≈ 40s）。
MAX_TARGET_LEVELS = 3


# 目标城寨等级的合法范围（2026-10-13：11–15 级寨子上线）。
#
# 注意别和上面那个 MAX_TARGET_LEVELS 看串了：**S 结尾的是「最多勾几个」
# （=3），不带 S 的是「最大是几级」（=15）**。两个名字只差一个字母，改这两
# 块代码时先确认自己在改哪一个。
#
# 1–10 与 11–15 是**两个互斥的区间**（区间由账号所在大地图决定，程序不需要
# 切换），不是一根连续滑条。所以「同一次搜索里混选两个区间」没有意义：面板
# 同一时刻只能停在其中一个区间上，另一个区间里的等级根本搜不到。
MIN_TARGET_LEVEL = 1
MAX_TARGET_LEVEL = 15
RANGE_BOUNDARY = 10          # 1..10 | 11..15 的分界


def level_range(lv: int) -> tuple[int, int]:
    """该等级所属区间的 (下界, 上界)：1–10 → (1, 10)；11–15 → (11, 15)。

    区间在本次改动里同时出现在三处（校验互斥、盲降降到底、跨区间的
    缓存/回读判断），所以给它一个名字，而不是在三处各写一遍 `if lv > 10`。
    """
    if lv <= RANGE_BOUNDARY:
        return (MIN_TARGET_LEVEL, RANGE_BOUNDARY)
    return (RANGE_BOUNDARY + 1, MAX_TARGET_LEVEL)

# 「劫掠者城寨」哨兵值（2026-10-11 活动第二阶段）。
#
# 它是一类**不分等级**的特殊寨子：搜索面板上多一个「劫掠者城寨」页签，
# 切过去以后**没有等级行**（实测该页 OCR 只有描述文字 + 搜索按钮），
# 集结流程与普通城寨完全一致（详情弹窗 → 红集结 → …）。
#
# 为什么用哨兵值而不是新加一个 `target_raider: bool` 字段：搜索目标在
# 语义上就是**一个有序列表**（先搜第一个，搜不到换下一个），劫掠者城寨
# 只是列表里的一种取值。加字段会立刻产生「两个字段互相矛盾」的组合
# （true + 非空 levels 算哪个？），还得让 target_levels 允许为空、
# 从而废掉「不能为空」这条既有不变量和它的测试。用 0 则天然互斥：
# 它就是列表里的一个元素，`[0]` 与 `[6, 5]` 不可能同时成立。
#
# 0 这个取值不可能与等级冲突（等级是 1..15），校验里额外要求它**只能
# 单独出现**——「劫掠者寨子 + 某级城寨」的混合搜索没意义：劫掠者城寨
# 没有等级，搜不到时换到普通等级等于换了一类目标，用户要的是二选一。
RAIDER_TARGET = 0

# 有序行军预设列表上限（2026-10-09）：与 MAX_TARGET_LEVELS 同理——列表越长，
# 每个预设都要跑一遍「点槽 + 确认 selected_preset_N 高亮」的代价越大。
MAX_MARCH_PRESETS = 3


RAIDER_LABEL = "劫掠者寨子"


def target_short(v: int) -> str:
    """列表里的紧凑写法：等级就是数字（`7`），劫掠者写中文。

    给表格列 / 校验文案里的「一串目标」用。哨兵值 0 不能原样摊给用户看
    （那读起来像「0 级」），但也不能一律写成 `7 级`——`8→7→6` 那种紧凑
    写法是既有的界面约定。
    """
    return RAIDER_LABEL if v == RAIDER_TARGET else str(v)


def target_label(v: int) -> str:
    """带单位的写法（日志 / 校验文案）：`7 级` / `劫掠者寨子`。"""
    return RAIDER_LABEL if v == RAIDER_TARGET else f"{v} 级"


def levels_repr(vals) -> str:
    """角色自己的目标列表在文案里的写法：`[7, 6]` / `[劫掠者寨子]`。"""
    return "[" + ", ".join(target_short(v) for v in vals) + "]"


class MarchPreset(BaseModel):
    """一个行军预设槽 + 该槽要点的兵种。

    troops 是列表而非单值：创建部队表单允许同时勾多个兵种，车头
    `_form_troop` 也是逐个点 `troop_*`（见 leader_sm），GUI 因此用 3 个
    复选框而不是单选下拉。
    """
    preset: int = Field(ge=1, le=5)
    troops: list[Literal["infantry", "cavalry", "archer"]]

    @field_validator("troops")
    @classmethod
    def _troops_not_empty(cls, v):
        if not v:
            raise ValueError("march_presets 每项至少要一个兵种")
        return v


class CharacterConfig(BaseModel):
    id: str
    name: str = Field(min_length=1)
    role: RoleEnum
    # 有序搜索列表：先搜第 1 个，搜不到换第 2 个……绕完一圈放弃本轮。
    # 顺序**完全自由**（用户明确要求，例如 6→4→5 合法），不强制降序；
    # 下限即列表中的最小值，不另设 min_level 字段。
    # 取值 1..15 = 普通城寨等级；`RAIDER_TARGET`(0) = 劫掠者寨子（不分等级，
    # 且只能单独出现，见 `_check_levels`）。
    target_levels: list[int]
    # 有序行军预设列表（2026-10-09）：第一个确认不了高亮就换第二个，
    # 行序即优先级。空列表时由下面的 _migrate_march 从旧字段合成。
    march_presets: list[MarchPreset] = []
    # 旧字段（2026-10-09 起降级为「只读兼容」）：GUI 不再写，读侧仍认。
    # 保留是为了不逼用户手改 config.yaml——已有配置照旧能加载。
    march_preset: int | None = Field(default=None, ge=1, le=5)
    march_troop_types: list[Literal["infantry", "cavalry", "archer"]] = []
    fill_target_leaders: list[FillLeader] = []

    @field_validator("target_levels")
    @classmethod
    def _check_levels(cls, v):
        if not v:
            raise ValueError("target_levels 不能为空：至少选一个城寨等级")
        if RAIDER_TARGET in v:
            # 劫掠者寨子不分等级 → 「它 + 某个等级」这种混合列表没有意义
            # （见 RAIDER_TARGET 的注释）。这里连 3 个上限都一并挡掉：
            # 合法的劫掠者配置有且只有 [RAIDER_TARGET] 这一种。
            if len(v) > 1:
                raise ValueError(
                    f"target_levels 选了劫掠者寨子（{RAIDER_TARGET}）时"
                    f"不能再选其他等级（收到 {v}）")
            return v
        if len(v) > MAX_TARGET_LEVELS:
            raise ValueError(
                f"target_levels 最多 {MAX_TARGET_LEVELS} 个（收到 {len(v)} 个）")
        for lv in v:
            if not MIN_TARGET_LEVEL <= lv <= MAX_TARGET_LEVEL:
                raise ValueError(
                    f"target_levels 取值须在 {MIN_TARGET_LEVEL}..{MAX_TARGET_LEVEL}"
                    f"（收到 {lv}）")
        if len(set(v)) != len(v):
            raise ValueError(f"target_levels 有重复等级：{v}")
        # 区间互斥：与 RAIDER_TARGET 那条并列的第二条互斥规则。按区间下界
        # 去重后还剩两种，就说明混选了两个区间。
        if len({level_range(lv)[0] for lv in v}) > 1:
            raise ValueError(
                f"target_levels 不能混选两个等级区间"
                f"（{MIN_TARGET_LEVEL}–{RANGE_BOUNDARY} 与 "
                f"{RANGE_BOUNDARY + 1}–{MAX_TARGET_LEVEL}）："
                f"搜索面板同一时刻只能停在一个区间上（收到 {v}）")
        return v

    @model_validator(mode="after")
    def _migrate_march(self):
        """旧字段 → march_presets 的兼容迁移与校验。

        三件事：(1) 新字段空时用旧字段合成一条；(2) 两者都空 = 配置错误
        （原来 march_preset/march_troop_types 是必填，不能因为改字段就
        变成可缺省）；(3) 新字段自己的三条约束（项数 / 预设号不重复）。
        """
        if not self.march_presets:
            if self.march_preset is None or not self.march_troop_types:
                raise ValueError(
                    "必须配置 march_presets（或旧的 march_preset + "
                    "march_troop_types）")
            self.march_presets = [MarchPreset(preset=self.march_preset,
                                              troops=list(self.march_troop_types))]
        if len(self.march_presets) > MAX_MARCH_PRESETS:
            raise ValueError(
                f"march_presets 最多 {MAX_MARCH_PRESETS} 项"
                f"（收到 {len(self.march_presets)} 项）")
        slots = [p.preset for p in self.march_presets]
        if len(set(slots)) != len(slots):
            raise ValueError(f"march_presets 预设号重复：{slots}")
        return self


class InstanceBase(BaseModel):
    """一个模拟器实例的公共字段与校验。

    抽出来是因为宝石模式也要「一台模拟器一个账号」，字段与校验一字不差；
    复制一份的下场是两份 `_instance_checks` 慢慢漂移（PROGRESS 已知问题 16
    就是同一类漂移）。**只放两模式共有的东西**：mumu/adb 二选一。
    """

    id: str
    name: str = ""
    mumu_index: int | None = Field(default=None, ge=0)
    adb_address: str = ""
    window_title_pattern: str = ""  # Win32 备用路线；ADB 路线用不到

    @model_validator(mode="after")
    def _instance_checks(self):
        if self.mumu_index is None and not self.adb_address:
            raise ValueError(f"Instance {self.id}: mumu_index 或 adb_address 必须填一个")
        if self.mumu_index is not None and self.adb_address:
            raise ValueError(f"Instance {self.id}: mumu_index 与 adb_address 只能填一个")
        return self


class InstanceConfig(InstanceBase):
    characters: list[CharacterConfig]

    @model_validator(mode="after")
    def _character_names_unique(self):
        # leader/either 要求在 RootConfig 层校验：member-only 实例可跨实例 fill leader
        names = [c.name for c in self.characters]
        if len(names) != len(set(names)):
            raise ValueError(f"Instance {self.id} has duplicate character names")
        return self


class NoRoleCharacterConfig(BaseModel):
    """无分工模式的角色（宝石 / 答题共用）。

    **刻意没有 role / target_levels / march_presets**：这两种模式一台模拟器
    一个号、流程固定，既没有分工也没有预设槽。把这些字段搬过来只会让
    「填了但不生效」变成可能——用户配了 role: leader 却什么都不发生，
    比字段不存在更难查。
    """

    id: str
    name: str = Field(min_length=1)


class NoRoleInstanceConfig(InstanceBase):
    characters: list[NoRoleCharacterConfig]

    @model_validator(mode="after")
    def _one_character(self):
        if len(self.characters) != 1:
            raise ValueError(
                f"Instance {self.id}: 该模式一台模拟器恰好 1 个角色"
                f"（收到 {len(self.characters)} 个）")
        return self


# 别名：config.yaml 与既有测试零改动。**不要**再写第二套类定义。
GemCharacterConfig = NoRoleCharacterConfig
GemInstanceConfig = NoRoleInstanceConfig
QuizInstanceConfig = NoRoleInstanceConfig


class ModeConfig(BaseModel):
    """有分工模式的配置骨架（当前由 ZhaiduoConfig 继承并加严校验）。"""
    instances: list[InstanceConfig] = Field(default_factory=list)


class ZhaiduoConfig(ModeConfig):
    """寨多多模式：唯一实现了的模式，所以它的校验最严。

    **校验跟着数据走，不跟着模式走**：原来挂在 RootConfig 上的 _cross_checks
    整块搬到这里，因为「至少一个 leader/either」「填兵目标互相指向」这些规则
    说的是**角色之间**的关系，而角色只存在于某个模式里。宝石/答题的角色没有
    role 概念，硬套「至少一个 leader」会让它们当场加载失败。
    """
    instances: list[InstanceConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _cross_checks(self):
        inst_ids = [i.id for i in self.instances]
        if len(inst_ids) != len(set(inst_ids)):
            raise ValueError("实例 id 重复")
        char_ids = [c.id for i in self.instances for c in i.characters]
        if len(char_ids) != len(set(char_ids)):
            raise ValueError("角色 id 重复")
        if not any(c.role in (RoleEnum.LEADER, RoleEnum.EITHER)
                   for i in self.instances for c in i.characters):
            raise ValueError("整个配置至少需要 1 个 leader/either 角色")
        by_key = {(i.id, c.name): c for i in self.instances for c in i.characters}
        for i in self.instances:
            for c in i.characters:
                if c.role == RoleEnum.LEADER and c.fill_target_leaders:
                    raise ValueError(
                        f"Character {c.name}: leader 不能配置 fill_target_leaders")
                if c.role in (RoleEnum.MEMBER, RoleEnum.EITHER):
                    if not c.fill_target_leaders:
                        raise ValueError(
                            f"Character {c.name}: member/either 必须配置 fill_target_leaders")
                    for t in c.fill_target_leaders:
                        if t.instance == i.id and t.name == c.name:
                            raise ValueError(
                                f"Character {c.name}: fill target 不能指向自己")
                        target = by_key.get((t.instance, t.name))
                        if target is None:
                            raise ValueError(
                                f"Character {c.name}: fill target ({t.instance}, {t.name}) 不存在")
                        if target.role not in (RoleEnum.LEADER, RoleEnum.EITHER):
                            raise ValueError(
                                f"Character {c.name}: fill target {t.name} 不是 leader/either")
        return self


class GemConfig(BaseModel):
    """宝石模式的专属配置（spec §4.2）。

    字段取值只在这里校验上下界；**具体配几级 / 等几分钟不写进文档**，
    要看实际值直接读 config.yaml。
    """

    # 队列图标数 >= 这个值 = 派满了，去等（spec §6.2）
    queue_limit: int = Field(default=5, ge=1, le=7)
    # 扫图会话轮数上限（一轮 = 螺旋扫一遍 + 沿途派兵）
    max_rounds: int = Field(default=10, ge=1)
    # 回字形向外扩几圈
    scan_rings: int = Field(default=3, ge=1)
    # 每步拖拽距离与时长
    scan_drag_px: int = Field(default=800, ge=100)
    scan_drag_ms: int = Field(default=500, ge=100)
    # 队列满后的等待下限/上限（分钟）
    idle_wait_min: float = Field(default=20.0, gt=0)
    idle_wait_max: float = Field(default=30.0, gt=0)
    instances: list[GemInstanceConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self):
        if self.idle_wait_max < self.idle_wait_min:
            raise ValueError(
                f"gem.idle_wait_max（{self.idle_wait_max}）不能小于"
                f"idle_wait_min（{self.idle_wait_min}）")
        ids = [i.id for i in self.instances]
        if len(ids) != len(set(ids)):
            raise ValueError("gem 实例 id 重复")
        char_ids = [c.id for i in self.instances for c in i.characters]
        if len(char_ids) != len(set(char_ids)):
            raise ValueError("gem 角色 id 重复")
        return self


class QuizLLMConfig(BaseModel):
    """答题模式的大模型兜底（OpenAI 兼容接口）。

    `api_key` 是明文落在 config.yaml 里的（绿色包里用户自己保管）；
    `enabled=False` 时**完全不发网络请求**，题库外直接随机。
    """

    enabled: bool = False
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    api_key: str = ""
    timeout_s: float = Field(default=8.0, gt=0)


class QuizConfig(BaseModel):
    """答题模式的专属配置（spec §5）。

    **不继承 ModeConfig**：那是寨多多专属的 `instances: list[InstanceConfig]`
    （min_length=1 + leader/member 交叉校验），答题套上去会当场加载失败。
    与 GemConfig 一样直接继承 BaseModel，自己写 id 唯一性校验。

    字段取值只在这里校验上下界；**具体配几轮/几分钟不写进文档**，
    要看实际值直接读 config.yaml。
    """

    instances: list[QuizInstanceConfig] = Field(default_factory=list)
    max_rounds: int = Field(default=3, ge=1)              # 跑满这么多轮自动收工
    fuzzy_threshold: float = Field(default=0.72, ge=0.0, le=1.0)  # 题库模糊匹配阈值
    verify_delay: float = Field(default=1.2, ge=0.0)      # 点完选项后多久截图看绿色
    min_green_ratio: float = Field(default=0.55, ge=0.0, le=1.0)
    round_cooldown_min: float = Field(default=10.0, ge=0.0)
    parse_retries: int = Field(default=2, ge=1)           # 同一题最多读几次再中止
    auto_click: bool = True                               # false = 只记日志不点击
    # 从地图点进答题活动页的**固定落点序列**（像素），真机探针
    # tools/quiz_entry_probe.py 测出来后填进来。空列表 = 只靠屏幕文字
    # （进入 / 习题演练 / 活动）找入口；找不到就报 quiz_entry_missing。
    entry_taps: list[tuple[int, int]] = Field(default_factory=list)
    llm: QuizLLMConfig = Field(default_factory=QuizLLMConfig)

    @model_validator(mode="after")
    def _checks(self):
        ids = [i.id for i in self.instances]
        if len(ids) != len(set(ids)):
            raise ValueError("quiz 实例 id 重复")
        char_ids = [c.id for i in self.instances for c in i.characters]
        if len(char_ids) != len(set(char_ids)):
            raise ValueError("quiz 角色 id 重复")
        return self


class AppConfig(BaseModel):
    screen_width: int = 1920
    screen_height: int = 1080
    locale: str = "zh-CN"
    mumu_manager_path: str = ""   # 全局；MuMuManager.exe 完整路径
    adb_path: str = "adb"         # 全局；adb.exe 完整路径
    log_dir: Path = Path("./logs")
    template_dir: Path = Path("./templates")
    # YOLO 权重路径（可选）。配置后每个模板 id 装配 Chain(模板匹配→YOLO 兜底)：
    # 校准过的模板先行，YOLO 只在模板未命中时接住动画帧/背景偏移。
    # 未配置=纯模板匹配（与旧版行为一致）
    yolo_model: Path | None = None
    # fill_<名字> 模板未命中时的 OCR 兜底（RapidOCR，账号无关名字识别）
    ocr_name_fallback: bool = True
    # 每个角色最多完成多少轮（开集结+填兵+返城算一轮）后自动停止
    max_rounds: int = Field(default=10, ge=1)
    # 连续多少轮以失败终态（no_fortress_found/locked_fortress/no_rally_found）
    # 后自动停止；连续 step 异常则按此数的 2 倍计（异常不走终态）
    max_consecutive_failures: int = Field(default=3, ge=1)
    # 角色卡片的显示模式：image = 图文（截屏缩略图 + 日志），
    # text = 文字（不展示截屏，卡片变矮、一屏放更多卡）。
    # 主界面页头的分段开关改它，落盘走 set_card_view()（只动这一行）。
    card_view: Literal["text", "image"] = "image"
    anti_detection: AntiDetectionConfig = Field(default_factory=AntiDetectionConfig)


# 老格式（顶层 instances）的可操作提示。config.py 的校验器与 selftest 的诊断共用
# 同一句，避免两处文案漂移。
LEGACY_FLAT_INSTANCES_HINT = (
    "配置格式已更新：instances 现在挂在 zhaiduo 模式下。"
    "请删除 config.yaml 后重启，程序会从 config.example.yaml 重新生成一份。")


class RootConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    zhaiduo: ZhaiduoConfig
    gem: GemConfig = Field(default_factory=GemConfig)
    quiz: QuizConfig = Field(default_factory=QuizConfig)

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_flat_instances(cls, data):
        """老格式（顶层 instances）→ 可操作的报错。

        pydantic 默认忽略多余键，直接后果是用户看到一句光秃秃的
        `zhaiduo / Field required`，不知道该干什么。**这是报错，不是迁移**：
        经确认不做自动迁移，老配置报错、用户重配。

        判据是「顶层出现 instances 就报错」——不再要求 zhaiduo 缺席。半迁移
        配置（顶层 instances 与 zhaiduo 同时存在）本会被 pydantic 静默丢弃顶层
        那段、加载成功；对「硬报错、不迁移」的设计来说，静默丢数据比报错更糟。

        必须放在 RootConfig 的 mode="before" 里，不能挂在 load_config() 上——
        GuiController.load_config 自己走 model_validate，不经过 load_config()。
        """
        if isinstance(data, dict) and "instances" in data:
            raise ValueError(LEGACY_FLAT_INSTANCES_HINT)
        return data

    def instances_for(self, mode: AppMode) -> list[InstanceBase]:
        """该模式的实例列表。模式 → 配置段的映射只有这一处。

        返回类型是**公共基类**：寨多多给 `InstanceConfig`、宝石给
        `GemInstanceConfig`，两者是兄弟，没有共同的子类关系。
        """
        return getattr(self, mode.value).instances


def find_level_collisions(instances: list[InstanceConfig]) -> list[str]:
    """找出「可能搜到同一寨子」的角色对，返回人类可读的告警文案。

    为什么是告警而不是校验错误：撞车不会让流程出错，只会白烧一次搜索
    ——车头被游戏静默拒绝后按 rally_rejected 降级、不计失败、转填兵。
    所以这里只提醒，不拦启动。

    判定条件（三者同时满足）：
      1. 两个角色 role ∈ {leader, either}（member 不开车）
      2. target_levels 两个列表**有交集**（2026-10-04：改多选后不再比
         「相等」——只要有一个共同等级，两号就可能在那一级搜到同一寨子）
      3. 至少一个方向填对方（互为填兵目标说明两号在同一联盟协同作战；
         不同联盟各自为战则不会互相干扰）

    注意第 3 条只要求**任一方向**：A 填 B 而 B 不填 A 时同样会撞车，
    只查「互为」会漏掉这种配置。
    """
    cars = [(i, c) for i in instances for c in i.characters
            if c.role in (RoleEnum.LEADER, RoleEnum.EITHER)]
    out: list[str] = []
    for idx, (inst_a, a) in enumerate(cars):
        for inst_b, b in cars[idx + 1:]:
            shared = sorted(set(a.target_levels) & set(b.target_levels))
            if not shared:
                continue
            related = any(t.instance == inst_b.id and t.name == b.name
                          for t in a.fill_target_leaders) or \
                any(t.instance == inst_a.id and t.name == a.name
                    for t in b.fill_target_leaders)
            if not related:
                continue
            levels = "、".join(target_label(lv) for lv in shared)
            out.append(
                f"[配置] {a.name}（{levels_repr(a.target_levels)}）与 {b.name}"
                f"（{levels_repr(b.target_levels)}）都含 {levels} 且至少"
                f"一方填对方：可能搜到同一寨子，撞车时后发者被游戏静默拒绝"
                f"（已降级不计失败，但白烧一次搜索）。建议错开等级。")
    return out


def load_config(path: Path) -> RootConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return RootConfig.model_validate(raw)


# ---------------- 单键行内改写 ----------------
# 为什么不用 yaml.safe_dump 整份重写：config.yaml 是用户手改的文件，里面
# 有一整块解释 YOLO 权重取舍的注释（还有他自己的排版）。safe_dump 会把注释
# 全部清掉——切一下显示模式就删掉用户的注释，代价和收益完全不成比例。
# 配置对话框保存时就是这个行为，那是历史包袱，不该再扩大。

_APP_HEAD_RE = re.compile(
    r"^(?P<indent>[ \t]*)app[ \t]*:[ \t]*(?:#.*)?(?P<eol>\r?\n)?$")
_CARD_VIEW_LINE_RE = re.compile(
    r"^(?P<indent>[ \t]*)card_view[ \t]*:(?P<tail>[^\n\r]*)")
_DEFAULT_INDENT = 2


def set_card_view(path: Path, value: str) -> bool:
    """把 `app.card_view` 写进 config.yaml，**只动这一行**。

    成功返回 True。文件解析不了、找不到 `app:` 段、或改写后回读值不符，
    一律返回 False **且不碰文件**——改坏用户的配置比不保存严重得多。
    调用方在 False 时保留本次会话内的切换生效，只是不持久化。
    """
    if value not in ("text", "image"):
        return False
    try:
        text = path.read_text(encoding="utf-8")
        raw = yaml.safe_load(text)
    except (OSError, yaml.YAMLError):
        logger.warning("读取/解析 %s 失败，card_view 仅本次会话生效", path)
        return False
    if not isinstance(raw, dict):
        logger.warning("%s 顶层不是映射，card_view 仅本次会话生效", path)
        return False

    new_text = _rewrite_app_key(text, "card_view", value)
    if new_text is None:
        logger.warning("%s 里没有顶层 app: 段，card_view 仅本次会话生效", path)
        return False

    # **先回读确认再写盘**：写坏再回滚，不如压根不写。
    try:
        back = yaml.safe_load(new_text)
    except yaml.YAMLError:
        logger.warning("改写后的 YAML 解析失败，未写入 %s", path)
        return False
    app_node = back.get("app") if isinstance(back, dict) else None
    if not isinstance(app_node, dict) or app_node.get("card_view") != value:
        logger.warning("改写未落到 app.card_view，未写入 %s", path)
        return False

    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError:
        logger.warning("写入 %s 失败，card_view 仅本次会话生效", path)
        return False
    return True


def _rewrite_app_key(text: str, key: str, value: str) -> str | None:
    """在文本里定位顶层 `app:` 段，替换/插入 `key: value` 那一行。

    返回新文本；找不到 `app:` 段返回 None。不解析、不重排——只认行。
    """
    lines = text.splitlines(keepends=True)

    head = None
    for i, line in enumerate(lines):
        m = _APP_HEAD_RE.match(line)
        if m and not m.group("indent"):        # 只认顶层 app:（缩进过的不是它）
            head = i
            break
    if head is None:
        return None

    # 段范围：app: 之后，直到第一个顶格的非空非注释行
    end = head + 1
    key_indent = None
    while end < len(lines):
        body = lines[end].strip()
        if not body or body.startswith("#"):
            end += 1
            continue
        indent = len(lines[end]) - len(lines[end].lstrip(" \t"))
        if indent == 0:
            break
        if key_indent is None:
            key_indent = indent
        end += 1

    indent = " " * (key_indent if key_indent is not None else _DEFAULT_INDENT)
    eol = "\r\n" if lines[head].endswith("\r\n") else "\n"

    for i in range(head + 1, end):
        m = _CARD_VIEW_LINE_RE.match(lines[i])
        # 只认 app 段**直接子级**的那一行：缩进更深的同名键属于别的嵌套段
        # （YAML 里它挂在上一级键下面），改它等于改错了地方。
        if not m or m.group("indent") != indent:
            continue
        # 保住行尾注释（用户可能写了「# 不要改」这类说明）
        tail_comment = re.search(r"[ \t]+#.*$", m.group("tail"))
        suffix = tail_comment.group(0) if tail_comment else ""
        lines[i] = f"{m.group('indent')}{key}: {value}{suffix}{eol}"
        return "".join(lines)

    lines.insert(head + 1, f"{indent}{key}: {value}{eol}")
    return "".join(lines)
