from enum import Enum


class WorkflowType(str, Enum):
    INTERNAL = "internal"
    USER = "user"
