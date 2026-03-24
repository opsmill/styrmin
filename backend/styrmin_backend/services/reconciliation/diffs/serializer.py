from functools import reduce
from typing import Any

from loguru import logger
from pydantic import BaseModel

from styrmin_backend.services.reconciliation.diffs.diffs import (
    ApplicationDriverVersionChange,
    ApplicationVersionChange,
    ContextChange,
    DiffEntry,
)


class ValuePath(BaseModel):
    """Represents a path to a value in a data structure."""

    path: list[str]

    def to_deep_diff_path(self) -> str:
        """Convert the path to a DeepDiff-compatible string."""
        return "root" + "".join(f"['{path}']" for path in self.path)


class DiffEntrySerializer:
    """Generic serializer for diffs."""

    def __init__(
        self,
        paths: list[ValuePath],
        diff_class: type[DiffEntry],
    ):
        self.paths = paths
        self.diff_class = diff_class

    def __repr__(self) -> str:
        return f"DiffEntrySerializer(paths={self.paths}, diff_class={self.diff_class})"

    def to_indexed(self) -> dict[str, "DiffEntrySerializer"]:
        return {path.to_deep_diff_path(): self for path in self.paths}

    def serialize(self, values: dict[str, Any]) -> DiffEntry:
        """Serialize the diff."""
        return self.diff_class.create(
            current_value=values["old_value"], new_value=values["new_value"]
        )


class DiffSerializer:
    SERIALIZERS: set[DiffEntrySerializer] = {
        DiffEntrySerializer(
            paths=[ValuePath(path=["application_version"])],
            diff_class=ApplicationVersionChange,
        ),
        DiffEntrySerializer(
            paths=[ValuePath(path=["context"])],
            diff_class=ContextChange,
        ),
        DiffEntrySerializer(
            paths=[ValuePath(path=["application_driver_version_id"])],
            diff_class=ApplicationDriverVersionChange,
        ),
    }

    def __init__(self) -> None:
        # Compute an index of serializers for fast lookup
        self._serializers = self._index_serializers()

    def _index_serializers(self) -> dict[str, DiffEntrySerializer]:
        """Index the serializers for fast lookup."""
        serializer_dict = reduce(
            lambda x, y: x | y,
            [serializer.to_indexed() for serializer in self.SERIALIZERS],
        )
        logger.debug("Indexed serializers: {}", serializer_dict)
        return serializer_dict

    def serialize(self, raw_diffs: dict[str, dict]) -> list[DiffEntry]:
        diffs = []

        # Apply the serializer to the raw diffs
        for path, diff_keys in raw_diffs.get("values_changed", {}).items():
            serializer = self._serializers.get(path, None)
            if serializer:
                logger.debug("Serializing diff for path: {}", path)
                diffs.append(serializer.serialize(values=diff_keys))
            else:
                logger.debug("Ignoring diff for path: {}", path)

        return diffs
