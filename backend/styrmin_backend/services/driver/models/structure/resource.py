from enum import Enum
from pathlib import Path

from pydantic import BaseModel


class Role(str, Enum):
    """The role enum."""

    DRIVER_SPEC = "driver_spec"
    ACTIONS_SPEC = "actions_spec"
    VALUES_TEMPLATE = "values_template"
    ACTIONS_CODE = "actions_code"


class Syntax(str, Enum):
    """The syntax enum."""

    YAML = "yaml"
    JSON = "json"
    STR = "str"
    PYTHON = "python"


class ResourceFile(BaseModel):
    """A resource file of the driver directory."""

    role: Role
    optional: bool = False
    syntax: Syntax
    path: Path
