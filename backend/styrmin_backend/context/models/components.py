from typing import Any, ItemsView

from pydantic import BaseModel, ConfigDict, RootModel


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


class ComponentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: ArbitrarySectionModel
    name: str
    enabled: bool


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
