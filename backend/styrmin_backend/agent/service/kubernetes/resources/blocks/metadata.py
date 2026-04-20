from dataclasses import dataclass, field
from typing import Any

from .base import KeyedBlock, TerminalBlock


@dataclass
class MetadataBlock(KeyedBlock): ...


@dataclass
class Name(MetadataBlock, TerminalBlock):
    _key: str = field(init=False, default="name")


@dataclass
class Labels(MetadataBlock):
    """A metadata block for Kubernetes labels."""

    labels: dict[str, str] = field(default_factory=dict)
    _key: str = field(init=False, default="labels")

    def render_value(self) -> Any:
        return self.labels


@dataclass
class Annotations(MetadataBlock):
    """A metadata block for Kubernetes annotations."""

    annotations: dict[str, str] = field(default_factory=dict)
    _key: str = field(init=False, default="annotations")

    def render_value(self) -> Any:
        return self.annotations
