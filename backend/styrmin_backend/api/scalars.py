from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing import TypeAlias

    JSON: TypeAlias = dict[Any, Any]
else:
    from strawberry.scalars import JSON

__all__ = ["JSON"]
