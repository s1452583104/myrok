from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from .anti_detection import AntiDetectionConfig


class RoleEnum(str, Enum):
    LEADER = "leader"
    MEMBER = "member"
    EITHER = "either"


class FillLeader(BaseModel):
    instance: str
    name: str = Field(min_length=1)


# 搜索目标等级上限（2026-10-04 用户要求）：按**配置顺序**依次搜，每级
# 连搜 5 次无结果就换下一级，绕完一圈（回到第一个之前）放弃本轮。
# 为什么是 3：再多也不会用上——附近的城寨等级就那么几档，列表越长
# 一圈的代价越大（每级 5 次全量重搜 ≈ 40s）。
MAX_TARGET_LEVELS = 3

# 有序行军预设列表上限（2026-10-09）：与 MAX_TARGET_LEVELS 同理——列表越长，
# 每个预设都要跑一遍「点槽 + 确认 selected_preset_N 高亮」的代价越大。
MAX_MARCH_PRESETS = 3


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
        if len(v) > MAX_TARGET_LEVELS:
            raise ValueError(
                f"target_levels 最多 {MAX_TARGET_LEVELS} 个（收到 {len(v)} 个）")
        for lv in v:
            if not 1 <= lv <= 10:
                raise ValueError(f"target_levels 取值须在 1..10（收到 {lv}）")
        if len(set(v)) != len(v):
            raise ValueError(f"target_levels 有重复等级：{v}")
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


class InstanceConfig(BaseModel):
    id: str
    name: str = ""
    mumu_index: int | None = Field(default=None, ge=0)
    adb_address: str = ""
    window_title_pattern: str = ""  # Win32 备用路线；ADB 路线用不到
    characters: list[CharacterConfig]

    @model_validator(mode="after")
    def _instance_checks(self):
        if self.mumu_index is None and not self.adb_address:
            raise ValueError(f"Instance {self.id}: mumu_index 或 adb_address 必须填一个")
        if self.mumu_index is not None and self.adb_address:
            raise ValueError(f"Instance {self.id}: mumu_index 与 adb_address 只能填一个")
        # leader/either 要求在 RootConfig 层校验：member-only 实例可跨实例 fill leader
        names = [c.name for c in self.characters]
        if len(names) != len(set(names)):
            raise ValueError(f"Instance {self.id} has duplicate character names")
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
    anti_detection: AntiDetectionConfig = Field(default_factory=AntiDetectionConfig)


class RootConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
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


def find_level_collisions(config: RootConfig) -> list[str]:
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
    cars = [(i, c) for i in config.instances for c in i.characters
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
            levels = "、".join(f"{lv} 级" for lv in shared)
            out.append(
                f"[配置] {a.name}（{a.target_levels}）与 {b.name}"
                f"（{b.target_levels}）都含 {levels} 且至少"
                f"一方填对方：可能搜到同一寨子，撞车时后发者被游戏静默拒绝"
                f"（已降级不计失败，但白烧一次搜索）。建议错开等级。")
    return out


def load_config(path: Path) -> RootConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return RootConfig.model_validate(raw)
