from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Literal, Union
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from .anti_detection import AntiDetectionConfig


class RoleEnum(str, Enum):
    LEADER = "leader"
    MEMBER = "member"


class FillLeader(BaseModel):
    account: str
    name: str


class CharacterConfig(BaseModel):
    id: str
    name: str
    role: RoleEnum
    target_level: int = Field(ge=1, le=10)
    march_preset: int = Field(ge=1, le=5)
    march_troop_types: list[Literal["infantry", "cavalry", "archer"]]
    fill_target_leaders: Union[Literal["nearest"], list[FillLeader]] = "nearest"

    @field_validator("march_troop_types")
    @classmethod
    def _not_empty(cls, v):
        if not v:
            raise ValueError("march_troop_types must be non-empty")
        return v


class AccountConfig(BaseModel):
    id: str
    window_title_pattern: str
    characters: list[CharacterConfig]

    @model_validator(mode="after")
    def _has_leader_and_unique_names(self):
        if not any(c.role == RoleEnum.LEADER for c in self.characters):
            raise ValueError(f"Account {self.id} has no leader")
        names = [c.name for c in self.characters]
        if len(names) != len(set(names)):
            raise ValueError(f"Account {self.id} has duplicate character names")
        return self


class AppConfig(BaseModel):
    screen_width: int = 1920
    screen_height: int = 1080
    locale: str = "zh-CN"
    log_dir: Path = Path("./logs")
    template_dir: Path = Path("./templates")
    anti_detection: AntiDetectionConfig = Field(default_factory=AntiDetectionConfig)


class RootConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    accounts: list[AccountConfig] = Field(min_length=1)


def load_config(path: Path) -> RootConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return RootConfig.model_validate(raw)
