from .code import ActionsCode
from .driver import DriverSpec

DriverResource = DriverSpec | ActionsCode | str
