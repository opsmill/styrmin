from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class GenericBlock(ABC):
    """A generic renderable block in the kubernetes custom resource definition."""

    @abstractmethod
    def render_value(self) -> Any: ...


@dataclass
class KeyedBlock(GenericBlock):
    """A block with a key in the kubernetes custom resource definition.

    The key is used as the key in the dictionary when rendering the block.
    """

    _key: str

    @property
    def key(self) -> str:
        return self._key

    def render(self) -> dict[str, Any]:
        return {self.key: self.render_value()}


@dataclass
class TerminalBlock(GenericBlock):
    """A block with a terminal value in the kubernetes custom resource definition."""

    value: Any

    def render_value(self) -> Any:
        return self.value
