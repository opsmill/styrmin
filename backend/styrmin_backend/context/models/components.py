from typing import Any, ItemsView, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from .config import SchedulingConfig


class LabelIdentifier(RootModel):
    root: dict[str, str]

    def __getitem__(self, item: str) -> str:
        """Get an item from the components context.

        Args:
            item (str): The item key.

        Returns:
            str: The item value.
        """
        return self.root[item]

    def __contains__(self, key: str) -> bool:
        return key in self.root

    def items(self) -> ItemsView[str, str]:
        return self.root.items()

    def label_selectable(self) -> str:
        key = next(iter(self.root.keys()))
        value = next(iter(self.root.values()))
        return f"{key}={value}"


class Identifier(BaseModel):
    label: LabelIdentifier


class ArbitrarySectionModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    identifier: Identifier

    def __getitem__(self, item: Any) -> Any:
        assert self.__pydantic_extra__ is not None
        return self.__pydantic_extra__[item]


ProvenanceLevel = Literal["environment", "deployment", "component"]


class ResolvedComponentScheduling(BaseModel):
    """Per-component effective scheduling configuration plus provenance.

    ``config`` is the fully merged :class:`SchedulingConfig` for one component
    (env → deployment → component layers combined). ``provenance`` maps each
    effective field (dotted path, e.g. ``"resources.requests.cpu"``) to the
    level that contributed its final value.
    """

    model_config = ConfigDict(extra="forbid")

    config: SchedulingConfig
    provenance: dict[str, ProvenanceLevel] = Field(default_factory=dict)


class ComponentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: ArbitrarySectionModel
    name: str
    enabled: bool
    scheduling: ResolvedComponentScheduling | None = None


class ComponentsContext(RootModel):
    root: dict[str, ComponentContext]

    def __getitem__(self, item: str) -> ComponentContext:
        """Get an item from the components context.

        Args:
            item (str): The item key.

        Returns:
            ComponentContext: The item value.
        """
        return self.root[item]

    def __contains__(self, key: str) -> bool:
        return key in self.root

    def items(self) -> ItemsView[str, ComponentContext]:
        return self.root.items()
