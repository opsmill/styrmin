"""Shared output formatting and parsing utilities for styrminctl."""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args, get_origin

from pydantic import BaseModel
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from styrmin_sdk.exceptions import StyrminError

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

console = Console()


def parse_json_argument(value: str | None) -> Any | None:  # noqa: ANN401
    """Parse a JSON argument that can be either a file path (prefixed with @) or inline JSON.

    Args:
        value: The raw string from the CLI argument. None if not provided.

    Returns:
        Parsed JSON as a Python object, or None.

    Raises:
        ValueError: If the JSON is invalid or file cannot be read.
    """
    if value is None:
        return None

    if value.startswith("@"):
        file_path = Path(value[1:])
        if not file_path.exists():
            raise ValueError(f"Config file not found: {file_path}")
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in file {file_path}: {e}") from e

    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e


def _find_class[T](annotation: object, base: type[T]) -> type[T] | None:
    """Return the subclass of *base* inside an annotation such as ``X | None`` or ``list[X]``."""
    origin = get_origin(annotation)
    if origin is None:
        return annotation if isinstance(annotation, type) and issubclass(annotation, base) else None
    if origin is dict:
        return None
    return next((found for arg in get_args(annotation) if (found := _find_class(arg, base)) is not None), None)


def _fields_by_key(model: type[BaseModel]) -> dict[str, FieldInfo]:
    """Map every field name and alias of *model* to its field."""
    fields: dict[str, FieldInfo] = {}
    for name, field in model.model_fields.items():
        fields[name] = field
        if field.alias:
            fields[field.alias] = field
    return fields


def _unknown_key_paths(model: type[BaseModel], data: object, path: str) -> list[str]:
    if isinstance(data, list):
        return [found for i, item in enumerate(data) for found in _unknown_key_paths(model, item, f"{path}[{i}]")]
    if not isinstance(data, dict):
        return []
    fields = _fields_by_key(model)
    unknown: list[str] = []
    for key, value in data.items():
        key_path = f"{path}.{key}" if path else str(key)
        field = fields.get(str(key))
        if field is None:
            unknown.append(key_path)
        elif (nested := _find_class(field.annotation, BaseModel)) is not None:
            unknown.extend(_unknown_key_paths(nested, value, key_path))
    return unknown


def validate_input_strict(model: type[BaseModel], data: Any) -> None:  # noqa: ANN401
    """Refuse keys of *data* that are neither a field name nor an alias of *model*, at any depth.

    The generated SDK input models ignore unknown keys, so a misspelled key would be dropped silently.

    Raises:
        ValueError: Naming the path of every unknown key (``dedicated_ingress.servce``).
    """
    unknown = _unknown_key_paths(model, data, "")
    if unknown:
        raise ValueError(f"Unknown config key(s): {', '.join(unknown)}")


def _enum_key(value: str) -> str:
    return value.replace("_", "").upper()


def _field_value_with_enum_names(field: FieldInfo | None, value: object) -> object:
    if field is None:
        return value
    if (nested := _find_class(field.annotation, BaseModel)) is not None:
        return to_graphql_enum_names(nested, value)
    enum = _find_class(field.annotation, Enum)
    if enum is None or not isinstance(value, str):
        return value
    return next((member.value for member in enum if _enum_key(member.value) == _enum_key(value)), value)


def to_graphql_enum_names(model: type[BaseModel], data: Any) -> Any:  # noqa: ANN401
    """Return *data* with stored enum values (``http``, ``NoSchedule``) replaced by GraphQL names (``HTTP``, ``NO_SCHEDULE``).

    A config printed by ``clusters get`` holds the stored values, which the SDK input models refuse.
    """
    if isinstance(data, list):
        return [to_graphql_enum_names(model, item) for item in data]
    if not isinstance(data, dict):
        return data
    fields = _fields_by_key(model)
    return {key: _field_value_with_enum_names(fields.get(key), value) for key, value in data.items()}


def print_table(rows: list[dict[str, Any]], columns: list[str], title: str = "") -> None:
    """Print a list of objects as a Rich table."""
    table = Table(title=title)
    for col in columns:
        table.add_column(col, style="cyan")
    for row in rows:
        table.add_row(*[str(row.get(col, "")) for col in columns])
    console.print(table)


def print_error(message: str) -> None:
    """Print an error message in red."""
    console.print(f"[red]Error:[/red] {message}")


def print_success(message: str) -> None:
    """Print a success message in green."""
    console.print(f"[green]Success:[/green] {message}")


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    console.print(f"[yellow]Warning:[/yellow] {escape(message)}")


@contextmanager
def styrmin_error_handler() -> Generator[None]:
    """Catch StyrminError and ValueError, print a friendly message, and exit."""
    try:
        yield
    except (StyrminError, ValueError) as e:
        print_error(str(e))
        raise SystemExit(1) from e
