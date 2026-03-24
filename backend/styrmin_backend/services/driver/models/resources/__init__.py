from .actions import ActionsSpec
from .code import ActionsCode
from .driver import DriverSpec

DriverResource = ActionsSpec | DriverSpec | ActionsCode | str
