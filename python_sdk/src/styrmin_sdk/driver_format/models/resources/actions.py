from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HookKind(str, Enum):
    SETUP = "setup"
    UPGRADE = "upgrade"


class ParameterKind(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: ParameterKind
    mandatory: bool


class ActionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    location: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*\.py::[a-z_][a-zA-Z0-9_]+$")
    description: str
    hook: HookKind

    parameters: list[Parameter] = Field(default_factory=list)
    mode: Literal["pre", "core", "post"]
    image: str | None = None
