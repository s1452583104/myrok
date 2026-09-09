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
    name: str


class CharacterConfig(BaseModel):
    id: str
    name: str
    role: RoleEnum
    target_level: int = Field(ge=1, le=10)
    march_preset: int = Field(ge=1, le=5)
    march_troop_types: list[Literal["infantry", "cavalry", "archer"]]
    fill_target_leaders: list[FillLeader] = []

    @field_validator("march_troop_types")
    @classmethod
    def _not_empty(cls, v):
        if not v:
            raise ValueError("march_troop_types must be non-empty")
        return v


class InstanceConfig(BaseModel):
    id: str
    name: str = ""
    mumu_index: int | None = None
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
    anti_detection: AntiDetectionConfig = Field(default_factory=AntiDetectionConfig)


class RootConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    instances: list[InstanceConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _cross_checks(self):
        inst_ids = [i.id for i in self.instances]
        if len(inst_ids) != len(set(inst_ids)):
            raise ValueError("Duplicate instance ids")
        char_ids = [c.id for i in self.instances for c in i.characters]
        if len(char_ids) != len(set(char_ids)):
            raise ValueError("Duplicate character ids")
        if not any(c.role in (RoleEnum.LEADER, RoleEnum.EITHER)
                   for i in self.instances for c in i.characters):
            raise ValueError("Config has no leader/either character")
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
                        target = by_key.get((t.instance, t.name))
                        if target is None:
                            raise ValueError(
                                f"Character {c.name}: fill target ({t.instance}, {t.name}) 不存在")
                        if target.role not in (RoleEnum.LEADER, RoleEnum.EITHER):
                            raise ValueError(
                                f"Character {c.name}: fill target {t.name} 不是 leader/either")
        return self


def load_config(path: Path) -> RootConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return RootConfig.model_validate(raw)
