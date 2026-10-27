from abc import ABC, abstractmethod
from typing import Union, Any
from uuid import UUID

from pydantic import BaseModel, Field

from styrmin_backend.domain.models import Instance
from typing_extensions import Self

CreateReturn = Union[
    "ApplicationVersionChange",
    "ContextChange",
    "ApplicationDriverVersionChange",
]
CreateArg = Union[str, dict, UUID]
#: The most changed paths that one diff report line names; it counts the rest.
MAX_DESCRIBED_PATHS = 50


def _key_path(path: str, key: Any) -> str:  # noqa: ANN401 - any dict key
    return f"{path}.{key}" if path else str(key)


def _leaf_paths(value: Any, path: str) -> list[str]:  # noqa: ANN401
    """The dotted paths of the leaves of ``value``: its keys, never its values."""
    if isinstance(value, dict) and value:
        return [
            leaf
            for key in sorted(value, key=str)
            for leaf in _leaf_paths(value[key], _key_path(path, key))
        ]
    return [path or "<root>"]


def changed_paths(current: Any, new: Any, path: str = "") -> list[str]:  # noqa: ANN401
    """The dotted paths of the keys whose value differs between two JSON-like values.

    Names the keys, never the values, so the result can go into a log. A key
    that only one side has is named down to its leaves, and ``None`` against a
    dict counts as an empty dict: a scope that had no env vars and gets one is
    named ``...env_vars.NAME``, not ``...env_vars``.

    >>> changed_paths({"a": {"b": 1, "c": 2}, "d": 3}, {"a": {"b": 1, "c": 9}, "e": 3})
    ['a.c', 'd', 'e']
    >>> changed_paths({"env_vars": None}, {"env_vars": {"TOKEN": "x"}})
    ['env_vars.TOKEN']
    >>> changed_paths({}, {"block": {"config": {"A": "x"}, "orphaned": False}})
    ['block.config.A', 'block.orphaned']
    >>> changed_paths({"env_vars": None}, {"env_vars": {}})
    ['env_vars']
    """
    current_map = {} if current is None else current
    new_map = {} if new is None else new
    if isinstance(current_map, dict) and isinstance(new_map, dict):
        paths: list[str] = []
        for key in sorted(current_map.keys() | new_map.keys(), key=str):
            key_path = _key_path(path, key)
            if key in current_map and key in new_map:
                paths.extend(changed_paths(current_map[key], new_map[key], key_path))
            else:
                only = current_map[key] if key in current_map else new_map[key]
                paths.extend(_leaf_paths(only, key_path))
        if paths or current == new:
            return paths
    return [] if current == new else [path or "<root>"]


class DiffEntry(BaseModel, ABC):
    """Base class for diff entries."""

    @classmethod
    @abstractmethod
    def create(cls, current_value: Any, new_value: Any) -> CreateReturn:
        """Set the current value of the diff."""
        pass

    @abstractmethod
    def describe(self) -> str:
        """What changed, for the logs; never a value that can be a secret."""


class ApplicationVersionChange(DiffEntry):
    """Version change diff."""

    current_value: str
    new_value: str

    def describe(self) -> str:
        return f"application version {self.current_value} -> {self.new_value}"

    @classmethod
    def create(cls, current_value: str, new_value: str) -> Self:
        """Set the current value of the diff."""
        if isinstance(current_value, str) and isinstance(new_value, str):
            return cls(
                current_value=current_value,
                new_value=new_value,
            )
        else:
            raise ValueError("Current value must be a string.")


class ApplicationDriverVersionChange(DiffEntry):
    """Application driver version change diff."""

    current_value: UUID
    new_value: UUID

    def describe(self) -> str:
        return f"driver version {self.current_value} -> {self.new_value}"

    @classmethod
    def create(cls, current_value: UUID, new_value: UUID) -> Self:
        """Set the current value of the diff."""
        if isinstance(current_value, UUID) and isinstance(new_value, UUID):
            return cls(
                current_value=current_value,
                new_value=new_value,
            )
        else:
            raise ValueError("Current and New value must be a UUID.")


class ContextChange(DiffEntry):
    """Context change diff.

    The contexts hold env var values and parameters, which can be secrets, so
    ``repr()`` leaves them out (#573).
    """

    current_value: dict = Field(repr=False)
    new_value: dict = Field(repr=False)

    def describe(self) -> str:
        paths = changed_paths(self.current_value, self.new_value)
        shown = ", ".join(paths[:MAX_DESCRIBED_PATHS]) or "no key"
        if len(paths) > MAX_DESCRIBED_PATHS:
            shown += f" and {len(paths) - MAX_DESCRIBED_PATHS} more"
        return f"context changed at {shown}"

    @classmethod
    def create(cls, current_value: dict, new_value: dict) -> Self:
        """Set the current value of the diff."""
        if isinstance(current_value, dict) and isinstance(new_value, dict):
            return cls(
                current_value=current_value,
                new_value=new_value,
            )
        else:
            raise ValueError("Current value must be a dictionary.")


class Diff(BaseModel):
    instance: Instance


class InstanceCreation(Diff):
    """The current instance is None and the new one is not."""


class InstanceDeletion(Diff):
    """The current instance is not None and the new one is."""


class InstanceUpdate(Diff):
    diffs: list[DiffEntry]


class DiffReport(BaseModel):
    """Diff report.

    ``raw`` holds DeepDiff's changes with their values, so ``repr()`` leaves it
    out (#573).
    """

    diff: Diff | None
    raw: dict | None = Field(repr=False)

    def describe(self) -> str:
        """One line for the logs: the change, its ids and what changed, never a value."""
        diff = self.diff
        if diff is None:
            return "no change"
        instance = diff.instance
        target = f"instance {instance.id} of deployment {instance.deployment_id}"
        if isinstance(diff, InstanceCreation):
            return (
                f"create {target}, application version "
                f"{instance.application_version}, driver version "
                f"{instance.application_driver_version_id}"
            )
        if isinstance(diff, InstanceDeletion):
            return f"delete {target}"
        if isinstance(diff, InstanceUpdate):
            changes = "; ".join(entry.describe() for entry in diff.diffs)
            return f"update to {target}: {changes or 'no change'}"
        return f"{type(diff).__name__} for {target}"
