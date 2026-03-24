from __future__ import annotations

import strawberry

from styrmin_backend.api.scalars import JSON


@strawberry.type
class ParameterDefinition:
    name: str
    label: str
    kind: str
    default: JSON | None = None
    values: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict) -> ParameterDefinition:
        return cls(
            name=data["name"],
            label=data["label"],
            kind=data["kind"],
            default=data.get("default"),
            values=data.get("values"),
        )
