from enum import Enum

from pydantic import ConfigDict


class Kind(str, Enum):
    model_config = ConfigDict(extra="forbid")

    ApplicationDriver = "ApplicationDriver"
    ActionDefinition = "ActionDefinition"
