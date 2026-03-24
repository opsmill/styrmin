from dataclasses import dataclass, field

from .base import KeyedBlock, TerminalBlock


@dataclass
class MetadataBlock(KeyedBlock): ...


@dataclass
class Name(MetadataBlock, TerminalBlock):
    _key: str = field(init=False, default="name")
