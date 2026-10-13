"""Strict checks for config dicts sent through a generated GraphQL input model.

The generated input models ignore unknown keys, so under full replacement a
misspelled key would be dropped and the stored value it meant to keep removed.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, get_args, get_origin

from pydantic import BaseModel

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo


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

    A config read back from the API holds the stored values, which the input models refuse.
    """
    if isinstance(data, list):
        return [to_graphql_enum_names(model, item) for item in data]
    if not isinstance(data, dict):
        return data
    fields = _fields_by_key(model)
    return {key: _field_value_with_enum_names(fields.get(key), value) for key, value in data.items()}
